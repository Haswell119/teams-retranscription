# Deploying Hansard on Nutanix Kubernetes Platform

NKP is Konvoy (the cluster) plus Kommander (the management plane), the former
D2iQ DKP. This page covers what is genuinely NKP-specific. For everything
portable - values reference, bot design, secrets, upgrades, troubleshooting -
read [deployment.md](deployment.md) first. The chart is the same chart.

| NKP | Kubernetes |
|---|---|
| 2.17 | 1.34 |
| 2.16 | 1.33 |

The chart declares `kubeVersion: ">=1.30.0-0"`.

---

## One model, French and English

Meetings here are held in French and in English, often in the same hour and
sometimes in the same sentence. Hansard handles both with **one model**:
Parakeet TDT 0.6b v3, natively multilingual over 25 European languages.

For an NKP operator this means:

* **One worker pool, not two.** No French node pool, no English node pool, no
  language-based routing in the queue.
* **One model artifact to mirror** into the air gap - about 0.71 GB total, once.
* **~2 GB RSS per CPU worker.** Sizing a node pool is a single calculation.
* **`asr.language: auto`** is the default and sends no language tag at all.

Diarization (pyannote segmentation 3.0 + NVIDIA TitaNet embeddings) and VAD
(Silero) are language independent, so nothing downstream changes either.

### Diarization: the embedding model was chosen on evidence

Worth knowing before anyone proposes swapping a model to "improve accuracy".
Diarization uses two models - one segments audio into speech turns, one embeds
each turn for clustering - and the embedding model is where the quality lives.
Benchmarked end to end on synthetic multi-speaker meetings with exact ground
truth:

| Embedding model | Speaker confusion | DER |
|---|---|---|
| `nemo_en_titanet_small.onnx` (39 MB, CC-BY-4.0) | **0.01 %** | **14.96 %** |
| `3dspeaker_..._campplus_..._voxceleb_16k.onnx` (29 MB) | 47 % | 62.77 % |

CAM++ failed **even when given the correct number of clusters**, so the gap is
the embedding space itself, not a clustering hyperparameter. The bundle ships
TitaNet; CAM++ was removed.

The practical consequence for an operator: you can evaluate a different
embedding model, or retune clustering, **without rebuilding the model bundle**:

```yaml
diarization:
  engine: sherpa
  embeddingModel: nemo_en_titanet_small.onnx   # relative to models.mountPath
  clusteringThreshold: 0.95    # higher = fewer speakers; calibrated for TitaNet
  minimumSpeakerSeconds: 3.0   # shorter clusters are absorbed into their neighbour
  maxSpeakers: 8
```

Symptom-driven tuning: one person split into two speakers means the threshold is
too low; two people merged into one means it is too high. Phantom speakers from
crosstalk and backchannel are what `minimumSpeakerSeconds` suppresses. Note that
`clusteringThreshold` is calibrated for TitaNet's embedding space and does not
transfer to a different model - if you change `embeddingModel`, re-benchmark
before trusting the threshold.

---

## Know your tier before you plan

This is the single most important thing on this page. **A large part of what
"Kubernetes observability and backup" normally means is a Pro+ entitlement on
NKP.** On Starter these components do not exist - not disabled, *absent*, with
no CRDs:

| Component | Provides | Starter |
|---|---|---|
| kube-prometheus-stack | Prometheus, Grafana, Alertmanager, `ServiceMonitor`, `PrometheusRule` | **absent** |
| Loki | log aggregation | **absent** |
| Velero | backup / restore | **absent** |
| Gatekeeper | OPA policy | **absent** |
| External Secrets Operator | `ExternalSecret` | **absent** |
| NVIDIA GPU Operator | `nvidia.com/gpu` scheduling | **absent** (Pro) |

Present on every tier: **Cilium** (CNI on Nutanix/AHV, eBPF baseline since
2.17; Calico on other infrastructures), **Traefik v3** as ingress
(`ingressClassName: kommander-traefik`), **MetalLB** as load balancer,
**Flux** for GitOps, **cert-manager**, **Dex**.

### What the chart does about it

Nothing you have to configure. Every optional integration is a **tri-state**
value defaulting to `auto`, which means *emit this object only if its CRD exists
in the target cluster*:

```yaml
metrics:
  serviceMonitor:   { enabled: auto }   # monitoring.coreos.com/v1
  prometheusRule:   { enabled: auto }
  grafanaDashboard: { enabled: auto }
secrets:
  externalSecret:   { enabled: auto }   # external-secrets.io/v1beta1
worker:
  autoscaling:
    keda:           { enabled: auto }   # keda.sh/v1alpha1
cilium:
  networkPolicy:    { enabled: auto }   # cilium.io/v2
storage:
  cosi:             { enabled: auto }   # objectstorage.k8s.io/v1alpha1
```

Install with **the same values file** on Starter and on Pro. The Starter
cluster gets fewer objects and `NOTES.txt` lists exactly which ones were
skipped and why. Set a value to `true` to force an object (you assert the CRD
exists) or `false` to suppress it.

On Starter, metrics are still exposed on the orchestrator's HTTP port and on
port 9095 of every worker. Point any Prometheus you run yourself at them, and
import `deploy/helm/hansard/dashboards/hansard.json` into any Grafana.

---

## Networking constraints you cannot change

**NKP default CIDRs are pods `192.168.0.0/16` and services `10.96.0.0/12`, and
they are immutable after cluster deployment.** Nothing in this chart hardcodes
a pod CIDR; if you write your own NetworkPolicies alongside it, do not assume
`10.244.0.0/16`.

Note the collision risk: `192.168.0.0/16` is also a very common office LAN
range. If your SMTP relay or object store lives in `192.168.x.x`, the
`egress.mode: open` posture's `privateRanges` exclusion will block it. Use
`egress.mode: cidr` with an explicit `extraCIDRs` entry.

---

## Storage

| StorageClass | Backing | Access modes | Present by default |
|---|---|---|---|
| `nutanix-volume` | Nutanix Volumes over iSCSI | **RWO** | yes, and it is the cluster default |
| `nutanix-file` | Nutanix Files (NFS) | **RWX** | **no** - requires a licensed Nutanix Files deployment |

**The chart requires only RWO.** Nothing in it asks for `ReadWriteMany`. The
orchestrator's workspace PVC, the Redis PVC and the optional models PVC are all
RWO, and the values schema will accept `ReadWriteMany` only if you set it
deliberately.

```yaml
global:
  storageClass: nutanix-volume
orchestrator:
  persistence:
    enabled: true
    accessMode: ReadWriteOnce
    size: 20Gi
redis:
  persistence:
    accessMode: ReadWriteOnce
    size: 8Gi
```

Because the workspace is RWO, the orchestrator does not share a filesystem with
its workers. Artifacts move between them through `storage.*` (object storage or
a per-pod path), not a shared volume. If you *do* have licensed Nutanix Files
and want a shared workspace, set `accessMode: ReadWriteMany` and
`storageClass: nutanix-file` - but treat that as an optimisation, never a
prerequisite.

**Snapshots.** The chart gates any `VolumeSnapshot` usage on
`snapshot.storage.k8s.io/v1` being present. Velero is Pro+; on Starter, back up
the artifact bucket and your values, not the PVCs.

---

## GPU node pools

The NVIDIA GPU Operator is a **Pro** entitlement on NKP, and the vendor's GPU
documentation is behind a login. Everything below is therefore expressed in
plain Kubernetes terms that hold on any distribution - which is also how the
chart expresses it.

AHV supports both **PCI passthrough** and **vGPU**. vGPU additionally requires
an NVIDIA licence server reachable from the guest; passthrough does not. Choose
before you build the node pool: it is not a runtime setting.

Once the GPU Operator is installed and its node feature discovery has labelled
the nodes:

```yaml
asr:
  compute: both        # GPU and CPU workers, one shared consumer group
worker:
  gpu:
    replicaCount: 2
    resourceName: nvidia.com/gpu
    count: 1
    nodeSelector:
      nvidia.com/gpu.present: "true"
    tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
```

**`resourceName` is a value, not a constant.** With the GPU Operator's
time-slicing configured with `renameByDefault: true`, the schedulable resource
is no longer `nvidia.com/gpu` but **`nvidia.com/gpu.shared`**. If your GPU pods
sit `Pending` with `Insufficient nvidia.com/gpu` while `kubectl describe node`
shows capacity under a different name, that is why - change the value, not the
chart.

`asr.compute: both` is usually the right answer on NKP: the GPU pool takes the
steady load and the CPU pool absorbs bursts, because both consume the same
Redis Stream consumer group.

`asr.compute: auto` deliberately resolves to **CPU only**. Helm cannot inspect
node GPU capacity at template time, so `auto` will never silently place work on
GPUs you did not intend to use.

> A CUDA/cuDNN mismatch makes ONNX Runtime fall back to the CPU provider
> *silently*, so you pay for a GPU node and get CPU throughput. The GPU image's
> `HEALTHCHECK` fails when `CUDAExecutionProvider` is not registered, and the
> `AsrRealtimeFactorDegraded` alert catches it in production. Version matrix in
> `deploy/docker/README.md`.

---

## Air-gap deployment, end to end

An NKP air-gapped cluster cannot pull from any public registry. The full
procedure, on both sides of the gap.

### 1. Connected side: build everything

```bash
make -C deploy/docker all-images REGISTRY=stage.example.com/hansard
make -C deploy/docker models                     # 0.71 GB bundle, checksum-verified
make -C deploy/docker push-all  REGISTRY=stage.example.com/hansard
make -C deploy/docker sign      REGISTRY=stage.example.com/hansard COSIGN_KEY=cosign.key
make -C deploy/docker digests   REGISTRY=stage.example.com/hansard
```

Record the digests into your values file and turn on the guard:

```yaml
global:
  requireImageDigests: true       # install fails on any unpinned image
images:
  api:        { digest: sha256:... }
  worker:     { digest: sha256:... }
  modelsInit: { digest: sha256:... }
```

Regenerate the mirror list from the chart itself, so it cannot drift:

```bash
make -C deploy/docker images-txt      # writes deploy/helm/hansard/images.txt
```

### 2. Cross the gap

Three options, pick one.

**NKP's own bundle tooling** (preferred - it is what the platform expects):

```bash
# connected side
nkp create image-bundle --images-file deploy/helm/hansard/images.txt \
  --output-file hansard-images.tar
# air-gapped side
nkp push bundle --bundle hansard-images.tar \
  --to-registry harbor.nkp.internal/hansard \
  --to-registry-ca-cert-file /etc/ssl/certs/nkp-internal-ca.crt
```

**Registry to registry**, if the two can see each other:

```bash
make -C deploy/docker mirror TARGET_REGISTRY=harbor.nkp.internal/hansard
```

**A tarball**, if nothing can:

```bash
make -C deploy/docker save            # dist/hansard-images-0.1.0.tar
# carry it, then on the far side:
docker load -i hansard-images-0.1.0.tar && docker push ...
```

The model artifact travels the same way - it is an ordinary OCI image
(`hansard-models-init`), so whichever mechanism you chose handles it too.

### 3. Push the chart

NKP's Flux consumes charts as OCI artifacts:

```bash
helm package deploy/helm/hansard
helm push hansard-0.1.0.tgz oci://harbor.nkp.internal/hansard/charts \
  --ca-file /etc/ssl/certs/nkp-internal-ca.crt
```

### 4. Trust the internal CA

Harbor, Nutanix Objects and any TLS-inspecting proxy will present certificates
signed by your internal CA. Create the secret once and point the chart at it:

```bash
kubectl -n hansard create secret generic hansard-internal-ca \
  --from-file=ca-bundle.crt=/etc/ssl/certs/nkp-internal-ca.crt
```

```yaml
global:
  customCA:
    enabled: true
    existingSecret: hansard-internal-ca
    key: ca-bundle.crt
```

The chart mounts it and sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`,
`CURL_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS` and `AWS_CA_BUNDLE` in every container
that needs them. **Certificate verification is never disabled anywhere in this
chart, and there is no value that disables it.**

### 5. Install

```bash
helm install hansard oci://harbor.nkp.internal/hansard/charts/hansard \
  --version 0.1.0 -n hansard --create-namespace \
  -f deploy/helm/hansard/ci/airgap-values.yaml
```

`ci/airgap-values.yaml` is the reference posture: internal registry, digest
pinning, ORAS-staged models, Nutanix Objects for artifacts, polling instead of
webhooks, `capture.engine: file`.

### 6. What does not work behind an air gap

**Microsoft Graph change notifications.** They require a public inbound HTTPS
endpoint that answers a validation handshake within 10 seconds and returns 2xx
within 3. There is no way to satisfy that from an isolated cluster. Hansard
polls instead (`polling.enabled: true`), and `webhook.enabled` stays `false`.

**Live Teams meeting capture**, obviously, if the air gap is total. Set
`capture.engine: file` and `bot.enabled: false`, and feed the system recordings
through the API or object storage. If you have a controlled egress path to
Microsoft 365 only, keep the bot and read [Egress](#egress) below.

---

## Nutanix Objects and COSI

Nutanix Objects is S3-compatible, but three of its properties will bite you if
you configure it like AWS.

**Path-style addressing is mandatory.** Objects does not serve the wildcard DNS
that virtual-host-style addressing (`bucket.endpoint`) needs. The chart sets
`storage.s3.forcePathStyle: true` and the values schema *rejects* `false` - a
`const: true` constraint, because silently getting this wrong produces
NXDOMAIN errors that look like network faults.

**There is no region.** Objects is not region-aware, but the S3 SDKs demand a
region string. `us-east-1` is the conventional placeholder and is the default.

**It presents an internal certificate.** Supply the CA through
`global.customCA`. Do not use `insecure: true` or any skip-verify flag - the
chart has no such value.

```yaml
storage:
  backend: s3
  s3:
    endpoint: https://objects.nkp.internal
    bucket: hansard-artifacts
    region: us-east-1
    forcePathStyle: true
    credentials:
      existingSecret: hansard-objects   # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
```

### COSI

If the Container Object Storage Interface driver `ntnx.objectstorage.k8s.io` is
installed, the chart can provision the bucket for you. The `BucketClass` and
`BucketAccessClass` are created by the platform team, not by this chart, and on
NKP are conventionally both named **`cosi-nutanix-nkp`**:

```yaml
storage:
  backend: s3
  cosi:
    enabled: auto                        # only when objectstorage.k8s.io/v1alpha1 exists
    bucketClassName: cosi-nutanix-nkp
    bucketAccessClassName: cosi-nutanix-nkp
    protocol: S3
    deletionPolicy: Retain
```

The chart then emits a `BucketClaim` and a `BucketAccess`; the driver writes
credentials into a Secret named after the release, which you reference from
`storage.s3.credentials.existingSecret`. Both objects carry
`helm.sh/resource-policy: keep`, so uninstalling the release never deletes your
bucket.

`storage.cosi.enabled` is additionally gated on `storage.backend: s3`, so a
filesystem-backed install on a COSI-equipped cluster does not create a stray
bucket.

---

## GitOps with Flux and the Kommander catalog

NKP ships Flux on every tier. Two wrappers are provided; use whichever matches
how your platform team works.

**`deploy/helm/hansard/nkp/ocirepository.yaml`** - a plain Flux
`OCIRepository` + `HelmRelease`. Works on any tier, including Starter. Values
come from a ConfigMap so they can be reviewed as an ordinary Kubernetes object,
and the `verify:` block checks the chart's cosign signature.

**`deploy/helm/hansard/nkp/appdeployment.yaml`** - the Kommander catalog route:
a `ClusterApp` catalog entry plus an `AppDeployment` that distributes Hansard to
managed clusters from the management cluster's workspace namespace. Custom
catalogs and multi-cluster AppDeployments are Kommander features; if your
licence does not include them, use the Flux `HelmRelease` above or plain
`helm upgrade --install`. **The chart is identical in all three cases.**

Keep credentials out of both files. Point `secrets.existingSecret` at a Secret
the platform team manages, or use External Secrets on Pro+.

---

## Egress

Hansard defaults to deny-all and only opens what you configure. On NKP you get
two layers, and **you need both**.

### Layer 1: the portable NetworkPolicy (every tier, every CNI)

`networkPolicy.enabled: true` emits a deny-all baseline, a DNS rule, an
internal-traffic rule, an ingress rule scoped to the Traefik namespace, and
CIDR-based egress rules:

```yaml
networkPolicy:
  ingress:
    fromNamespaceSelector:
      kubernetes.io/metadata.name: kommander-traefik
  egress:
    mode: cidr
    teamsMedia:
      cidrs:   [52.112.0.0/14, 52.122.0.0/15]
      cidrsV6: [2603:1063::/38]
      udpPorts: [3478, 3479, 3480, 3481, 443]
      tcpPorts: [443]
    entra:
      cidrs: [20.20.32.0/19, 20.190.128.0/18, 20.231.128.0/19, 40.126.0.0/18]
      tcpPorts: [443, 80]
    extraCIDRs: [10.42.0.0/16]           # your SMTP relay, Objects, LLM
```

Teams media is allowed only for the **bot**; Entra and Graph only for the
**orchestrator**. The bot can never reach an identity endpoint.

### Layer 2: the CiliumNetworkPolicy (Nutanix/AHV, where Cilium is the CNI)

`cilium.networkPolicy.enabled: auto` adds `toFQDNs` rules, which is the only way
to express the endpoints Microsoft publishes as names:

```
*.teams.microsoft.com   teams.microsoft.com     *.teams.cloud.microsoft
*.cloud.microsoft       *.lync.com              *.skype.com
join.secure.skypeassets.com   mlccdnprod.azureedge.net   *.office.net   aka.ms
```

plus CRL/OCSP (`ocsp.digicert.com`, `crl3.digicert.com`, `crl4.digicert.com`,
`oneocsp.microsoft.com`, `ocsp.msocsp.com`, `crl.microsoft.com`,
`mscrl.microsoft.com`) - a blocked revocation check looks exactly like a hung
TLS handshake - and, for the orchestrator only, `graph.microsoft.com`,
`login.microsoftonline.com`, `login.microsoft.com`, `*.msauth.net`,
`*.msftauth.net`.

`cilium.networkPolicy.enableDnsProxy: true` emits the DNS visibility rule
(`toEndpoints` kube-dns with `rules.dns.matchPattern: "*"`). **Without it every
`toFQDNs` rule stays empty** - Cilium learns names only by observing DNS
answers through its proxy.

### Why you need both, stated plainly

> **`toFQDNs` cannot cover Teams media.** The client learns media relay
> addresses through ICE/TURN signalling, not DNS. Cilium's DNS proxy never sees
> an answer for them, so no `toFQDNs` rule ever matches, and the bot joins the
> meeting and hears nothing. The `toCIDRSet` rule for `52.112.0.0/14`,
> `52.122.0.0/15` and `2603:1063::/38` on UDP 3478-3481 is **not** redundant
> with `toFQDNs`. Keep it.
>
> And the reverse: **a CIDR allowlist cannot cover the Teams web endpoints**,
> because several of them are published as FQDNs with no IP ranges at all. Keep
> both layers.

### Layer 3 (alternative): an egress proxy

If your site already runs an HTTPS egress proxy that does name-based filtering,
delegate to it:

```yaml
networkPolicy:
  egress:
    mode: proxy
    proxy:
      host: egress-proxy.netpol.svc.cluster.local
      port: 3128
      cidr: 10.96.44.11/32
      noProxy: "localhost,127.0.0.1,.svc,.svc.cluster.local,.cluster.local"
```

The chart then permits egress only to that address and injects `HTTPS_PROXY`,
`HTTP_PROXY` and `NO_PROXY` into every container. Give the proxy's CA to
`global.customCA` if it terminates TLS.

---

## Ingress on NKP

```yaml
orchestrator:
  ingress:
    enabled: true
    className: kommander-traefik
    hosts:
      - host: hansard.apps.nkp.internal
        paths: [{ path: /, pathType: Prefix }]
    tls:
      - secretName: hansard-tls
        hosts: [hansard.apps.nkp.internal]
```

cert-manager is present on all tiers, so add your issuer annotation to
`orchestrator.ingress.annotations`. For a `LoadBalancer` Service instead, the
address must come from a configured MetalLB `IPAddressPool`:

```yaml
orchestrator:
  service:
    type: LoadBalancer
    loadBalancerIP: 10.42.10.50
    loadBalancerSourceRanges: [10.0.0.0/8]
```

---

## Sizing a node pool

Per CPU worker, transcribing at roughly 0.3-0.5x realtime with int8 Parakeet:

| | Request | Limit |
|---|---|---|
| CPU | 2 | *none, by design* |
| Memory | 3 Gi | 6 Gi |

**No CPU limits anywhere in this chart.** CFS throttling stalls the ONNX session
that has to keep up with realtime audio and the event loop that shepherds live
meetings. Requests reserve capacity; limits would only add jitter.

Steady-state RSS is about 2 GB per worker, because there is one multilingual
model rather than one per language. Add roughly 1 GB of headroom for the audio
buffer of the longest meeting you allow.

Each capture bot is a separate Job: 1 CPU request, and `memory request == limit`
(3 Gi with the default 1 Gi `/dev/shm`, because tmpfs pages are charged to the
container). Size the bot node pool by peak *concurrent meetings*, not by
meetings per day.

---

## Verifying an install

```bash
kubectl -n hansard rollout status deploy/hansard-orchestrator
helm test hansard -n hansard

# what did this cluster actually get?
kubectl -n hansard get servicemonitor,prometheusrule 2>&1 | head
kubectl -n hansard get ciliumnetworkpolicy
kubectl -n hansard get scaledobject 2>&1 | head

# is the model bundle intact?
kubectl -n hansard logs deploy/hansard-worker-cpu -c stage-models
# -> "model artifact verified"
```

`helm test` verifies the orchestrator answers `/readyz` **and** that the model
artifact staged and matches its `SHA256SUMS`.

---

## Where NKP's documentation was too thin to be certain

Stated honestly, because guessing here would cost you a maintenance window:

* **GPU.** NKP's GPU Operator documentation is behind a vendor login, so the
  chart deliberately expresses GPU scheduling in vanilla Kubernetes terms only
  (`nvidia.com/gpu`, `nvidia.com/gpu.present`, standard toleration). Confirm the
  exact node labels your GPU Operator deployment applies, and whether
  time-slicing renamed the resource to `nvidia.com/gpu.shared`, with
  `kubectl describe node <gpu-node>` before you size the pool.
* **Kommander AppDeployment API version.** `apps.kommander.d2iq.io/v1alpha3` is
  what current NKP releases use, but the group has been renamed once already in
  the D2iQ-to-Nutanix transition. Check
  `kubectl api-resources | grep -i kommander` on your management cluster and
  adjust `nkp/appdeployment.yaml` if it differs. The Flux `HelmRelease` route in
  `nkp/ocirepository.yaml` avoids this question entirely.
* **COSI class names.** `cosi-nutanix-nkp` for both the `BucketClass` and the
  `BucketAccessClass` is the documented convention, but they are created by your
  platform team and can be named anything. Confirm with
  `kubectl get bucketclass,bucketaccessclass` and override
  `storage.cosi.bucketClassName` / `bucketAccessClassName`.
* **The Traefik namespace.** `networkPolicy.ingress.fromNamespaceSelector`
  defaults to `kubernetes.io/metadata.name: kommander-traefik`. Some
  installations run the ingress controller in `kommander` instead. Verify with
  `kubectl get pods -A -l app.kubernetes.io/name=traefik` and adjust, or your
  Ingress will resolve but nothing will reach the pods.
* **`nkp create image-bundle` flags.** The bundle subcommand's exact flags have
  changed across NKP minor releases. Run `nkp create image-bundle --help` on
  your version; the `images.txt` file the chart generates is the stable input
  regardless of which flags the CLI wants.
