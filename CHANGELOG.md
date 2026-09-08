# Changelog

Notable changes to Hansard. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Quality figures cite the run that produced them. Anything not measured is said
to be not measured — see [docs/benchmarks.md](docs/benchmarks.md) and
[docs/quality-research.md](docs/quality-research.md).

## [0.1.0] - 2026-09-08

First tagged release. Hansard joins a Microsoft Teams meeting as a notetaker,
transcribes it with speaker attribution, writes minutes and delivers them,
without any part of the meeting leaving the infrastructure it runs on.

### Added

- **Meeting capture.** A headless Chromium bot joins by meeting URL, announces
  itself, records the mixed stream through a dedicated PulseAudio sink and reads
  the participant roster live from the meeting. Survives a recorder that dies
  mid-meeting, a browser that will not launch, and a Teams page that stops being
  a meeting.
- **Transcription.** NVIDIA Parakeet TDT 0.6b v3 through ONNX Runtime — one
  multilingual model for French and English, no language flag, no per-language
  worker pool. Silero voice activity detection, adaptive segmentation, language
  identification with a drift guard.
- **Speaker attribution.** pyannote segmentation 3.0 and NVIDIA TitaNet through
  sherpa-onnx, with centroid consolidation, coverage refinement and roster-based
  naming when the meeting supplies participant names.
- **Minutes** through a local LLM endpoint, with an extractive fallback that
  needs no model at all. Every generated claim carries an evidence timecode.
- **Delivery** to filesystem, SMTP, Microsoft Graph and webhooks; export as
  Markdown, HTML, DOCX, JSON, SRT, VTT and RTTM.
- **Deployment.** Docker Compose for a laptop, Helm chart validated against five
  postures — default, air-gap, NKP starter, restricted and GPU — with Prometheus
  rules, Grafana dashboards and a documented Nutanix path.
- **Evaluation harness.** WER, CER, cpWER, tcpWER, WDER, DER, JER, speaker-count
  error, quiet-speaker recall and error decomposition by word category and by
  overlap band, over AMI, SUMM-RE, FLEURS, LibriSpeech, MLS and synthetic
  fixtures, with quality gates that fail the build's own judgement rather than
  ours.

### Measured

Real meeting audio, this hardware, normalizer 1.3.0:

| Corpus | cpWER | WER |
| --- | ---: | ---: |
| AMI English, with participant list | **27.89 %** | 21.25 % |
| AMI English, told nothing | 30.61 % | 21.25 % |
| SUMM-RE French, 12 meetings | 57.04 % | 42.86 % |
| SUMM-RE French, 4 held-out meetings | 51.95 % | 38.18 % |

Azure Speech, the engine behind Teams transcription, is independently measured
at 27.39 % cpWER on AMI. **We have not run Hansard and Teams on the same
recordings**, so parity on AMI is measured and not established, and no claim
that Hansard beats Teams is supported by anything in this repository.

### Sovereignty

No cloud speech API, no external inference, no telemetry containing meeting
content, and no network in the inference path — asserted by a CI job that runs
a transcription and fails if a socket opens. Model weights are downloaded once
at build time and checksum-verified.

### Known limitations

- **French meetings are clearly behind English.** 57.04 % against 30.61 % cpWER.
  The cause is measured: overlapped speech is 17 % of the reference words and
  39 % of the errors, and a single-stream recogniser cannot emit two people at
  once. Fixing it needs a separation front-end that does not fit on 4 vCPU.
- **No head-to-head against Teams**, no NOTSOFAR-1 run, and no blind human
  rating of minutes against Copilot's recap.
- **The quality gates do not pass**: 190 of 360, with 89 must-pass failures, 87
  of them on the AMI and SUMM-RE research corpora. They are quality targets, not
  release criteria, and they are reported rather than relaxed.

### Fixed before tagging

- The Docker Compose stack defaulted to INT8 weights, which the benchmarks show
  stop producing words on real meeting audio. It now matches the Helm chart and
  the documented default: float32.

[0.1.0]: https://github.com/Haswell119/teams-retranscription/releases/tag/v0.1.0
