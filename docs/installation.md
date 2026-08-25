# Installation

There are three ways to run Hansard, in increasing order of effort:

1. **pip on a machine you already have** — enough to transcribe a recording and
   produce minutes. Covered here.
2. **Docker Compose on a laptop** — the same file-based path, containerised.
   Covered here and in [deployment](deployment.md).
3. **Kubernetes**, including the browser bot that joins live meetings — see
   [deployment](deployment.md) and [deployment on NKP](deployment-nkp.md).

Whichever you choose, two things are true. **ffmpeg must be on the PATH**, and
**the models must be on disk before you run anything**: Hansard does not
download weights at run time.

French and English are handled by the same model and the same install. There is
no per-language package, no language pack and no second worker.

---

## 1. System prerequisites

| Requirement | Why | Check |
| --- | --- | --- |
| **Python 3.11 or 3.12** | `requires-python = ">=3.11"` in `pyproject.toml` | `python3 --version` |
| **ffmpeg** | The audio path shells out to it for decoding, for the high-pass and loudness filters, and for the live recorder | `ffmpeg -version` |
| **libsndfile** | `soundfile` reads WAV, FLAC, OGG and Opus directly without ffmpeg | `python -c "import soundfile"` |

ffmpeg is not optional. `hansard.adapters.audio.io` uses it to decode anything
that is not WAV/FLAC/OGG/Opus, `hansard.adapters.enhancement.ffmpeg_chain` uses
it for `highpass` and `loudnorm`, and the meeting recorder uses it to capture the
PulseAudio monitor source. Without it you get
`HansardError: ffmpeg is required to read .m4a audio` or
`ffmpeg is required by FfmpegEnhancer`.

```bash
# Debian / Ubuntu
sudo apt-get install -y ffmpeg libsndfile1

# Fedora / RHEL
sudo dnf install -y ffmpeg libsndfile

# macOS
brew install ffmpeg libsndfile
```

### Additional prerequisites for the browser bot

The bot joins a Teams meeting as a participant using a real Chromium under a
virtual display, and captures the meeting audio through a PulseAudio null sink.
That needs more than a Python package:

| Requirement | Package on Debian/Ubuntu |
| --- | --- |
| Chromium, installed through Playwright | `python -m playwright install --with-deps chromium` |
| Virtual X display | `xvfb`, `x11-utils`, `xauth`, `dbus-x11` |
| A window manager Chromium will render into | `fluxbox` |
| PulseAudio and `pactl` | `pulseaudio`, `pulseaudio-utils` |
| Process reaping in a container | `tini`, `procps` |

The reference list is `src/hansard/adapters/capture/docker/Dockerfile`, and the
start-up sequence (Xvfb, then fluxbox, then PulseAudio, then the null sink, then
the worker) is `src/hansard/adapters/capture/docker/entrypoint.sh`. Running the
bot outside a container is possible but unsupported; the container is the tested
configuration.

---

## 2. Install with pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "hansard[asr-onnx,diarization]"
```

### Which extras do you need

Every extra is declared in `pyproject.toml`. Pick by what you intend to do.

| I want to … | Extras | What they pull in |
| --- | --- | --- |
| Transcribe a file, with speakers | `asr-onnx,diarization` | `onnx-asr`, `onnxruntime`, `sherpa-onnx` |
| The same on an NVIDIA GPU | `asr-onnx-gpu,diarization` | `onnxruntime-gpu` instead of `onnxruntime` |
| Transcribe without speaker separation | `asr-onnx` | recognition only; set `HANSARD_DIARIZATION__ENGINE=null` |
| Minutes from a local LLM | *none* | the OpenAI-compatible client uses `httpx`, which is a core dependency |
| Email delivery | `delivery` | `aiosmtplib` |
| Webhook or Teams Workflows delivery | *none* | `httpx` again |
| Teams delivery through Microsoft Graph | `delivery-msal` (optional) | `msal`. Without it the client-credentials flow runs over `httpx` instead |
| The browser bot | `capture` | `playwright`, plus the system packages above |
| Prometheus metrics | `observability` | `prometheus-client` |
| Run the benchmarks | `metrics` | `jiwer`, `scipy`, `meeteval`, `whisper-normalizer`, `unidecode` |
| Contribute | `dev` | `ruff`, `mypy`, `pytest` and friends |

A full working install for a single machine:

```bash
pip install "hansard[asr-onnx,diarization,delivery,metrics,observability]"
```

`make install` does the same thing with `uv`, and `make install-dev` adds `dev`,
`capture` and the Chromium download.

### Two extras that do not yet do what their name suggests

- **`api`** installs FastAPI and Uvicorn, but there is no HTTP interface in the
  tree yet: `src/hansard/interfaces/` contains only `cli.py`. The whole `api`
  settings section is currently inert. See
  [configuration](configuration.md#not-yet-wired-up).
- **`asr-whisper`** installs `faster-whisper`, but the module the ASR registry
  imports for the `whisper` engine, `hansard.adapters.asr.whisper_engine`, is
  not present. `HANSARD_ASR__ENGINE=whisper` therefore fails with an
  `ImportError`. Parakeet is the supported recogniser.

---

## 3. Getting the models

Hansard never fetches weights during a run.
`HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS` defaults to `false`, and the container
images set `HF_HUB_OFFLINE=1`. Staging the models is a deliberate, separate,
verifiable step — which is what makes an air-gapped install possible at all. See
[sovereignty](sovereignty.md).

Provenance lives in exactly one file, `deploy/docker/models.manifest`: one line
per file, giving the target path, a URL pinned to a commit, and a SHA-256 that
is verified after download. `deploy/docker/fetch-models.sh` reads it.

### Fetching them

```bash
deploy/docker/fetch-models.sh \
  deploy/docker/models.manifest \
  deploy/docker/models.NOTICE \
  ./models
```

The script downloads each URL once, verifies its digest, extracts the two
diarization files from the sherpa-onnx release archive, copies the licence
notice in, and finally writes a `SHA256SUMS` covering the whole directory. A
digest mismatch aborts the build rather than continuing with unknown weights.

Behind a mirror, set the two rewrite variables before running it:

```bash
HF_ENDPOINT=https://huggingface.internal \
GITHUB_MIRROR=https://github.internal \
deploy/docker/fetch-models.sh deploy/docker/models.manifest deploy/docker/models.NOTICE ./models
```

> The repository also has a `make models` target. As written it passes
> `MODELS_DIR` as an environment variable, while `fetch-models.sh` takes its
> manifest, notice and output directory as three positional arguments, so the
> target currently exits with
> `usage: fetch-models.sh <manifest> <notice> <output-dir>`. Use the explicit
> invocation above until that is fixed.

### The expected layout

Every path below is what the adapters resolve, relative to
`HANSARD_RUNTIME__MODELS_DIR`. They are not arbitrary: the ASR loader looks for
`models_dir / model_id` with any `/` in the id replaced by `__`, the VAD loader
for `models_dir / vad.model_subdirectory`, and the diarizer for the two
filenames named in `HANSARD_DIARIZATION__SEGMENTATION_MODEL` and
`HANSARD_DIARIZATION__EMBEDDING_MODEL`.

```
models/
├── nemo-parakeet-tdt-0.6b-v3/
│   ├── config.json
│   ├── vocab.txt
│   ├── nemo128.onnx
│   ├── encoder-model.int8.onnx
│   └── decoder_joint-model.int8.onnx
├── silero/
│   ├── silero_vad.onnx
│   └── LICENSE
├── sherpa-onnx-pyannote-segmentation-3-0/
│   ├── model.int8.onnx
│   └── LICENSE
├── nemo_en_titanet_small.onnx
├── NOTICE
└── SHA256SUMS
```

| Directory or file | Purpose | Licence |
| --- | --- | --- |
| `nemo-parakeet-tdt-0.6b-v3/` | Speech recognition, French and English and 23 other European languages from one model | CC-BY-4.0 |
| `silero/silero_vad.onnx` | Voice activity detection, language independent | MIT |
| `sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx` | Speaker segmentation | MIT |
| `nemo_en_titanet_small.onnx` | Speaker embeddings for clustering | CC-BY-4.0 |

Only the INT8 encoder and decoder are in the manifest. If you set
`HANSARD_ASR__QUANTIZATION=none` you must supply the float32 weights yourself;
the shipped bundle will not satisfy that setting.

### Pointing Hansard at them

```bash
export HANSARD_RUNTIME__MODELS_DIR="$PWD/models"
```

The default is `/var/lib/hansard/models`. The published container images
override it to `/models`, which is where the model volume is mounted.

Re-verify the bundle at any time:

```bash
cd models && sha256sum -c SHA256SUMS
```

---

## 4. Docker Compose

`deploy/compose/docker-compose.yml` builds the images locally, downloads the
model bundle into a named volume once, and gives you a one-shot `cli` service
that shares those models and volumes.

```bash
cd deploy/compose
cp .env.example .env
docker compose --profile build build
docker compose run --rm models          # downloads and verifies the bundle, once
docker compose run --rm cli doctor
cp ~/meeting.m4a ./inbox/
docker compose run --rm cli transcribe /inbox/meeting.m4a --output /artifacts
```

Artefacts land in `deploy/compose/artifacts/` on the host. The compose stack runs
every service read-only, non-root, with all capabilities dropped.

Two caveats worth stating plainly. There is **no browser bot in compose** — a
Teams bot needs its own `/dev/shm` budget and egress policy, which compose cannot
model honestly. And the `api` and `worker` services invoke `hansard serve` and
`hansard worker`, subcommands that do not exist in the CLI yet; the `models` and
`cli` services are the parts that work today. The full walkthrough, including
what to do about that, is in [deployment](deployment.md).

For Kubernetes, air-gapped installation, GPU node pools and network policy, go
to [deployment](deployment.md) and [deployment on NKP](deployment-nkp.md).

---

## 5. Verifying the installation

```bash
hansard doctor
```

```
                         Hansard environment
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check               ┃ Status   ┃ Detail                            ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ffmpeg              │ ok       │ /usr/bin/ffmpeg                   │
│ models directory    │ ok       │ /home/you/models                  │
│ ONNX runtime        │ ok       │ onnxruntime                       │
│ diarization runtime │ ok       │ sherpa_onnx                       │
│ telemetry           │ disabled │ Hansard never sends data anywhere │
└─────────────────────┴──────────┴───────────────────────────────────┘
```

| Row | What it checks | If it is `missing` |
| --- | --- | --- |
| **ffmpeg** | `shutil.which("ffmpeg")` | Install ffmpeg, or fix the PATH of the user the process runs as |
| **models directory** | Whether `HANSARD_RUNTIME__MODELS_DIR` is a directory. It does **not** look inside | Set the variable, or fetch the bundle. A directory that exists but is empty still reports `ok` and fails later at load time |
| **ONNX runtime** | `import onnxruntime` | `pip install "hansard[asr-onnx]"` |
| **diarization runtime** | `import sherpa_onnx` | `pip install "hansard[diarization]"` |
| **telemetry** | Always `disabled` | Not a check. It records that there is no analytics code to switch on, and that `HANSARD_RUNTIME__TELEMETRY_ENABLED=true` is rejected by a validator |

`doctor` reads the same settings as everything else, so run it with the same
environment as your real workload.

---

## 6. First transcription

```bash
hansard transcribe meeting.m4a --language fr --format markdown,vtt
```

The full command set today is `version`, `doctor` and `transcribe`. `transcribe`
takes:

| Option | Default | Meaning |
| --- | --- | --- |
| `--output`, `-o` | `artifacts/<stem>/` | Directory for the artefacts |
| `--language`, `-l` | unset | `fr`, `en`, … Omit it and Parakeet detects the language itself, including a meeting that switches mid-sentence |
| `--format`, `-f` | `markdown,json,vtt` | Comma-separated. Available: `markdown`, `html`, `json`, `vtt`, `srt`, `text` |
| `--vocabulary` | unset | A file with one phrase per line, applied by phonetic correction after recognition |
| `--speakers` | unset | Documented as the known participant count. See the note below |
| `--title` | `Meeting` | Meeting title in the rendered output |

It writes one file per format plus a `metrics.json` holding the audio duration,
the real-time factor, the number of speakers detected, the word count and the
per-stage timings.

`--speakers` currently only lowers `diarization.max_speakers`, and the
sherpa-onnx diarizer does not read that field, so the option has no effect on
the result today. Speaker count is inferred from the audio. The knob that does
change the outcome is `HANSARD_DIARIZATION__CLUSTERING_THRESHOLD` — see
[configuration](configuration.md#diarization).

The `join` command shown in some places does not exist yet either; joining a
live meeting goes through the containerised bot described in
[deployment](deployment.md) and [Teams setup](teams-setup.md).

Output formats are documented in [output formats](output-formats.md); minutes
and the local LLM in [minutes](minutes.md); sending the result somewhere in
[delivery](delivery.md).

---

## 7. When it does not work

Start with [troubleshooting](troubleshooting.md), which is organised by symptom.
The most common first-run failures are a missing ffmpeg, a `models directory`
row that says `missing`, and a `diarization model missing:` error caused by
`HANSARD_RUNTIME__MODELS_DIR` pointing one level above or below the real bundle.
