# deploy/

Everything needed to run Hansard somewhere other than your own laptop.

```
deploy/
  docker/     container images + the model bundle
  helm/       the Helm chart (NKP-tuned, portable everywhere)
  compose/    laptop evaluation stack, file-based path
```

## Start here

| I want to... | Go to |
|---|---|
| Try it on my laptop in ten minutes | [`compose/docker-compose.yml`](compose/docker-compose.yml), [`../docs/deployment.md`](../docs/deployment.md#laptop-quickstart-docker-compose) |
| Deploy on any Kubernetes | [`../docs/deployment.md`](../docs/deployment.md#kubernetes) |
| Deploy on Nutanix Kubernetes Platform | [`../docs/deployment-nkp.md`](../docs/deployment-nkp.md) |
| Build, mirror or sign the images | [`docker/README.md`](docker/README.md) |
| Read the values reference | [`helm/hansard/README.md`](helm/hansard/README.md) |
| Mirror images into an air gap | [`helm/hansard/images.txt`](helm/hansard/images.txt) |

## What is here

### `docker/`

| File | Builds |
|---|---|
| `Dockerfile.api` | orchestrator + HTTP API + CLI |
| `Dockerfile.worker` | CPU ASR/diarization worker (ONNX Runtime, no PyTorch) |
| `Dockerfile.worker-gpu` | CUDA worker (ONNX Runtime CUDA EP) |
| `Dockerfile.models` | the model bundle: host directory, `FROM scratch` image, and busybox copier |
| `models.manifest` | every model URL with a pinned SHA-256 - the only place provenance lives |
| `models.NOTICE` | third-party attribution, copied into the bundle as `/models/NOTICE` |
| `fetch-models.sh` | build-time downloader and verifier |
| `Makefile` | build, push, mirror, sign, SBOM, air-gap tarball |

The **browser capture bot image is not here**: it belongs to the capture
adapter at `src/hansard/adapters/capture/docker/`. The Makefile has a `bot`
target that builds it where it lives.

### `helm/hansard/`

```
Chart.yaml  values.yaml  values.schema.json  README.md  images.txt  LICENSE
templates/            the chart
dashboards/           a real Grafana dashboard
nkp/                  Flux OCIRepository + Kommander AppDeployment wrappers
ci/                   five tested value postures
hack/                 images.txt generator
```

### `compose/`

A file-based evaluation stack: Redis, the API, one worker, and a one-shot model
downloader. No browser bot - that needs a real Kubernetes Job.

## Three things worth knowing before you read anything else

**One model, French and English.** Parakeet TDT 0.6b v3 is natively
multilingual. There is no per-language image, no per-language worker pool and no
language tag to pass (`asr.language: auto` is the default). This is what keeps a
CPU worker at roughly 2 GB RSS.

**Nothing is downloaded at runtime.** Model weights are resolved at *image build
time*, verified against pinned SHA-256 digests, and mounted at `/models`. Every
workload runs with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and
`HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS=false`, and no value turns them off.

**Nothing is assumed about the cluster.** Prometheus Operator, Grafana, KEDA,
Cilium, External Secrets and COSI are all detected at template time and skipped
when absent. The chart installs unchanged on NKP Starter, where most of them do
not exist.

## Validating a change

One command runs everything CI runs against the chart - lint, render and
kubeconform every posture with and without the optional CRDs, prove NKP Starter
gets no Pro-tier objects, prove the guard rails reject invalid values, and check
restricted Pod Security Standards compliance plus the bot Job invariants:

```bash
deploy/helm/hansard/hack/validate.sh
```

Needs `helm >= 3.14`, `kubeconform >= 0.6` and `python3` with PyYAML. No cluster.

For the images and the compose stack:

```bash
make -C deploy/docker images-txt      # regenerate the mirror list from the chart
make -C deploy/docker models-verify   # re-check the model bundle checksums
docker compose -f deploy/compose/docker-compose.yml config >/dev/null
```
