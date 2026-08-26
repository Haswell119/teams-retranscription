<div align="center">

# Hansard

**Sovereign meeting transcription for Microsoft Teams.**
Runs entirely on your own infrastructure. Nothing leaves your network.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-1011%20passing-brightgreen.svg)](tests/)
[![Languages](https://img.shields.io/badge/languages-fran%C3%A7ais%20%7C%20english-blue.svg)](docs/benchmarks.md)

</div>

---

Invite Hansard to a Teams meeting. It joins, listens, and afterwards sends you a
transcript and a set of minutes — who decided what, who owes what by when — as a
Teams message, an email, or a file.

The audio is transcribed on your own hardware. The minutes are written by a model
you run yourself. No API key, no vendor, no cloud, no telemetry.

*Hansard is the name given to the official verbatim record of parliamentary
proceedings. That is what this tool is for.*

## Why this exists

Microsoft Teams already transcribes meetings. If that works for you, use it.

This project exists for organisations that cannot send meeting content to a third
party — public administrations, healthcare, defence, legal, R&D — and for everyone
who would simply rather not.

Two facts are worth knowing before you decide.

**Where the processing happens.** Microsoft's own documentation states that
Copilot *flex routing* allows large-language-model inferencing for EU and EFTA
customers "to occur outside the EU Data Boundary during periods of peak demand",
specifically "in the United States, Canada, or Australia" — and that it is **on by
default for eligible tenants created after 25 March 2026**. Because AI meeting
notes are LLM inferencing, meeting content in a new EU tenant can be processed
outside the EU unless an administrator actively opts out.
([Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-365/copilot/copilot-flex-routing))

**How good the transcription actually is.** Azure Speech, the engine behind Teams
transcription, is marketed at **2.4 % word error rate** on curated short clips. On
AMI, the standard meeting corpus, independent benchmarking puts it at **27.4 %
cpWER** — the metric that scores transcription and speaker attribution together —
and at **35.7 %** on NOTSOFAR-1, which is Microsoft's *own* office-meeting corpus.
That is not dishonesty; it is the gap between read speech and a real meeting. It
does mean the marketing number tells you very little about what you will read
after your Tuesday stand-up.

Hansard is built to be measured on the second kind of number. See
[benchmarks](docs/benchmarks.md).

## What you get

| | Hansard | Teams + Copilot |
| --- | --- | --- |
| Where audio is processed | Your infrastructure | Microsoft's |
| Where minutes are generated | Your infrastructure | Microsoft's, possibly outside the EU by default |
| Custom vocabulary (names, jargon, product codes) | **Yes** | Not available |
| Speakers supported | No architectural limit. Nine detected exactly on clean audio; on spontaneous meeting audio the count is over-estimated and a Teams roster fixes it | Attribution degrades past ~3; guests appear as "Speaker 1" |
| Maximum meeting length | Unbounded | 4 hours or 1.5 GB, no automatic restart |
| Languages in one meeting | **Automatic**, no language tag needed; every utterance is labelled with the language it was spoken in, and decisions, actions and deadlines are extracted with that language's rules on both sides of a switch — see [multilingual](docs/multilingual.md) | One language per meeting; multilingual mode needs Teams Premium and discards the transcript afterwards |
| Verbatim transcript | Yes | Obscenities are always masked |
| Evidence for every claim in the minutes | **Timestamp, speaker and quote** | No per-claim citations |
| Decisions register | Structured, separate from suggestions | Not a documented output |
| Export | Markdown, HTML, JSON, WebVTT, SRT, plain text | `.vtt` via Graph; no export API for the recap |
| Cost per meeting-hour | Your electricity | Teams Premium $10/user/mo or Copilot $30/user/mo |
| Telemetry | None | — |

## Measured quality

On **4 vCPU with no GPU** — deliberately modest hardware, with the shipped
default: Parakeet TDT 0.6B v3 in **float32**.

**Speech recognition — French and English, one model, no language tag.** French
is measured on every release, not assumed to follow from English:

| Corpus | Language | WER | CER | RTF |
| --- | --- | ---: | ---: | ---: |
| FLEURS `fr_fr` | **French** | **4.63 %** | 1.62 % | 0.31 |
| FLEURS `en_us` | English | **4.47 %** | 1.99 % | 0.49 |
| LibriSpeech dev-clean | English | **3.34 %** | 1.19 % | 0.57 |

**Meetings**, scored with cpWER, which penalises both transcription errors and
speaker confusion:

| Meeting | Language | Speakers detected | cpWER | WDER | DER | RTF |
| --- | --- | :---: | ---: | ---: | ---: | ---: |
| 3 speakers | English | 3 / 3 ✓ | **2.52 %** | 0.00 % | 8.64 % | 0.78 |
| 6 speakers | English | 6 / 6 ✓ | **5.56 %** | 1.91 % | 9.40 % | 0.81 |
| 9 speakers | English | 9 / 9 ✓ | **6.51 %** | 1.52 % | 9.94 % | 0.61 |
| 3 speakers | **French** | 3 / 3 ✓ | **4.20 %** | 0.00 % | 11.88 % | 0.30 |
| 6 speakers | **French** | 6 / 6 ✓ | **6.48 %** | 0.69 % | 8.87 % | 0.29 |
| 9 speakers | **French** | 9 / 9 ✓ | **13.36 %** | 3.42 % | 13.98 % | 0.29 |

The speaker count is detected exactly, in both languages, without being told in
advance.

RTF is the real-time factor — processing seconds per second of audio, lower is
better. A 60-minute recording is transcribed and diarized in about 44 minutes on
that 4-core machine, peaking at 3.6 GB of RAM. Minutes generation is extra and
depends on the model you point it at.

INT8 weights ship alongside as an opt-in low-memory profile
(`HANSARD_ASR__QUANTIZATION=int8`, roughly 1.4 GB resident instead of 2.8 GB).
They are **not** the default and not faster: INT8 costs about **2.0 WER points in
French** for the memory it saves. The comparison is a table in
[benchmarks](docs/benchmarks.md#5-choosing-a-quantization-profile).

**French is a first-class case, and here is exactly how far that goes.** One
model covers both languages with no language tag, French read speech is measured
and passes every quality gate it has, and French meeting fixtures are now built
by the same generator as the English ones and scored in the same run — but no
French *meeting* result has been recorded yet, so the meeting table above is
English. We would rather leave that cell empty than fill it with an English
number.

**Real meetings, not just fixtures.** Those fixtures are clean recordings mixed
together, which is much easier than a real room, so we also measure on two
corpora of genuine spontaneous meetings — AMI in English, SUMM-RE in French:

| Corpus | Speakers | cpWER | WER |
| --- | :---: | ---: | ---: |
| AMI, 3 meetings, told nothing | 4 → 5, 4, 5 | 28.75 % | 20.44 % |
| AMI, 3 meetings, with a participant list | 4 → **4, 4, 4** | **27.34 %** | 20.44 % |
| SUMM-RE, real French meeting | 4 → **4** | 53.16 % | 37.52 % |

Azure Speech, the engine behind Teams transcription, is independently measured
at **27.39 %** cpWER on AMI. We are level with it there — from 49.39 % earlier in
this project's life, closed by fixing our own defects rather than by changing how
we score. Read [benchmarks](docs/benchmarks.md) before quoting that: three
meetings is a small sample, the Azure figure comes from a third party using its
own reference preparation, and **on French meetings we are clearly behind** —
though nobody publishes a French meeting number to be behind. Where we lose, and
why, is written down.

## Quick start

Transcribe a recording — no Teams, no cluster, five minutes:

```bash
pip install "hansard[api,asr-onnx,diarization,metrics]"
hansard doctor                        # check ffmpeg, models, runtimes
hansard transcribe meeting.m4a --language fr --format markdown,vtt
```

With your own vocabulary, which is where the difference shows:

```bash
cat > glossary.txt <<'EOF'
Aurélie Fontaine
Jean-Luc Mercier
Kubernetes
SecNumCloud
EOF

hansard transcribe meeting.m4a --vocabulary glossary.txt
```

Invite the bot to a live meeting:

```bash
hansard join "https://teams.microsoft.com/l/meetup-join/..." \
  --deliver email:equipe@example.org \
  --deliver teams-chat:19:xxxx@thread.v2
```

Deploy on Kubernetes:

```bash
helm install hansard deploy/helm/hansard \
  --set global.imageRegistry=registry.internal \
  --set asr.compute=cpu
```

Full instructions: [installation](docs/installation.md) ·
[configuration](docs/configuration.md) · [deployment](docs/deployment.md) ·
[NKP](docs/deployment-nkp.md)

## How it works

```
Teams meeting
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Capture      headless Chromium joins as a participant,         │
│               announces itself, records the mixed audio,        │
│               and reads the participant roster and the          │
│               active-speaker signal from the Teams client       │
└─────────────────────────────────────────────────────────────────┘
     │  16 kHz mono audio  +  who-spoke-when metadata
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Prepare      high-pass filter, EBU R128 loudness for           │
│               recognition, dynamics preserved for diarization,  │
│               Silero voice-activity detection                   │
├─────────────────────────────────────────────────────────────────┤
│  Recognise    Parakeet TDT 0.6B v3, float32 ONNX, 25 languages, │
│               word-level timestamps, punctuation, no PyTorch    │
├─────────────────────────────────────────────────────────────────┤
│  Diarize      pyannote segmentation + TitaNet embeddings,       │
│               unbounded speakers, 46 MB of models               │
├─────────────────────────────────────────────────────────────────┤
│  Attribute    word-level fusion with boundary dilation and      │
│               Viterbi smoothing; clusters matched to real       │
│               names against the Teams roster                    │
├─────────────────────────────────────────────────────────────────┤
│  Correct      participant names and jargon recovered by         │
│               phonetic matching against your glossary           │
├─────────────────────────────────────────────────────────────────┤
│  Summarise    your local LLM, map-reduce over topics, every     │
│               claim verified against the transcript before it   │
│               is allowed into the minutes                       │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
Teams message  ·  email  ·  webhook  ·  files
```

Every stage is an interchangeable adapter behind a protocol. Swap the recognizer,
the diarizer or the summariser without touching anything else — see
[architecture](docs/architecture.md).

Minutes generation is optional and degrades gracefully: with no LLM available,
Hansard still produces decisions, action items with owners and deadlines, open
questions and per-topic summaries using deterministic extraction. It never
returns an empty recap.

Here is that no-LLM path on a French meeting
([full example](docs/examples/worked-example-minutes-fr.md)):

| Owner | Action | Due |
| --- | --- | --- |
| Sofia Ben Ali | Communiqué de presse, relecture vendredi prochain | 2026-06-12 |
| Marc Lefèvre | Périmètre détaillé demain matin | 2026-06-04 |
| Sofia Ben Ali | Visuels de l'agence pour la réunion | 2026-06-04 |

Relative deadlines resolve against the meeting date, not the day the transcript
happened to be processed. Two decisions, two open questions and a per-topic
breakdown come out of the same pass, and every item carries the timecode and the
speaker it came from.

## Models

Everything ships under a licence that permits commercial use. Nothing is gated.

| Purpose | Model | Size | Licence |
| --- | --- | ---: | --- |
| Speech recognition, **default** | NVIDIA Parakeet TDT 0.6B v3 (float32 ONNX) | 2.5 GB | CC-BY-4.0 |
| Speech recognition, low-memory option | NVIDIA Parakeet TDT 0.6B v3 (INT8 ONNX) | 640 MB | CC-BY-4.0 |
| Speaker segmentation | pyannote segmentation 3.0 (INT8 ONNX) | 7 MB | MIT |
| Speaker embeddings | NVIDIA TitaNet Small | 39 MB | CC-BY-4.0 |
| Voice activity | Silero VAD | 2 MB | MIT |
| Minutes | any local model you choose | — | yours |

**3.2 GB in total** — both recognition profiles ship in the same bundle, so
switching to `HANSARD_ASR__QUANTIZATION=int8` needs no second download and no
network access. They are baked into a signed OCI artifact, verified by SHA-256,
and never downloaded at run time. Air-gapped clusters are a supported
configuration.

## Documentation

| | |
| --- | --- |
| [Installation](docs/installation.md) | Getting it running |
| [Configuration](docs/configuration.md) | Every setting |
| [Teams setup](docs/teams-setup.md) | What your Teams administrator has to approve |
| [Deployment](docs/deployment.md) | Docker Compose and Kubernetes |
| [Deployment on NKP](docs/deployment-nkp.md) | Nutanix Kubernetes Platform, including air-gapped |
| [Output formats](docs/output-formats.md) | Markdown, HTML, JSON, WebVTT, SRT |
| [Delivery](docs/delivery.md) | Teams, email, webhook |
| [Minutes](docs/minutes.md) | Running a local LLM, and what the minutes contain |
| [Multilingual meetings](docs/multilingual.md) | French and English in the same meeting |
| [Metrics](docs/metrics.md) | Every formula we use to score ourselves |
| [Benchmarks](docs/benchmarks.md) | The numbers, and how to reproduce them |
| [Sovereignty](docs/sovereignty.md) | Where your data goes, with citations |
| [Architecture](docs/architecture.md) | How the pieces fit |
| [Troubleshooting](docs/troubleshooting.md) | When it does not work |

## Recording responsibly

Hansard joins meetings under a name you choose and posts a notice into the
meeting chat when it arrives. That behaviour is on by default and we recommend
leaving it on.

Presence in a meeting is not consent to be recorded. Around eleven US states
require all-party consent, Germany treats non-consensual call recording as a
criminal offence, and under the GDPR a recording is personal data from the first
word. Your Teams administrator must also explicitly authorise the bot — see
[Teams setup](docs/teams-setup.md).

## Contributing

Issues and pull requests are welcome. Three conventions, in case they surprise
you:

- **The code contains no comments.** Names, types and small functions carry the
  meaning; every explanation lives in `docs/`. If a piece of code needs a comment
  to be understood, that is a signal to rewrite the code.
- **Quality claims need evidence.** A change that touches recognition,
  diarization or attribution should come with a benchmark run. `make bench` takes
  a few minutes.
- **No new network calls in the inference path.** CI runs transcription with the
  network disabled and fails if anything reaches out.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for model attributions.

## Credits

Built on the work of NVIDIA NeMo (Parakeet, TitaNet), pyannote, Silero,
k2-fsa/sherpa-onnx, ONNX Runtime and Playwright. The engineering decisions here
lean on published benchmarks from AssemblyAI, the CHiME challenge series, the
Hugging Face Open ASR Leaderboard, and Linagora's French speech work.
