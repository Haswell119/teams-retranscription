# hansard

Sovereign, self-hosted Microsoft Teams meeting transcription and minutes.
Targets **Nutanix Kubernetes Platform (NKP)** and works unchanged on vanilla
Kubernetes (k3s, kind, EKS/AKS/GKE).

```
helm install hansard oci://harbor.internal/hansard/charts/hansard \
  --namespace hansard --create-namespace \
  --set global.imageRegistry=harbor.internal/hansard \
  --set secrets.create=false --set secrets.existingSecret=hansard-credentials
```

* `kubeVersion` `>=1.30.0-0` (NKP 2.16 -> Kubernetes 1.33, NKP 2.17 -> 1.34)
* No subcharts, no external Helm repositories.
* Requires **RWO** storage only.
* Full `restricted` Pod Security Standards compliance on every workload.

## Design rules this chart follows

**Capability gating, not assumption.** Every optional platform integration is a
*tri-state*: `true` always emits, `false` never emits, and `auto` (the default)
emits only when the corresponding CRD exists in the target cluster.

| Value | API group probed | Absent on |
|---|---|---|
| `metrics.serviceMonitor.enabled` | `monitoring.coreos.com/v1` | NKP Starter |
| `metrics.prometheusRule.enabled` | `monitoring.coreos.com/v1` | NKP Starter |
| `metrics.grafanaDashboard.enabled` | `monitoring.coreos.com/v1` | NKP Starter |
| `secrets.externalSecret.enabled` | `external-secrets.io/v1beta1` | NKP Starter |
| `worker.autoscaling.keda.enabled` | `keda.sh/v1alpha1` | most clusters |
| `cilium.networkPolicy.enabled` | `cilium.io/v2` | non-Cilium CNIs |
| `storage.cosi.enabled` | `objectstorage.k8s.io/v1alpha1` | clusters without COSI |

Install the chart on NKP Starter with the **same values** you use on Pro. The
Starter cluster simply gets fewer objects, and `NOTES.txt` says exactly which.

**No CPU limits, anywhere.** CFS throttling stalls the event loop that shepherds
a live meeting and the ONNX session that has to keep up with realtime audio.
Requests are set; memory is limited because memory is not compressible. The
values schema *rejects* `resources.limits.cpu`.

**Three service accounts, three blast radii.**

| Identity | Kubernetes API | Token mounted | Secrets |
|---|---|---|---|
| orchestrator | namespaced `Role`: jobs, pods, pods/log, events | yes | all |
| worker | none | no | queue + object storage |
| bot | none | **no** | **none** |

The bot receives a single-meeting join URL and a pre-signed upload URL from the
orchestrator and nothing else. `serviceAccounts.bot.automountServiceAccountToken`
is pinned to `false` by the values schema.

**Sovereignty is structural.** No telemetry. No egress except what
`networkPolicy.egress` allows. `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and
`HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS=false` on every workload, so a model can
never be pulled at pod start.

## Language

**One model serves both French and English.** `asr.modelId` defaults to
Parakeet TDT 0.6b v3, which is natively multilingual across 25 European
languages. There is no per-language model, no per-language worker pool, and no
per-language deployment - which is what keeps the CPU worker at roughly 2 GB
RSS. A meeting that switches between French and English transcribes in one pass.

`asr.language` defaults to `auto`, meaning **no language tag is sent at all**.
Set it to `fr` or `en` only if you want to pin the decoder for very short or
very noisy audio, and accept that a language switch mid-meeting will then be
mis-transcribed.

Diarization and VAD are language independent by construction.

### Diarization tuning

```yaml
diarization:
  engine: sherpa
  embeddingModel: nemo_en_titanet_small.onnx   # relative to models.mountPath
  clusteringThreshold: 0.95    # higher = fewer speakers
  minimumSpeakerSeconds: 3.0   # shorter clusters are absorbed into their neighbour
```

These reach the app as `HANSARD_DIARIZATION__EMBEDDING_MODEL`,
`..._CLUSTERING_THRESHOLD` and `..._MINIMUM_SPEAKER_SECONDS`, so diarization can
be retuned - or a different embedding model evaluated - **without rebuilding the
model bundle**.

The default was chosen by measurement: on synthetic multi-speaker meetings with
exact ground truth, `nemo_en_titanet_small.onnx` scored **0.01 % speaker
confusion (DER 14.96 %)** against **47 % (DER 62.77 %)** for
`3dspeaker_..._campplus_..._voxceleb_16k.onnx`, which failed even when handed
the correct number of clusters. `clusteringThreshold: 0.95` is calibrated for
TitaNet's embedding space and does not transfer to another model - re-benchmark
if you change `embeddingModel`.

Metrics carry a bounded `language` label on
`hansard_asr_transcribe_duration_seconds` and `hansard_asr_realtime_factor`
(25 known codes plus `unknown`), so the dashboard can show the language mix
without any cardinality risk.

## Values that matter most

### Images

Everything is prefixed by `global.imageRegistry`, including Redis and the model
artifact, so a single value moves the whole deployment behind an internal
registry. Pin by digest in production:

```
make -C deploy/docker digests
# paste into images.<name>.digest, then:
--set global.requireImageDigests=true      # install fails on any unpinned image
```

`images.txt` is generated from the chart itself
(`hack/gen-images-txt.sh`) and is the authoritative mirror list.

### Models

| `models.source` | Mechanism | Notes |
|---|---|---|
| `initImage` **(default)** | busybox init container copies into an `emptyDir`, then `sha256sum -c` | works everywhere |
| `image` | Kubernetes `image:` volume | ~11.5 s warm start, size independent, but **ImageVolume is beta and disabled by default in 1.33** and needs containerd >= 2.1. Verify before enabling |
| `oras` | ORAS init container pulls an OCI artifact | set `models.oras.reference` |
| `s3` | `mc mirror` init container | re-downloads on every pod start |
| `pvc` | pre-populated volume | the only zero-network option |

One mount path (`models.mountPath`, default `/models`), one env contract, all
five sources.

### Compute

`asr.compute`:

* `auto` **(default)** - CPU only. Helm cannot see node GPU capacity at template
  time, so `auto` never silently schedules onto GPUs.
* `cpu` / `gpu` - one deployment.
* `both` - GPU **and** CPU deployments consuming the **same Redis Stream
  consumer group**, i.e. one logical worker pool spread over two node classes.

`worker.gpu.resourceName` is a **value**, not a constant: with GPU Operator
time-slicing and `renameByDefault: true` the schedulable resource becomes
`nvidia.com/gpu.shared`.

### Autoscaling

Precedence, highest first:

1. KEDA `ScaledObject` on Redis Stream **pending entries** - the only honest
   backlog signal (`worker.autoscaling.keda.enabled: auto`).
2. Plain CPU `HorizontalPodAutoscaler` (`worker.autoscaling.hpa.enabled`).
3. Fixed replica counts.

**KEDA is never required.** The orchestrator has its own straightforward HPA
(`orchestrator.autoscaling`).

### Secrets

Exactly one of the three, enforced by both `values.schema.json` (a `oneOf`) and
a `fail()` in `_helpers.tpl`:

```yaml
secrets: { create: true }                             # evaluation / encrypted GitOps repos
secrets: { create: false, existingSecret: my-secret } # production default
secrets: { create: false, externalSecret: { enabled: auto, secretStoreRef: {...} } }  # NKP Pro+
```

### Network policy

Two layers, both optional, both off by nothing:

* `templates/networkpolicy.yaml` - portable, CIDR based. This is the floor and
  it works on every CNI.
* `templates/ciliumnetworkpolicy.yaml` - `toFQDNs` plus a DNS-proxy rule. Cilium
  is the CNI on NKP/AHV.

> **Both are needed, and neither is redundant.** Several Teams endpoints
> (`*.teams.cloud.microsoft`, `*.cloud.microsoft`, `*.lync.com`,
> `join.secure.skypeassets.com`, `aka.ms`) are published as FQDNs with **no IP
> ranges**, so a pure CIDR allowlist cannot be complete. And Teams **real-time
> media** goes to IPs learned through ICE/TURN signalling rather than DNS, so
> Cilium's DNS proxy never sees them and `toFQDNs` alone silently drops all
> audio - which is why the `toCIDRSet` rule for `52.112.0.0/14`,
> `52.122.0.0/15`, `2603:1063::/38` on UDP 3478-3481 must stay.

`networkPolicy.egress.mode` is `cidr` (default), `proxy` (everything through an
HTTPS egress proxy, also injected as `HTTPS_PROXY`) or `open` (evaluation only).

### Capture bot

The bot is not a Deployment. `templates/bot/job-template-configmap.yaml` renders
a **Job template** into a ConfigMap; the orchestrator instantiates it once per
meeting, substituting `${HANSARD_JOB_NAME}`, `${HANSARD_MEETING_REF}`,
`${HANSARD_JOIN_URL}` and `${HANSARD_UPLOAD_URL}`.

Job shape: `restartPolicy: Never`, `backoffLimit: 1`,
`ttlSecondsAfterFinished`, `activeDeadlineSeconds`,
`terminationGracePeriodSeconds: 90` (the bot must leave the meeting and flush
its last audio), and
`cluster-autoscaler.kubernetes.io/safe-to-evict: "false"`.

Chromium's own sandbox needs user-namespace clone syscalls that the
`RuntimeDefault` seccomp profile blocks. Playwright's answer is a custom seccomp
profile, but Pod Security Standards `baseline`/`restricted` forbid `Unconfined`,
`Localhost` requires per-node file placement no operator can guarantee, and
`SYS_ADMIN` is not in the baseline allow-list. The chart therefore uses
**`--no-sandbox` inside a fully restricted pod**: `RuntimeDefault` seccomp,
`runAsNonRoot`, `allowPrivilegeEscalation: false`, `capabilities: drop: [ALL]`,
`readOnlyRootFilesystem: true`, no service account token. Defensible because the
bot renders exactly one origin, is a single-use Job, and carries no secrets.
`bot.hostUsers: false` adds a user namespace where the cluster supports it.

`/dev/shm` is an `emptyDir{medium: Memory}` because `hostIPC: true` is forbidden
by the baseline standard. **Those bytes count against the container memory
limit**: `bot.shm.sizeLimit: 1Gi` plus a 2 GiB working set needs
`bot.resources.limits.memory: 3Gi`. Prefer `bot.chromium.disableDevShmUsage:
true` with a smaller shm if memory is tight.

## Observability

`metrics.enabled` serves `/metrics` on the orchestrator's HTTP port and on
`worker.metricsPort` (9095) regardless of what the cluster offers. The
ServiceMonitor, PrometheusRule and Grafana dashboard ConfigMap are all `auto`.

Metric names, all prefixed `hansard_`: `build_info`, `meetings_scheduled_total`,
`bot_join_attempts_total{result}`, `bot_join_duration_seconds`, `bot_active`,
`queue_pending{stream,group}`,
`asr_transcribe_duration_seconds{model,compute,language}`,
`asr_realtime_factor{model,compute,language}`, `asr_failures_total{reason}`,
`diarization_speakers`, `minutes_generated_total`,
`delivery_attempts_total{channel,result}`, `object_storage_reachable`.

**No metric ever carries a meeting id, user id, e-mail or join URL.** That is
enforced in code: `src/hansard/observability/metrics.py` raises
`UnsafeLabelError` at import time if such a label name is introduced.

Alerts: `BotJoinFailureRateHigh`, `NoBotsJoinedRecently`, `QueuePendingGrowing`,
`AsrRealtimeFactorDegraded`, `AsrFailuresSustained`, `ObjectStorageUnreachable`.

## Validate before you install

```
deploy/helm/hansard/hack/validate.sh    # everything below, in one command
helm test hansard -n hansard            # after install, against a real cluster
```

`validate.sh` runs `helm lint` on every posture, renders each one twice (with no
optional CRDs and with all of them) and validates the output with `kubeconform`
against real upstream CRD schemas, asserts that NKP Starter receives no
Pro-tier objects, asserts that the guard rails reject twelve invalid value
combinations, and checks restricted Pod Security Standards compliance plus the
capture-bot Job invariants across every rendered object.

`ci/*-values.yaml` are the postures this chart is tested against:

| File | Posture |
|---|---|
| `default-values.yaml` | portable Kubernetes, nothing assumed |
| `airgap-values.yaml` | disconnected, digest-pinned, ORAS models, Objects/S3, file capture |
| `nkp-starter-values.yaml` | NKP Starter: no ServiceMonitor, no Grafana, no ESO, no KEDA |
| `restricted-values.yaml` | hardest posture that still runs a browser bot |
| `gpu-values.yaml` | GPU + CPU pools sharing one consumer group |

## Further reading

* `docs/deployment-nkp.md` - NKP tiers, storage classes, GPU pools, air gap,
  Nutanix Objects/COSI, Flux catalog wrapper, Cilium FQDN egress.
* `docs/deployment.md` - portable Kubernetes and a laptop `docker compose`
  quickstart.
* `deploy/docker/README.md` - building, mirroring and signing the images.
