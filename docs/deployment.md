# Deploying Hansard

Two paths:

* **[Laptop quickstart](#laptop-quickstart-docker-compose)** - `docker compose`,
  file-based transcription, no browser bot, working in about ten minutes.
* **[Kubernetes](#kubernetes)** - the real deployment, portable across k3s,
  kind, EKS, AKS, GKE and NKP.

For Nutanix Kubernetes Platform specifically - tiers, storage classes, GPU node
pools, the air-gap procedure, Nutanix Objects and the Flux catalog wrapper -
read **[deployment-nkp.md](deployment-nkp.md)** instead.

---

## One model, French and English

Hansard transcribes **French and English with a single model**. `asr.modelId`
defaults to NVIDIA Parakeet TDT 0.6b v3, which is natively multilingual across
25 European languages.

What follows from that, concretely:

* **No per-language deployment.** There is no French worker pool and no English
  worker pool. One deployment, one queue, one set of pods.
* **No language tag.** `asr.language` defaults to `auto`, which sends no
  language hint at all. The model works it out. A meeting where people switch
  between French and English transcribes correctly in a single pass - something
  engines that demand a language up front cannot do.
* **One model in memory.** This is what keeps the CPU worker to a single
  recogniser: roughly **2.8 GB RSS** with the shipped float32 weights, and up to
  **3.6 GB** for the full pipeline at peak. Running two monolingual models would
  double it, and holding both loaded would double it again. The INT8 profile
  (`HANSARD_ASR__QUANTIZATION=int8`) brings the recogniser down to about 1.4 GB
  at the cost of roughly two points of French word error rate — see
  [benchmarks §5](benchmarks.md#5-choosing-a-quantization-profile).
* **Diarization and VAD are language independent** by construction: pyannote
  segmentation 3.0 for speaker turns, NVIDIA TitaNet for speaker embeddings,
  Silero for voice activity. Nothing there changes with language either.

Set `asr.language: fr` or `asr.language: en` only if you want to pin the
decoder for very short or very noisy audio, and accept that a language switch
mid-meeting will then be mis-transcribed. Leave it on `auto` otherwise.

### Tuning diarization

Speaker separation has three knobs, and none of them requires rebuilding the
model bundle:

```yaml
diarization:
  engine: sherpa
  embeddingModel: nemo_en_titanet_small.onnx   # relative to models.mountPath
  clusteringThreshold: 0.99    # higher = fewer speakers
  minimumSpeakerSeconds: 3.0   # shorter clusters are absorbed into their neighbour
```

Tune by symptom: one person appearing as two speakers means
`clusteringThreshold` is too low; two people merged into one means it is too
high. Phantom speakers from crosstalk are what `minimumSpeakerSeconds` removes.

The default embedding model was picked by measurement, not reputation. On
synthetic multi-speaker meetings with exact ground truth, TitaNet scored 0.01 %
speaker confusion (DER 14.96 %) against 47 % (DER 62.77 %) for CAM++ - which
failed even when handed the correct number of clusters. If you change
`embeddingModel`, re-benchmark: `clusteringThreshold: 0.99` is calibrated for
TitaNet's embedding space and does not transfer.

---

## Laptop quickstart (docker compose)

This is the **file-based** path: you hand it a recording, it hands you a
transcript and minutes. There is deliberately no browser bot here - a Teams bot
needs a real Kubernetes Job with its own `/dev/shm` budget, egress policy and
grace period, and compose cannot model that honestly.

### Requirements

* Docker with BuildKit (Docker 23+), about 6 GB free disk for the images plus
  3.2 GB for the model bundle
* 4 CPU cores and 8 GB RAM is comfortable; it will run on less, slower

### Steps

```bash
cd deploy/compose
cp .env.example .env

# 1. Build the images (api, worker, model bundle).
docker compose --profile build build

# 2. Download and checksum-verify the model bundle. ONCE.
#    ~3.2 GB. Nothing is ever downloaded again after this.
docker compose run --rm models

# 3. Start Redis, the API and one worker.
docker compose up -d

# 4. Confirm the environment.
docker compose run --rm cli doctor
```

`doctor` should report `ok` for ffmpeg, the models directory, the ONNX runtime
and the diarization runtime, and `disabled` for telemetry:

```
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check               ┃ Status   ┃ Detail                            ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ffmpeg              │ ok       │ /usr/bin/ffmpeg                   │
│ models directory    │ ok       │ /models                           │
│ ONNX runtime        │ ok       │ onnxruntime                       │
│ diarization runtime │ ok       │ sherpa_onnx                       │
│ telemetry           │ disabled │ Hansard never sends data anywhere │
└─────────────────────┴──────────┴───────────────────────────────────┘
```

### Transcribe something

```bash
cp ~/Recordings/comite-de-pilotage.m4a deploy/compose/inbox/
docker compose run --rm cli transcribe /inbox/comite-de-pilotage.m4a --output /artifacts
ls deploy/compose/artifacts/comite-de-pilotage/
# transcript.md  transcript.json  transcript.vtt  metrics.json
```

Any format ffmpeg can read works: `.wav`, `.m4a`, `.mp3`, `.ogg`, `.mkv`.
French, English or both in the same file - you do not tell it which.

### Minutes

Summarisation is off until you give it an endpoint you host yourself. Point it
at any OpenAI-compatible server (llama.cpp, vLLM, Ollama, LM Studio):

```bash
# in deploy/compose/.env, or on the command line:
docker compose run --rm \
  -e HANSARD_MINUTES__ENABLED=true \
  -e HANSARD_MINUTES__ENDPOINT=http://host.docker.internal:8080/v1 \
  -e HANSARD_MINUTES__MODEL_ID=qwen3-8b-instruct \
  cli transcribe /inbox/comite-de-pilotage.m4a --output /artifacts
```

Hansard never ships a default endpoint. If you do not configure one, no text
leaves the machine, because there is nowhere for it to go.

### Tuning on a laptop

| Variable | Effect |
|---|---|
| `OMP_NUM_THREADS` | ONNX Runtime threads per worker. Default 4. Set to your core count minus two. |
| `WORKER_REPLICAS` | Parallel workers. One per ~4 GB RAM. |
| `HANSARD_ASR__QUANTIZATION` | `none` (default, float32, ~2.8 GB RSS) or `int8` (low-memory, ~1.4 GB, no faster, ~2 WER points worse in French) |
| `HANSARD_ASR__BATCH_SIZE` | Segments per ONNX call. Higher = faster and hungrier. |

### Tearing down

```bash
docker compose down                 # keeps the model volume
docker compose down -v              # deletes it too; you will re-download 3.2 GB
```

---

## Kubernetes

### Requirements

* Kubernetes >= 1.30
* A default StorageClass supporting **ReadWriteOnce**. The chart never requires
  ReadWriteMany.
* An ingress controller, if you want the API reachable from outside the cluster
* Roughly, per worker: 2 CPU / 3 GB request, 6 GB limit. The float32 pipeline
  was measured at up to 3.6 GB peak on the synthetic fixtures, so it lives inside
  the limit but above the request; give workers a node with headroom, or switch
  them to the INT8 profile
* **Long spontaneous meetings need more than that.** On the AMI corpus — real
  25-minute meetings at the default 120-second segment ceiling — peak RSS reached
  **7.1 GB**, above the chart's 6 GB limit. For that kind of recording, raise
  `worker.cpu.resources.limits.memory`, or lower the segment ceiling through
  `config.extraEnv` (the chart does not model audio settings directly):

  ```yaml
  config:
    extraEnv:
      - name: HANSARD_AUDIO__MAX_SEGMENT_SECONDS
        value: "60"
  ```

  Shorter segments cost word error rate — the exchange rate is in
  [benchmarks](benchmarks.md#6-engineering-findings-worth-knowing)

Not required, used if present: Prometheus Operator, Grafana, KEDA, Cilium,
External Secrets Operator, COSI. Every one of them is detected at template time
and skipped when absent.

### Install

```bash
helm install hansard oci://ghcr.io/haswell119/charts/hansard \
  --version 0.1.0 \
  --namespace hansard --create-namespace \
  --values my-values.yaml
```

Or from a checkout:

```bash
helm install hansard deploy/helm/hansard -n hansard --create-namespace \
  -f deploy/helm/hansard/ci/default-values.yaml
```

Then:

```bash
kubectl -n hansard rollout status deploy/hansard-orchestrator
helm test hansard -n hansard
```

`helm test` checks two things that matter: the orchestrator answers `/readyz`,
and the model artifact was staged and matches its `SHA256SUMS`.

### Namespace hardening

The chart's workloads are all `restricted`-compliant. Label the namespace so
the API server enforces it:

```bash
kubectl label namespace hansard \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/warn=restricted
```

Helm cannot label a namespace it did not create, which is why this is a manual
step rather than a chart value.

### The five decisions

#### 1. Where do images come from?

```yaml
global:
  imageRegistry: registry.example.internal/hansard
  imagePullSecrets:
    - name: registry-pull
  requireImageDigests: true      # refuse to install anything unpinned
images:
  api:
    digest: sha256:...
```

`deploy/helm/hansard/images.txt` is the authoritative mirror list and is
generated from the chart itself, so it cannot drift.

#### 2. Where do models come from?

Never from the internet at pod start. `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1` and `HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS=false` are
set on every workload, and there is no value that turns them off.

| `models.source` | How | When |
|---|---|---|
| `initImage` **(default)** | init container copies the bundle into an `emptyDir`, then verifies `SHA256SUMS` | works everywhere |
| `image` | Kubernetes `image:` volume | ~11.5 s warm start regardless of model size, but **ImageVolume is beta and disabled by default in 1.33** and needs containerd >= 2.1. Check both before enabling |
| `oras` | ORAS init container pulls an OCI artifact | you already publish models as OCI artifacts |
| `s3` | `mc mirror` init container | re-downloads on every pod start; fine for small models, painful for large ones |
| `pvc` | pre-populated volume | zero network |

#### 3. CPU, GPU, or both?

```yaml
asr:
  compute: auto        # auto | cpu | gpu | both
  quantization: none   # none (float32, benchmarked default) | int8 (low-memory)
```

`auto` resolves to **CPU**. Helm cannot see node GPU capacity at template time,
so `auto` never silently schedules onto GPUs - ask for them explicitly.

**Set `asr.quantization` explicitly.** The application default is `none`, but the
chart's own `values.yaml` still ships `int8`, so a default `helm install` gets the
low-memory profile - no faster, and about two points of French word error rate
worse. Pass `none` unless you specifically want INT8.

`both` runs a GPU deployment and a CPU deployment against the **same Redis
Stream consumer group**: one logical worker pool spread over two node classes,
so a burst overflows from GPU to CPU instead of queueing.

GPU workers use plain Kubernetes vocabulary:

```yaml
worker:
  gpu:
    resourceName: nvidia.com/gpu     # nvidia.com/gpu.shared with time-slicing
    count: 1
    nodeSelector:
      nvidia.com/gpu.present: "true"
    tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
```

`resourceName` is a value, not a constant, because the NVIDIA GPU Operator's
time-slicing with `renameByDefault: true` presents the device to the scheduler
as `nvidia.com/gpu.shared`.

> If GPU workers are no faster than CPU workers, check that ONNX Runtime
> actually registered the CUDA provider. A CUDA/cuDNN mismatch does not fail
> loudly - it falls back to CPU. The GPU image's `HEALTHCHECK` catches this;
> see `deploy/docker/README.md`.

#### 4. How does it scale?

Highest precedence first:

1. **KEDA** `ScaledObject` on Redis Stream *pending entries*. This is the only
   honest backlog signal: CPU utilisation on an idle ASR worker tells you
   nothing about how much audio is waiting.
2. **HPA** on CPU utilisation (`worker.autoscaling.hpa.enabled=true`).
3. **Fixed replicas.**

KEDA is `auto`, so it is used if installed and ignored if not. **It is never
required.**

#### 5. What may it talk to?

`networkPolicy.enabled` is `true` by default and starts from deny-all.

```yaml
networkPolicy:
  egress:
    mode: cidr        # cidr | proxy | open
```

* `cidr` - only the CIDRs you list. Ships with Microsoft's published Teams media
  and Entra ranges, and `extraCIDRs` for your SMTP relay, object store and LLM.
* `proxy` - everything through one HTTPS egress proxy, which is also injected
  into the pods as `HTTPS_PROXY`. Best fit when a proxy already does name-based
  filtering for you.
* `open` - the internet minus RFC1918. **Evaluation only.**

> **A CIDR allowlist cannot be complete for Teams.** Several endpoints
> (`*.teams.cloud.microsoft`, `*.cloud.microsoft`, `*.lync.com`,
> `join.secure.skypeassets.com`, `aka.ms`) are published by Microsoft as FQDNs
> with no corresponding IP ranges. On Cilium the chart also emits a
> `CiliumNetworkPolicy` with `toFQDNs` to cover them; elsewhere, use
> `mode: proxy`. See [deployment-nkp.md](deployment-nkp.md#egress).

### The capture bot

The bot is not a Deployment. The chart renders a **Job template** into a
ConfigMap; the orchestrator instantiates it once per meeting.

```yaml
bot:
  enabled: true
  terminationGracePeriodSeconds: 90     # leave the meeting, flush the last audio
  ttlSecondsAfterFinished: 900
  activeDeadlineSeconds: 15000
  shm:
    sizeLimit: 1Gi
  resources:
    requests: { cpu: "1", memory: 3Gi }
    limits:   { memory: 3Gi }
```

Three things about it are worth understanding before you tune it:

**It runs Chromium with `--no-sandbox`, on purpose.** Chromium's internal
sandbox needs user-namespace clone syscalls that the `RuntimeDefault` seccomp
profile blocks. The usual answer is a custom seccomp profile, but the
`baseline` and `restricted` Pod Security Standards forbid `Unconfined`,
`Localhost` requires placing a file on every node, and `SYS_ADMIN` is not in the
baseline allow-list. So the chart drops Chromium's own sandbox and keeps the
Kubernetes one: `RuntimeDefault` seccomp, non-root, no capabilities, no
privilege escalation, read-only root filesystem, no service account token. That
trade is defensible here because the bot renders exactly one origin, is a
single-use Job, and holds no secrets.

**`/dev/shm` memory counts against the container limit.** It is an
`emptyDir{medium: Memory}` because `hostIPC: true` is forbidden by the baseline
standard, and tmpfs pages are charged to the pod. `shm.sizeLimit: 1Gi` plus a
2 GiB working set needs `limits.memory: 3Gi`. If memory is tight, set
`bot.chromium.disableDevShmUsage: true` and drop `shm.sizeLimit` to `256Mi` -
Chromium then puts its cache on `/tmp` instead.

**It never receives a long-lived secret.** The orchestrator hands each bot a
single-meeting join URL and a pre-signed, short-TTL upload URL. Its service
account has no Role and its token is not mounted.

### Secrets

Exactly one of these, enforced by the values schema:

```yaml
secrets: { create: true }                                # evaluation only
secrets: { create: false, existingSecret: hansard-credentials }
secrets: { create: false, externalSecret: { enabled: auto, secretStoreRef: { name: vault } } }
```

Keys the chart reads from that Secret:

```
HANSARD_API__API_KEY
HANSARD_DELIVERY__GRAPH__TENANT_ID
HANSARD_DELIVERY__GRAPH__CLIENT_ID
HANSARD_DELIVERY__GRAPH__CLIENT_SECRET
HANSARD_DELIVERY__SMTP__USERNAME
HANSARD_DELIVERY__SMTP__PASSWORD
HANSARD_MINUTES__API_KEY
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

### Calendar discovery: polling, not webhooks

Microsoft Graph change notifications need a **public inbound HTTPS endpoint**
that answers a validation handshake within 10 seconds and returns 2xx within 3.
That is incompatible with a private or air-gapped cluster, so Hansard **polls**
by default:

```yaml
polling:
  enabled: true
  intervalSeconds: 60
webhook:
  enabled: false
```

If you do have a public endpoint and want webhooks, `webhook.enabled=true`
requires `webhook.ingress.enabled=true` (the chart fails otherwise) and
restricts inbound to Microsoft's published ranges:

```
20.20.32.0/19   20.190.128.0/18   20.231.128.0/19   40.126.0.0/18
```

Enforce those at the perimeter too - an Ingress annotation is not a firewall.

### Observability

`/metrics` is served on the orchestrator's HTTP port and on port 9095 of every
worker, whether or not the cluster has Prometheus. If the Prometheus Operator
CRDs exist, the chart also emits a `ServiceMonitor`, a `PrometheusRule` and a
Grafana dashboard ConfigMap. If they do not, it emits none of them and
`NOTES.txt` tells you so.

Metrics are prefixed `hansard_`. The ones you will actually look at:

| Metric | Read it as |
|---|---|
| `hansard_bot_join_attempts_total{result}` | are we getting into meetings |
| `hansard_bot_join_duration_seconds` | how long the lobby is holding us |
| `hansard_queue_pending{stream,group}` | is the fleet keeping up |
| `hansard_asr_realtime_factor{model,compute,language}` | processing seconds per audio second; above 1.0 you are losing ground |
| `hansard_asr_failures_total{reason}` | what is breaking |
| `hansard_delivery_attempts_total{channel,result}` | is anything reaching anyone |

**No metric carries a meeting id, user id, e-mail address or join URL.** That is
not a convention, it is enforced: `src/hansard/observability/metrics.py` raises
`UnsafeLabelError` at import time if such a label is introduced. The `language`
label is bounded to 25 known codes plus `unknown`, so it is safe.

Import `deploy/helm/hansard/dashboards/hansard.json` into any Grafana.

### Upgrades

```bash
helm upgrade hansard deploy/helm/hansard -n hansard -f my-values.yaml
```

The orchestrator rolls with `maxUnavailable: 0`. Workers finish their current
segment: `terminationGracePeriodSeconds` is 120 and KEDA's scale-down
stabilisation window is 300 s, so a worker is never pulled mid-transcription.
Bots already in meetings are Jobs and are not touched by a chart upgrade at all
- they run to completion on the old image.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Init container `stage-models` fails on `sha256sum -c` | mirrored bundle is truncated or stale | re-mirror; `make -C deploy/docker models-verify` on the source side |
| Pods `CreateContainerConfigError` | `secrets.existingSecret` does not exist in the namespace | create it, or switch to `secrets.create=true` for a test |
| Bot joins but records silence | Teams media egress blocked | UDP 3478-3481 to `52.112.0.0/14` and `52.122.0.0/15` must be allowed. `toFQDNs` alone will not do it |
| Bot never leaves the lobby | tenant admission policy | check `hansard_bot_join_attempts_total{result="lobby_timeout"}` and raise `capture.lobbyTimeoutSeconds` |
| GPU workers no faster than CPU | CUDA/cuDNN mismatch, ORT fell back to CPU | see `deploy/docker/README.md`; the GPU image `HEALTHCHECK` detects it |
| `LocalEntryNotFoundError ... HF_HUB_OFFLINE` | something asked for a model that is not in the bundle | that is the sovereignty guard working. Add the model to `deploy/docker/models.manifest` and rebuild the bundle |
| `helm test` fails on `/readyz` | orchestrator cannot reach Redis | check the `allow-internal` NetworkPolicy and `redis.external.url` |
| Workers idle while the queue grows | consumer group mismatch | `queue.stream` and `queue.group` must match across orchestrator and workers; they do by default |
