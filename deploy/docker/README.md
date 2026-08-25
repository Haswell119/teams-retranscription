# Hansard container images

Five images, one build context (the repository root), one Makefile.

| Image | Dockerfile | What it is | Needed when |
|---|---|---|---|
| `hansard-api` | `Dockerfile.api` | orchestrator + HTTP API + CLI | always |
| `hansard-worker` | `Dockerfile.worker` | CPU ASR/diarization, ONNX Runtime, no PyTorch | always |
| `hansard-worker-gpu` | `Dockerfile.worker-gpu` | CUDA variant, ONNX Runtime CUDA EP | `asr.compute=gpu\|both` |
| `hansard-models-init` / `hansard-models` | `Dockerfile.models` | the model bundle | always (one of the two) |
| `hansard-bot` | `src/hansard/adapters/capture/docker/` | browser capture bot | `capture.engine=browser` |

The bot image is **owned by the capture adapter**, not by this directory. The
Makefile has a `bot` target that builds it where it lives; it does not define it.

```
make -C deploy/docker help
make -C deploy/docker images                 # api + worker
make -C deploy/docker models                 # download weights ONCE, build all model outputs
make -C deploy/docker all-images             # everything, including GPU and bot
```

## What is deliberately NOT in these images

* **No model weights.** Every app image ships with
  `HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS=false`, `HF_HUB_OFFLINE=1` and
  `TRANSFORMERS_OFFLINE=1`. Weights arrive through a separate, checksummed
  artifact mounted at `/models`. Baking them in would make every application
  patch a 700 MB re-pull.
* **No build toolchain.** `build-essential` exists only in the builder stage.
* **No root.** Every image runs as uid/gid `10001`, has no shell entry point
  for that user, and works with `readOnlyRootFilesystem: true`.
* **No telemetry.** Nothing phones anywhere.

## Language: one model, French and English

`Dockerfile.models` bundles **NVIDIA Parakeet TDT 0.6b v3** (int8 ONNX), which
is natively multilingual across 25 European languages, French and English among
them. There is no French image and no English image; there is no language tag
to pass at inference time (`asr.language: auto` is the default and the
recommended setting). A meeting where people switch between French and English
transcribes correctly in one pass, and the CPU worker still sits at roughly
2 GB RSS.

Voice activity detection (Silero) and diarization (pyannote segmentation 3.0 +
CAM++ embeddings) are language independent by construction.

## The model artifact

`Dockerfile.models` downloads every weight **at build time**, verifies each file
against a SHA-256 pinned in `models.manifest`, writes a `SHA256SUMS` covering
the whole bundle, and copies `models.NOTICE` in as `/models/NOTICE`. Nothing is
ever fetched at pod start.

One download feeds three outputs:

```
make -C deploy/docker models-export         # -> dist/models/  (host directory)
make -C deploy/docker models-init-image     # -> hansard-models-init  (busybox copier)
make -C deploy/docker models-scratch-image  # -> hansard-models       (FROM scratch)
make -C deploy/docker models                # all three
```

| Output | Chart value | How it reaches `/models` | Use it when |
|---|---|---|---|
| `hansard-models-init` | `models.source=initImage` *(default)* | init container `cp -R` into an `emptyDir`, then `sha256sum -c` | always works; no feature gates, no extra tooling |
| `hansard-models` (scratch) | `models.source=image` | Kubernetes `image:` volume | you have verified ImageVolume is enabled (**beta and disabled by default in 1.33**, needs containerd >= 2.1). ~11.5 s warm start, independent of model size |
| `dist/models/` -> `oras push` | `models.source=oras` | ORAS init container pulls an OCI artifact | you already publish models as OCI artifacts |
| `dist/models/` -> object storage | `models.source=s3` | `mc mirror` init container | you have a bucket and accept a re-download per pod start |
| pre-populated PVC | `models.source=pvc` | nothing at all | the only zero-network option |

`make models-oras-push` publishes `dist/models` as a plain OCI artifact. Note
that `oras pull` cannot extract a Docker image manifest's layers, which is why
the ORAS path uses the artifact and the ImageVolume path uses the scratch
image; both are produced from the same verified bytes.

### Contents

```
/models/nemo-parakeet-tdt-0.6b-v3/{config.json,vocab.txt,nemo128.onnx,
                                   encoder-model.int8.onnx,
                                   decoder_joint-model.int8.onnx}   ASR, CC-BY-4.0
/models/silero/silero_vad.onnx                                      VAD, MIT
/models/sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx       segmentation, MIT
/models/nemo_en_titanet_small.onnx                                  embeddings, CC-BY-4.0
/models/NOTICE                                                      attribution
/models/SHA256SUMS                                                  integrity
```

Roughly 0.72 GB in total, 11 files. The paths are not decorative: they are
exactly what `hansard.adapters.asr.registry`, `onnx_asr.models.silero` and
`hansard.adapters.diarization.sherpa` resolve. Change one and the runtime
stops finding its models.

### The embedding model was chosen on measurement

Speaker diarization has two models: one segments the audio into speech turns,
the other turns each turn into an embedding that gets clustered. The **embedding
model is where diarization quality actually lives**, and the difference between
candidates is not marginal.

Benchmarked end to end on synthetic multi-speaker meetings with exact ground
truth:

| Embedding model | Speaker confusion | DER |
|---|---|---|
| `nemo_en_titanet_small.onnx` (39 MB, CC-BY-4.0) | **0.01 %** | **14.96 %** |
| `3dspeaker_..._campplus_..._voxceleb_16k.onnx` (29 MB, Apache-2.0) | 47 % | 62.77 % |

CAM++ failed **even when handed the correct number of clusters**, so this is not
a clustering-hyperparameter problem - the embedding space itself does not
separate these speakers. The bundle therefore ships TitaNet, and CAM++ was
removed.

Two consequences worth internalising:

* **Do not swap the embedding model on reputation.** Re-run the benchmark. A
  model that tops a speaker-verification leaderboard can still be useless on
  meeting audio, which is short-turn, overlapped and far-field.
* **You can test a candidate without rebuilding the bundle.** The chart exposes
  `diarization.embeddingModel`, `diarization.clusteringThreshold` and
  `diarization.minimumSpeakerSeconds` as values (env
  `HANSARD_DIARIZATION__EMBEDDING_MODEL`, `..._CLUSTERING_THRESHOLD`,
  `..._MINIMUM_SPEAKER_SECONDS`). Add the candidate to `models.manifest`, ship
  both, and switch with a value. `clusteringThreshold: 0.95` is calibrated for
  TitaNet and is not transferable to a different embedding space.

### Changing models

Edit `models.manifest`, nothing else. Each line is
`target|url|sha256|archive-member`. To get a new SHA-256:

```
curl -fsSL <url> | sha256sum
```

Hugging Face URLs are pinned to a **commit**, not to `main`, so a rebuild in six
months produces identical bytes.

## CUDA and cuDNN pinning (GPU image)

`onnxruntime-gpu` wheels are built against exactly one CUDA major and one cuDNN
major. Getting it wrong does not fail loudly: ONNX Runtime logs
`Failed to create CUDAExecutionProvider` and silently falls back to CPU, so you
pay for a GPU node and get CPU throughput.

| `onnxruntime-gpu` | CUDA | cuDNN |
|---|---|---|
| <= 1.18.x (PyPI default) | 11.8 | 8 |
| 1.19.x - 1.20.x | 12.x | 9 |
| >= 1.21.x | 12.x | 9 |

`Dockerfile.worker-gpu` therefore pins `onnxruntime-gpu>=1.19,<2` against
`nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04`. `pyproject.toml` declares the
looser `onnxruntime-gpu>=1.18`, which would permit a CUDA 11 wheel; the floor is
raised with an explicit constraint in the Dockerfile rather than by editing the
project metadata. The image's `HEALTHCHECK` fails if
`CUDAExecutionProvider` is not registered, so a mismatch shows up as an
unhealthy container instead of a silent slowdown.

Host driver must be >= 525 (CUDA 12 minor-version compatibility floor). Verify
with `nvidia-smi` in a debug pod on the GPU node pool.

## Build-time proxies, mirrors and private CAs

Every Dockerfile takes the same three knobs:

```
docker build \
  --build-arg PIP_INDEX_URL=https://nexus.internal/repository/pypi/simple \
  --build-arg PIP_EXTRA_INDEX_URL= \
  --secret id=ca_bundle,src=/etc/ssl/certs/corporate-ca.crt \
  -f deploy/docker/Dockerfile.api -t hansard-api:0.1.0 .
```

and the model builder additionally takes:

```
  --build-arg HF_ENDPOINT=https://hf-mirror.internal \
  --build-arg GITHUB_MIRROR=https://github-mirror.internal
```

The CA secret is installed into the system trust store and pointed at from
`/etc/pip.conf`; verification is never disabled.

> **Gotcha:** BuildKit does not include secret *contents* in the layer cache
> key. If you first built without `--secret id=ca_bundle` and the layer was
> cached, adding the secret later changes nothing. Force it with
> `--no-cache-filter builder`.

`EXTRA_PIP_PACKAGES` adds packages the project's extras do not declare. It is
empty by default - `sherpa-onnx` now ships in pyproject's `diarization` extra -
and remains available for pinning or patching a dependency without editing
project metadata. Run `docker run --rm <image> doctor` after any build: it
prints whether ffmpeg, `/models`, ONNX Runtime and the diarization runtime are
all present.

## Air-gap procedure

1. **On a connected machine**, build and push everything:

   ```
   make -C deploy/docker all-images REGISTRY=stage.example.com/hansard
   make -C deploy/docker push-all   REGISTRY=stage.example.com/hansard
   make -C deploy/docker digests    REGISTRY=stage.example.com/hansard
   ```

2. **Record the digests** into `deploy/helm/hansard/values.yaml`
   (`images.<name>.digest`) and set `global.requireImageDigests=true`. The
   chart then refuses to install with an unpinned image.

3. **Regenerate the mirror list** so it cannot drift from the chart:

   ```
   make -C deploy/docker images-txt
   ```

4. **Carry the images across.** Either a tarball:

   ```
   make -C deploy/docker save        # dist/hansard-images-0.1.0.tar
   ```

   or, on NKP, the platform's own bundle tooling:

   ```
   nkp push bundle --bundle hansard-images.tar --to-registry harbor.nkp.internal/hansard
   ```

   or `skopeo`, registry to registry:

   ```
   make -C deploy/docker mirror TARGET_REGISTRY=harbor.nkp.internal/hansard
   ```

5. **Carry the model artifact across** the same way. It is an ordinary OCI
   image (`hansard-models-init`), so `nkp push bundle` / `skopeo copy` handle
   it. Verify on the far side:

   ```
   make -C deploy/docker models-verify
   ```

6. **Push the chart** as an OCI artifact into the same registry:

   ```
   helm package deploy/helm/hansard
   helm push hansard-0.1.0.tgz oci://harbor.nkp.internal/hansard/charts
   ```

7. **Install** with `global.imageRegistry=harbor.nkp.internal/hansard` and
   `global.customCA.existingSecret` pointing at the registry's CA. See
   `deploy/helm/hansard/ci/airgap-values.yaml`.

## Signing

```
make -C deploy/docker sign    REGISTRY=...            # keyless in CI, or COSIGN_KEY=cosign.key
make -C deploy/docker verify  REGISTRY=... COSIGN_KEY=cosign.key
make -C deploy/docker sbom                            # CycloneDX per image
```

Air-gapped clusters cannot reach a public Rekor log, so use key-based signing
(`--key`) and verify with the matching `.pub`, or run an internal Rekor. Flux
verifies chart signatures through the `verify:` block in
`deploy/helm/hansard/nkp/ocirepository.yaml`.

## Size budget

| Image | Uncompressed |
|---|---|
| `hansard-api` | ~1.26 GB (budget 1.5 GB) |
| `hansard-worker` | slightly smaller: no `api` or `delivery` extras |
| `hansard-worker-gpu` | several GB; the CUDA runtime base dominates |
| `hansard-models-init` | ~0.72 GB of weights on a 4 MB busybox |

`make -C deploy/docker size` prints the current numbers. The largest single
contributor to the app images is `ffmpeg` plus its codec dependencies, and it is
not optional: the audio enhancement chain shells out to it.
