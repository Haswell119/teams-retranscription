<div align="center">

# Hansard

**Sovereign meeting transcription for Microsoft Teams.**
Runs entirely on your own infrastructure. Nothing leaves your network.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-1220%20passing-brightgreen.svg)](tests/)
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

Microsoft's own documentation states that Copilot *flex routing* allows
large-language-model inferencing for EU and EFTA customers "to occur outside the
EU Data Boundary during periods of peak demand", and that it is **on by default
for eligible tenants created after 25 March 2026**. Because AI meeting notes are
LLM inferencing, meeting content in a new EU tenant can be processed outside the
EU unless an administrator actively opts out.
([Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-365/copilot/copilot-flex-routing))

| | Hansard | Teams + Copilot |
| --- | --- | --- |
| Where audio and minutes are processed | Your infrastructure | Microsoft's, possibly outside the EU by default |
| Custom vocabulary (names, jargon, product codes) | **Yes** | Not available |
| Languages in one meeting | **Automatic**, every utterance labelled with the language it was spoken in — see [multilingual](docs/multilingual.md) | One language; multilingual mode needs Teams Premium and discards the transcript |
| Maximum meeting length | Unbounded | 4 hours or 1.5 GB, no automatic restart |
| Verbatim transcript | Yes | Obscenities are always masked |
| Evidence for every claim in the minutes | **Timestamp, speaker and quote** | No per-claim citations |
| Export | Markdown, HTML, JSON, WebVTT, SRT, plain text | `.vtt` via Graph; no export API for the recap |
| Cost per meeting-hour | Your electricity | Teams Premium $10/user/mo or Copilot $30/user/mo |
| Telemetry | None | — |

## Measured quality

On **4 vCPU with no GPU**, with the shipped default: Parakeet TDT 0.6B v3 in
float32. One model, both languages, no language tag. Every number here is
produced by the code in this repository — [benchmarks](docs/benchmarks.md) has
the tables, the commands and the caveats.

**Read speech** — WER: FLEURS `fr_fr` **4.63 %**, FLEURS `en_us` **4.47 %**,
LibriSpeech dev-clean **3.34 %**. These say the engine is healthy. They say
almost nothing about a real meeting, which is why the next two blocks exist.

**Synthetic meetings**, scored with cpWER, which penalises transcription errors
and speaker confusion together. The speaker count is detected exactly, in both
languages, without being told in advance:

| Speakers | English cpWER | French cpWER |
| :---: | ---: | ---: |
| 3 | **2.52 %** | **4.20 %** |
| 6 | **5.56 %** | **6.48 %** |
| 9 | **6.51 %** | **13.36 %** |

**French and English in the same meeting**, which is the case Teams handles by
making you pick one language. Three code-switched fixtures, no language tag
given: macro **19.21 %** cpWER, **10.33 %** WER, **3.90 %** WDER, and **96.33 %**
of words labelled with the language they were actually spoken in. That last
number is under our own 98 % gate, and the errors run one way — 105 French words
called English against 41 the other way — because the language is currently
decided from our own recognized text rather than from the audio. See
[benchmarks §2.3](docs/benchmarks.md#23-code-switched-meetings-french-and-english-in-one-room).

**Real meetings.** Those fixtures are clean recordings mixed together, which is
far easier than a real room, so we also measure on corpora of genuine
spontaneous speech — and these are the numbers to judge us on:

| Corpus | Speakers | cpWER | WER |
| --- | :---: | ---: | ---: |
| AMI, 3 English meetings, told nothing | 4 → 5, 4, 5 | 28.75 % | 20.44 % |
| AMI, 3 English meetings, with a participant list | 4 → **4, 4, 4** | **27.34 %** | 20.44 % |
| SUMM-RE, 1 real French meeting | 4 → **4** | 53.16 % | 37.52 % |

Azure Speech, the engine behind Teams transcription, is independently measured at
**27.39 %** cpWER on AMI. On English meetings we are level with it, down from
49.39 % earlier in this project's life — closed by fixing our own defects, not by
changing how we score. **On French meetings we are clearly behind**, and that is
the largest open problem in the project; nobody else publishes a French meeting
number to be behind, which cuts both ways. Three meetings is a small sample and
the Azure figure comes from a third party using its own reference preparation.
Where we lose, and why, is written down in
[benchmarks §8](docs/benchmarks.md#8-where-we-lose).

**We now know where the French words go, and it is not French.** Handing the
recognizer the corpus's own utterance boundaries across seven SUMM-RE meetings
leaves 30.82 % word error, so segmentation is worth about seven points and not
the twenty-five that were missing. Splitting those same results by how much of
each utterance somebody *else* is talking over gives the real answer:

| Overlap with another speaker | Reference words | WER |
| --- | ---: | ---: |
| clean, under 5 % | 3758 | **20.60 %** |
| light, 5–50 % | 2154 | 23.35 % |
| heavy, over 50 % | 1232 | **70.54 %** |

Heavily overlapped speech is 17 % of the words and 39 % of the errors. On clean
French spontaneous speech the shipped model scores 20.6 %, close to what it
scores on English AMI. It is not bad at French; it is bad at two people at once,
and on the single mixed stream Teams hands us it has no way to be anything else.
Replacing it with a bigger model does not help — NVIDIA Canary 1B v2, which
outranks it on French read speech, scored 38.01 % on identical audio and lost in
every band. The experiment log is
[quality-research](docs/quality-research.md).

**Speed and memory.** A 60-minute recording is transcribed and diarized in about
44 minutes on that 4-core machine, peaking at 3.6 GB of RAM on the English
fixtures and 4.1 GB on the French ones. INT8 weights ship alongside as an opt-in
low-memory profile (`HANSARD_ASR__QUANTIZATION=int8`, ~1.4 GB resident instead of
~2.8 GB). They are **not** the default and not faster: INT8 costs about **2.0 WER
points in French**, and deletes words wholesale on real meeting audio.

**Not yet measured:** NOTSOFAR-1, any speech-separation front-end, and a
head-to-head against a live Teams transcript.
[Benchmarks §9](docs/benchmarks.md#9-what-we-have-not-measured-yet) keeps that
list honest.

## Quick start

Transcribe a recording — no Teams, no cluster, five minutes:

```bash
pip install "hansard[api,asr-onnx,diarization,metrics]"
hansard doctor                        # check ffmpeg, models, runtimes
hansard transcribe meeting.m4a --language fr --format markdown,vtt
```

With your own vocabulary, which is where the difference shows:

```bash
printf 'Aurélie Fontaine\nJean-Luc Mercier\nSecNumCloud\n' > glossary.txt
hansard transcribe meeting.m4a --vocabulary glossary.txt
```

Invite the bot to a live meeting, or deploy the service:

```bash
hansard join "https://teams.microsoft.com/l/meetup-join/..." \
  --deliver email:equipe@example.org \
  --deliver teams-chat:19:xxxx@thread.v2

helm install hansard deploy/helm/hansard \
  --set global.imageRegistry=registry.internal --set asr.compute=cpu
```

Full instructions: [installation](docs/installation.md) ·
[configuration](docs/configuration.md) · [deployment](docs/deployment.md) ·
[NKP](docs/deployment-nkp.md)

## How it works

A Teams meeting goes in; a transcript, minutes and a delivery come out. Each
stage is an interchangeable adapter behind a protocol — swap the recognizer, the
diarizer or the summariser without touching anything else.

| Stage | What it does |
| --- | --- |
| **Capture** | Headless Chromium joins as a participant, announces itself, records the mixed audio, and reads the roster and active-speaker signal from the Teams client |
| **Prepare** | High-pass filter, EBU R128 loudness, Silero voice-activity detection |
| **Recognise** | Parakeet TDT 0.6B v3, float32 ONNX, word timestamps, punctuation, no PyTorch |
| **Identify** | Probes catch the recogniser settling on the wrong language and force a re-decode; every utterance is labelled with the language it was spoken in |
| **Diarize** | pyannote segmentation + TitaNet embeddings, unbounded speakers, 42 MB of models |
| **Attribute** | Word-level fusion, clusters matched to real names against the Teams roster, jargon recovered phonetically from your glossary |
| **Summarise** | Your local LLM, map-reduce over topics, every claim verified against the transcript before it reaches the minutes |

See [architecture](docs/architecture.md) for how the pieces fit.

Minutes generation degrades gracefully: with no LLM available, deterministic
extraction still produces decisions, action items with owners and deadlines, open
questions and per-topic summaries, resolving relative deadlines against the
meeting date rather than the processing date. It never returns an empty recap —
[worked example in French](docs/examples/worked-example-minutes-fr.md).

## Models

Everything ships under a licence that permits commercial use. Nothing is gated.

| Purpose | Model | Size | Licence |
| --- | --- | ---: | --- |
| Speech recognition, **default** | NVIDIA Parakeet TDT 0.6B v3 (float32 ONNX) | 2.5 GB | CC-BY-4.0 |
| Speech recognition, low-memory option | NVIDIA Parakeet TDT 0.6B v3 (INT8 ONNX) | 670 MB | CC-BY-4.0 |
| Speaker segmentation | pyannote segmentation 3.0 (INT8 ONNX) | 1.5 MB | MIT |
| Speaker embeddings | NVIDIA TitaNet Small | 40 MB | CC-BY-4.0 |
| Voice activity | Silero VAD | 2 MB | MIT |
| Minutes | any local model you choose | — | yours |

**3.2 GB in total** — both recognition profiles ship in the same bundle, so
switching to INT8 needs no second download and no network access. They are baked
into a signed OCI artifact, verified by SHA-256, and never downloaded at run
time. Air-gapped clusters are a supported configuration.

## Documentation

| | |
| --- | --- |
| [Installation](docs/installation.md) · [Configuration](docs/configuration.md) | Getting it running, and every setting |
| [Teams setup](docs/teams-setup.md) | What your Teams administrator has to approve |
| [Deployment](docs/deployment.md) · [NKP](docs/deployment-nkp.md) | Docker Compose, Kubernetes, air-gapped |
| [Output formats](docs/output-formats.md) · [Delivery](docs/delivery.md) | Markdown, HTML, JSON, WebVTT, SRT; Teams, email, webhook |
| [Minutes](docs/minutes.md) · [Multilingual](docs/multilingual.md) | Running a local LLM; French and English in one meeting |
| [Benchmarks](docs/benchmarks.md) · [Metrics](docs/metrics.md) | The numbers, how to reproduce them, and every formula |
| [Architecture](docs/architecture.md) · [Sovereignty](docs/sovereignty.md) | How the pieces fit; where your data goes, with citations |
| [Troubleshooting](docs/troubleshooting.md) | When it does not work |

## Recording responsibly

Hansard joins under a name you choose and posts a notice into the meeting chat on
arrival. That is on by default and we recommend leaving it on.

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
- **Quality claims need evidence.** A change touching recognition, diarization or
  attribution comes with a benchmark run. `make bench` takes a few minutes.
- **No new network calls in the inference path.** CI runs transcription with the
  network disabled and fails if anything reaches out.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for model attributions.
Built on NVIDIA NeMo (Parakeet, TitaNet), pyannote, Silero, k2-fsa/sherpa-onnx,
ONNX Runtime and Playwright.
