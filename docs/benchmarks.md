# Benchmarks

Every number on this page was produced by running the code in this repository.
Nothing is copied from a model card. The commands to reproduce each table are
given underneath it.

**Test machine:** 4 vCPU, 15 GB RAM, **no GPU**, Linux 6.18.
That is deliberately modest hardware. If your numbers are better than ours, that
is the expected outcome.

**Normalizer version:** `hansard-normalizers-1.0.0`. Word error rates are not
comparable across normalizers, so this identifier appears in every report we
publish. Changing it forces us to re-record the baseline.

## 1. Speech recognition, French and English

Model: `nemo-parakeet-tdt-0.6b-v3`, INT8 ONNX, CC-BY-4.0.
One model serves both languages; no language tag is required.

| Dataset | Language | Utterances | Audio | WER | CER | Speed | Peak RAM |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FLEURS `fr_fr` test | French | 80 | 14.2 min | **6.95 %** | 2.50 % | 8.7× real-time | 1.38 GB |
| FLEURS `en_us` test | English | 80 | 12.6 min | **4.59 %** | 2.27 % | 8.9× real-time | 1.38 GB |
| LibriSpeech dev-clean | English | 73 | 8.0 min | **3.93 %** | 1.50 % | 8.1× real-time | 1.40 GB |

```bash
make bench-asr
```

**Read this table carefully.** These are *read speech* corpora. They measure
whether the engine is healthy; they do not tell you how the system behaves on a
real meeting. Microsoft's Azure Speech reports 2.78 % on FLEURS `fr_fr`, and we
do not beat that. Read-speech benchmarks are not where a meeting product is
won or lost — see the next section for the reason.

## 2. Meeting transcription with speaker attribution

This is the metric that matters. `cpWER` (concatenated minimum-permutation word
error rate) scores the transcript *and* the speaker attribution together, so a
system that transcribes perfectly but confuses who said what scores badly. It is
the metric used to rank the CHiME-8 and NOTSOFAR challenges.

| Meeting | Speakers (reference → detected) | WER | **cpWER** | tcpWER@5s | **WDER** | DER (collar 0) | DER (collar 0.25) | Speed |
| --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 speakers, 153 s | 3 → **3** | 2.52 % | **3.02 %** | 3.53 % | **0.26 %** | 8.60 % | 3.17 % | 2.9× |
| 6 speakers, 400 s | 6 → **6** | 6.50 % | **9.51 %** | 10.64 % | **1.71 %** | 9.41 % | 4.81 % | 3.0× |
| 9 speakers, 349 s | 9 → **9** | 11.02 % | **13.75 %** | 13.85 % | **1.77 %** | 9.73 % | 4.14 % | 3.1× |

```bash
make bench-meetings
```

The number of speakers was **detected exactly** in all three cases, without
being told in advance. This matters more than it may appear: NVIDIA's Sortformer
diarizer — a natural choice, and one we evaluated — has a hard architectural
limit of four speakers, and its published error rate roughly doubles beyond that.
Real meetings routinely have six to ten participants.

### How this compares to Microsoft

| System | Corpus | cpWER |
| --- | --- | ---: |
| Azure Speech (the engine behind Teams transcription) | AMI | 27.39 % |
| Azure Speech | NOTSOFAR-1 test (Microsoft's own office-meeting corpus) | 35.68 % |
| Azure Speech | NOTSOFAR-1 dev | 45.38 % |
| Hansard | our synthetic meetings, 3–9 speakers | 3.02 – 13.75 % |

*Azure figures: AssemblyAI's January 2026 competitive benchmark, which is the
only public source that scores Azure with cpWER on meeting corpora.*

**These rows are not directly comparable, and we will not pretend otherwise.**
Our meetings are built from clean close-talk recordings mixed together. AMI and
NOTSOFAR include far-field microphones, room reverberation and heavy crosstalk,
which are substantially harder. What our numbers establish is that the pipeline
is sound and that speaker attribution works at nine speakers. Running Hansard on
AMI and NOTSOFAR is the next benchmark we owe you, and the harness to do it
already ships in `hansard.evaluation`.

Note also the gap in Microsoft's own numbers: Azure markets **2.4 % WER** on
curated short clips and scores **27.4 % cpWER** on AMI. That is not dishonesty —
it is the difference between read speech and a real meeting, and it is exactly
why this page separates the two.

## 3. What the metrics mean

| Metric | What it measures | Why you should care |
| --- | --- | --- |
| **WER** | Word error rate, speaker-agnostic | Raw transcription accuracy |
| **CER** | Character error rate | Diacritic fidelity — the metric that catches a French system silently dropping accents |
| **cpWER** | Transcription **and** attribution jointly, under the best speaker permutation | The single number that reflects what a reader experiences |
| **tcpWER@5s** | cpWER with a 5-second time collar | Catches a system with correct text but broken timestamps |
| **WDER** | Of the words recognised correctly, the fraction given to the wrong speaker | Isolates attribution quality from transcription quality |
| **DER** | Diarization error rate: missed speech + false alarm + speaker confusion | Diagnoses *which* part of diarization is failing |
| **JER** | Jaccard error rate, averaged per speaker rather than per second | Catches a system that handles the meeting chair well and mangles the quiet participants |

We report DER at collar 0 with overlapping speech scored, which is the strict
setting, as well as the traditional 0.25-second collar so the numbers can be
compared with older literature.

## 4. Efficiency

| Profile | Hardware | Speed | Peak RAM | 60-minute meeting |
| --- | --- | ---: | ---: | ---: |
| CPU only, full pipeline | 4 vCPU, no GPU | ~3× real-time | 2.9 GB | ~20 minutes |
| CPU only, recognition alone | 4 vCPU, no GPU | ~8.8× real-time | 1.4 GB | ~7 minutes |

Time is spent roughly 55 % on recognition, 40 % on diarization, and 5 % on
everything else. Both scale with CPU cores, so an 8- or 16-core node roughly
halves or quarters those figures, and a GPU profile is available for volume
deployments.

Model footprint on disk is **682 MB** in total: recognition 600 MB, diarization
39 MB, voice activity detection 2 MB.

## 5. Engineering findings worth knowing

Two results from this benchmarking changed the design, and both are the kind of
thing that is easy to get wrong silently.

**Loudness normalisation degrades speaker attribution.** Applying EBU R128
normalisation before diarization produced five clusters for a three-speaker
meeting and a 41.07 % error rate, against 14.75 % with a plain high-pass filter.
Dynamic-range processing alters the spectral envelope over time, which is
precisely the signal a speaker-embedding model relies on. Hansard therefore runs
two audio chains: recognition receives the fully normalised audio, diarization
receives a dynamics-preserving clip.

**The speaker-embedding model matters more than the clustering algorithm.**
Swapping 3D-Speaker CAM++ for NVIDIA TitaNet, changing nothing else, moved
speaker confusion from **47 %** to **0.01 %** on the same audio. CAM++ failed
even when handed the correct number of clusters. Do not assume an embedding
model works because it scores well on speaker verification — measure it inside
your pipeline.

## 6. Reproducing all of this

```bash
git clone https://github.com/Haswell119/teams-retranscription
cd teams-retranscription
make install          # virtualenv and dependencies
make models           # fetch the model bundle, ~682 MB, SHA-256 verified
make bench-data       # fetch the evaluation corpora
make bench            # run everything, write bench/results/*.json
```

Raw result files live in [`bench/results/`](../bench/results/) and carry the
normalizer version, the hardware, and the per-stage timings.

## 7. What we have not measured yet

Being explicit about this is part of the point.

- **AMI and NOTSOFAR-1.** The harness supports them; we have not yet run them.
  Until we do, treat our meeting numbers as evidence the pipeline is sound, not
  as a head-to-head win over Azure.
- **SUMM-RE**, the 91-hour French meeting corpus. This is the important one: no
  vendor has published a French meeting number, and published results for other
  open models sit at 19–23 % WER. Preparation code ships in
  `hansard.evaluation.corpora`.
- **A recorded head-to-head against a live Teams transcript.** The protocol is
  written up in [metrics.md](metrics.md); it needs real meetings and real consent.
- **Minutes quality against Copilot's recap**, blind and rated by humans.

## Related reading

- [Metrics](metrics.md) — every formula and how it is computed
- [Architecture](architecture.md) — what runs where
- [Sovereignty](sovereignty.md) — the other reason to run this
