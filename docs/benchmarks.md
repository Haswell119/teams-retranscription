# Benchmarks

Every number on this page was produced by running the code in this repository.
Nothing is copied from a model card. The commands to reproduce each table are
given underneath it.

**Test machine:** 4 vCPU, 15 GB RAM, **no GPU**, Linux 6.18.
That is deliberately modest hardware. If your numbers are better than ours, that
is the expected outcome.

**Normalizer version:** `hansard-normalizers-1.1.0`. Word error rates are not
comparable across normalizers, so this identifier appears in every report we
publish. Changing it forces us to re-record the baseline. Where a table below
carries a different normalizer version, it says so.

**Shipped profile:** `nemo-parakeet-tdt-0.6b-v3`, **float32 ONNX**. Every
headline number on this page is that profile. The INT8 profile is still
available and still measured; its numbers are in
[§5](#5-choosing-a-quantization-profile), never mixed into the tables above it.

**Both languages, every release.** French and English are benchmarked on the
same schedule with the same harness, and the French numbers gate a release just
as the English ones do. Nothing here is an English measurement with a French
claim attached to it.

## 1. Speech recognition, French and English

Model: `nemo-parakeet-tdt-0.6b-v3`, float32 ONNX, CC-BY-4.0.
One model serves both languages; no language tag is required.

Source: [`bench/results/asr_bilingual.json`](../bench/results/asr_bilingual.json).

| Dataset | Language | Utterances | Audio | WER | CER | RTF | Peak RAM |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FLEURS `fr_fr` test | **French** | 80 | 14.2 min | **4.63 %** | 1.62 % | 0.31 | 2.80 GB |
| FLEURS `en_us` test | English | 80 | 12.6 min | **4.47 %** | 1.99 % | 0.49 | 2.74 GB |
| LibriSpeech dev-clean | English | 73 | 8.0 min | **3.34 %** | 1.19 % | 0.57 | 2.86 GB |

RTF is the real-time factor: processing seconds per second of audio. Lower is
better; 0.31 means 14.2 minutes of French audio were transcribed in 4.5 minutes.

```bash
make bench-asr
```

**Read this table carefully.** These are *read speech* corpora. They measure
whether the engine is healthy; they do not tell you how the system behaves on a
real meeting. Microsoft's Azure Speech reports 2.78 % on FLEURS `fr_fr`, and we
do not beat that. Read-speech benchmarks are not where a meeting product is
won or lost — see the next section for the reason.

French is the corpus we watch hardest, because it is the language most likely to
be silently mishandled: a system that drops diacritics or mangles elisions can
still post a respectable WER. That is why CER is published beside WER, and why
the French normalizer deliberately keeps accents.

## 2. Meeting transcription with speaker attribution

This is the metric that matters. `cpWER` (concatenated minimum-permutation word
error rate) scores the transcript *and* the speaker attribution together, so a
system that transcribes perfectly but confuses who said what scores badly. It is
the metric used to rank the CHiME-8 and NOTSOFAR challenges.

### 2.1 Synthetic meetings, exact ground truth

Source:
[`bench/results/synthetic_meetings.json`](../bench/results/synthetic_meetings.json).

| Meeting | Speakers (reference → detected) | WER | CER | **cpWER** | tcpWER@5s | **WDER** | DER (collar 0) | RTF | Peak RAM |
| --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 speakers, 153 s | 3 → **3** | 2.52 % | 0.94 % | **2.52 %** | 3.02 % | **0.00 %** | 8.64 % | 0.78 | 3209 MB |
| 6 speakers, 400 s | 6 → **6** | 1.32 % | 0.35 % | **5.56 %** | 6.50 % | **1.91 %** | 9.40 % | 0.81 | 3551 MB |
| 9 speakers, 349 s | 9 → **9** | 3.67 % | 2.56 % | **6.51 %** | 6.51 % | **1.52 %** | 9.94 % | 0.61 | 3594 MB |

```bash
make bench-meetings
```

Run settings recorded in the result file: `audio.max_segment_seconds = 30`,
`audio.segment_padding_seconds = 0.2`, `vad.threshold = 0.5`. The shipped default
for `max_segment_seconds` is 120 — see
[§6](#6-engineering-findings-worth-knowing) for what that setting buys and costs.

DER is reported at collar 0 with overlapping speech scored — the strict setting.
This run does not record the traditional 0.25-second collar; the INT8 run in
[§5](#5-choosing-a-quantization-profile) does, and its collar figures are 2.91 %,
5.07 % and 4.40 % on the same three fixtures.

The number of speakers was **detected exactly** in all three cases, without
being told in advance. This matters more than it may appear: NVIDIA's Sortformer
diarizer — a natural choice, and one we evaluated — has a hard architectural
limit of four speakers, and its published error rate roughly doubles beyond that.
Real meetings routinely have six to ten participants.

**What these fixtures are, precisely.** Clean read-speech recordings from
distinct speakers, mixed into a meeting timeline with exact ground truth. The
speech is English. They prove that recognition, diarization and attribution
compose correctly and that attribution survives nine speakers. They do not prove
anything about a real room, and they are not the French meeting evidence — see
[§9](#9-what-we-have-not-measured-yet).

### 2.2 AMI, real meeting audio

Source:
[`bench/results/ami_mix_headset.json`](../bench/results/ami_mix_headset.json).
Three AMI test meetings, Mix-Headset condition, 56.6 minutes of spontaneous
four-person meeting audio, run end to end through the full pipeline and scored
with our own harness. **Normalizer version `hansard-normalizers-1.0.0`** — this
run predates the current normalizer, and predates the float32 default.

| Meeting | Duration | Speakers (reference → detected) | WER | **cpWER** | tcpWER@5s | WDER | DER (collar 0) | RTF |
| --- | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ES2004a | 17.5 min | 4 → 10 | 43.20 % | **48.33 %** | 48.81 % | 6.13 % | 32.78 % | 0.95 |
| IS1009a | 14.0 min | 4 → 10 | 46.39 % | **59.28 %** | 59.89 % | 13.52 % | 30.83 % | 0.91 |
| TS3003a | 25.1 min | 4 → 10 | 41.40 % | **48.29 %** | 49.98 % | 7.61 % | 32.96 % | 0.87 |
| **Macro average** | — | — | **43.66 %** | **51.97 %** | **52.89 %** | **9.09 %** | **32.19 %** | — |

```bash
make bench-data-ami
make bench-ami
```

Word-weighted cpWER is 51.37 %. JER is 46.50 %, DER at the 0.25-second collar is
21.59 %.

**This is where we lose, and it is an open problem, not a footnote.** Azure's
published AMI figure is 27.39 % cpWER. Ours is **51.97 %** — roughly twice the
error. The speaker count is the visible culprit: ten clusters detected where
there are four speakers, in every one of the three meetings. See
[§8](#8-where-we-lose) for what that comparison is and is not worth.

Two later runs are kept alongside as labelled history, because the difference
between them is the size of the problem:

| Run | File | Macro cpWER | Notes |
| --- | --- | ---: | --- |
| Shipped AMI figure | `ami_mix_headset.json` | **51.97 %** | Normalizer 1.0.0, 10 speakers detected |
| Before the diarization fixes | `ami_mix_headset_before_fixes.json` | 51.97 % | The same run, kept as the explicit reference point |
| After the fixes, 30 s segments | `ami_mix_headset_short_segments.json` | 49.39 % | Normalizer 1.1.0, 6 speakers detected, peak RSS up to 7.1 GB |

Neither AMI run has been repeated on the shipped float32 profile. Until it is,
the headline AMI number stays at 51.97 % — we do not publish an improvement we
have not measured.

### 2.3 How this compares to Microsoft

| System | Corpus | cpWER |
| --- | --- | ---: |
| Azure Speech (the engine behind Teams transcription) | AMI | 27.39 % |
| Azure Speech | NOTSOFAR-1 test (Microsoft's own office-meeting corpus) | 35.68 % |
| Azure Speech | NOTSOFAR-1 dev | 45.38 % |
| **Hansard** | **AMI Mix-Headset, 3 meetings** | **51.97 %** |
| Hansard | our synthetic meetings, 3–9 speakers | 2.52 – 6.51 % |

*Azure figures: AssemblyAI's January 2026 competitive benchmark, which is the
only public source that scores Azure with cpWER on meeting corpora.*

**Read the two Hansard rows together or not at all.** On the corpus where a
direct comparison exists, we are behind. On our own fixtures we score well, and
those fixtures are built from clean close-talk recordings mixed together, while
AMI and NOTSOFAR include far-field microphones, room reverberation and heavy
crosstalk. What the synthetic numbers establish is that the pipeline is sound and
that speaker attribution works at nine speakers. What the AMI number establishes
is that spontaneous overlapping speech is not solved here yet.

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

Shipped float32 profile, 4 vCPU, no GPU:

| Profile | RTF | Peak RAM | 60 minutes of audio |
| --- | ---: | ---: | ---: |
| Full pipeline (meeting fixtures) | 0.61 – 0.81 | 3.6 GB | ~44 minutes |
| Recognition alone (read speech) | 0.31 – 0.57 | 2.9 GB | ~26 minutes |

RTF is processing seconds per second of audio; lower is better. The ranges are
the per-corpus extremes, and the 60-minute column uses the duration-weighted
figure across each set — 0.73 for the full pipeline, 0.44 for recognition alone.
Minutes generation is not included: it depends entirely on the model you point
Hansard at.

Time is spent roughly 55 % on recognition, 40 % on diarization, and 5 % on
everything else. Both scale with CPU cores, so an 8- or 16-core node roughly
halves or quarters those figures, and a GPU profile is available for volume
deployments.

Model footprint on disk is **3.2 GB** in total: float32 recognition 2.5 GB,
INT8 recognition 640 MB, diarization 46 MB, voice activity detection 2 MB. The
INT8 weights ship alongside so `HANSARD_ASR__QUANTIZATION=int8` needs no second
download.

## 5. Choosing a quantization profile

Hansard ships **float32** weights and offers **INT8** as an opt-in low-memory
profile. Both are in the bundle; the switch is one environment variable and no
download:

```bash
HANSARD_ASR__QUANTIZATION=none      # default: float32, the numbers above
HANSARD_ASR__QUANTIZATION=int8      # low-memory profile, the numbers below
```

This used to be the other way round. Measurement changed the decision, and the
table is here so you can make it yourself rather than take our word for it.

**Recognition quality.** Sources:
[`asr_bilingual.json`](../bench/results/asr_bilingual.json) and
[`asr_bilingual_int8.json`](../bench/results/asr_bilingual_int8.json).

| Corpus | Language | float32 WER / CER | INT8 WER / CER | Cost of INT8 |
| --- | --- | ---: | ---: | ---: |
| FLEURS `fr_fr` | **French** | **4.63 % / 1.62 %** | 6.67 % / 2.25 % | **+2.04 WER** |
| FLEURS `en_us` | English | **4.47 % / 1.99 %** | 4.59 % / 2.27 % | +0.12 WER |
| LibriSpeech dev-clean | English | **3.34 % / 1.19 %** | 3.93 % / 1.50 % | +0.59 WER |

**The cost falls almost entirely on French.** English barely moves; French loses
two full points. If your meetings are in French, INT8 is the expensive option,
whatever its name suggests.

**Meeting quality.** Sources:
[`synthetic_meetings.json`](../bench/results/synthetic_meetings.json) and
[`synthetic_meetings_int8.json`](../bench/results/synthetic_meetings_int8.json).

| Meeting | float32 WER / cpWER | INT8 WER / cpWER |
| --- | ---: | ---: |
| 3 speakers | **2.52 % / 2.52 %** | 2.52 % / 2.52 % |
| 6 speakers | **1.32 % / 5.56 %** | 4.24 % / 8.29 % |
| 9 speakers | **3.67 % / 6.51 %** | 8.29 % / 11.12 % |

Speaker counting is unaffected: both profiles detect 3, 6 and 9 exactly, and DER
is identical to the second decimal, because diarization does not use the
recognition weights. The gap is transcription, and it widens with the number of
speakers. The INT8 meeting run predates CER reporting for meetings, so those
cells do not exist and are not guessed at here.

**Cost and benefit.**

| | float32 (default) | INT8 (opt-in) |
| --- | ---: | ---: |
| On disk | 2.5 GB | 640 MB |
| Peak RSS, read speech | 2.74 – 2.86 GB | 1.38 – 1.40 GB |
| Peak RSS, meeting pipeline | 3.21 – 3.59 GB | 2.09 – 2.73 GB |
| RTF, read speech | 0.31 – 0.57 | 0.32 – 0.36 |
| RTF, meeting pipeline | 0.61 – 0.81 | 0.83 – 1.28 |
| CPU-seconds per second of audio | **0.645** | **0.650** |

**INT8 is not faster.** That is the finding that reversed the default. On the
controlled measurement the two profiles cost the same CPU time to within one
percent, because the dynamic quantize/dequantize work around each INT8 matmul
cancels out the arithmetic saving. INT8 buys **memory** — roughly 1.4 GB of
resident set and 1.9 GB of disk — and it pays for that memory in accuracy.

**So choose like this:**

- **Use the default (float32)** unless something forces you not to — and
  especially for French meetings.
- **Use INT8** when the recogniser has less than about 4 GB of memory to live in:
  a small container, a shared node, or several concurrent meetings per worker.
  Expect roughly two points of French word error rate as the price, and say so in
  your own reporting.

## 6. Engineering findings worth knowing

Two results from this benchmarking changed the design, and both are the kind of
thing that is easy to get wrong silently.

**Loudness normalisation degrades speaker attribution.** Applying EBU R128
normalisation before diarization produced five clusters for a three-speaker
meeting and a 41.07 % error rate, against 14.75 % with a plain high-pass filter.
Dynamic-range processing alters the spectral envelope over time, which is
precisely the signal a speaker-embedding model relies on. Hansard therefore runs
two audio chains: recognition receives the fully normalised audio, diarization
receives a dynamics-preserving clip.

**Segment length trades memory for accuracy, and the exchange rate is steep.**
On a fourteen-minute AMI meeting, raising the recognition segment ceiling from
28 to 120 seconds recovered 70 words and 4.1 points of word error rate, because
the recognizer sees more context around each turn:

| `audio.max_segment_seconds` | Segments | Words recovered | WER | Peak RAM |
| ---: | ---: | ---: | ---: | ---: |
| 28 | 63 | 65.4 % | 40.7 % | 2.3 GB |
| 60 | 52 | 65.5 % | 40.7 % | 2.9 GB |
| **120** | **50** | **68.9 %** | **36.6 %** | **4.2 GB** |

Transcribing the same audio with no segmentation at all scored better still, so
segmentation is a memory concession rather than an optimisation. The default is
120 seconds; lower it if your nodes are small, and expect to pay for it.

**The speaker-embedding model matters more than the clustering algorithm.**
Swapping 3D-Speaker CAM++ for NVIDIA TitaNet, changing nothing else, moved
speaker confusion from **47 %** to **0.01 %** on the same audio. CAM++ failed
even when handed the correct number of clusters. Do not assume an embedding
model works because it scores well on speaker verification — measure it inside
your pipeline.

## 7. Reproducing all of this

```bash
git clone https://github.com/Haswell119/teams-retranscription
cd teams-retranscription
make install          # virtualenv and dependencies
make models           # fetch the model bundle, ~3.2 GB, SHA-256 verified
make bench-data       # fetch the evaluation corpora
make bench            # run everything, write bench/results/*.json
```

Raw result files live in [`bench/results/`](../bench/results/) and carry the
normalizer version, the hardware, and the per-stage timings.

## 8. Where we lose

Publishing this matters more than publishing the wins.

**On the AMI meeting corpus we are worse than the published Azure figure.** We
ran three AMI test meetings (ES2004a, IS1009a, TS3003a — 56.6 minutes of real,
spontaneous, four-person meeting audio in the Mix-Headset condition) end to end
through the full pipeline, and scored them with our own harness. The macro
average is **51.97 % cpWER** against Azure's published **27.39 %**: we are
roughly twice as wrong on the only corpus where a direct comparison exists. The
per-meeting numbers are in [§2.2](#22-ami-real-meeting-audio) and the raw file is
[`bench/results/ami_mix_headset.json`](../bench/results/ami_mix_headset.json).

This is **the current state of a known open problem**, and it is what every
must-pass quality gate failure in [§10](#10-checking-the-gates) is. The most
legible symptom is speaker counting: ten clusters detected where there are four
speakers, in all three meetings. Spontaneous overlapping speech fragments a
speaker across clusters in a way clean fixtures never do, and cpWER charges for
every fragment. Work on it is tracked by re-running `make bench-ami`, not by
rewording this paragraph.

Two things about that comparison need saying plainly:

- The Azure number comes from a third party (AssemblyAI, January 2026) using
  their own reference preparation and normalizer, on conditions we cannot
  inspect. Many published cpWER figures use reference utterance boundaries;
  ours uses nothing but the raw audio. That difference alone can be worth a
  great deal, in either direction.
- The only rigorous comparison is running Teams on the same recordings and
  scoring both outputs with one toolchain. The protocol for doing that is in
  [metrics](metrics.md); it needs real meetings and real consent, and we have
  not done it.

So: treat the gap as real until proven otherwise, and treat the size of the gap
as uncertain.

**We also do not beat Azure on read speech.** Azure Speech reports 2.78 % on
FLEURS `fr_fr`; we measure 4.63 %. Read-speech benchmarks are not what a meeting
product is for, but pretending they do not exist would be dishonest. The float32
default closed part of that gap — INT8 measured 6.67 % on the same corpus — and
it did not close it.

**Where we are genuinely ahead** is not on the leaderboard: audio that never
leaves your infrastructure, a custom vocabulary that Teams does not offer at all,
no four-hour ceiling, no forced profanity masking, evidence timecodes on every
generated claim, and open export formats.

## 9. What we have not measured yet

Being explicit about this is part of the point.

- **AMI on the shipped float32 profile.** AMI has been run — that is
  [§2.2](#22-ami-real-meeting-audio) — but the recorded run used the old INT8
  default and normalizer 1.0.0. Until it is repeated, the AMI figure is not a
  measurement of what you install today.
- **NOTSOFAR-1.** The harness supports it; we have not run it.
- **A French meeting corpus. This is the gap that matters most.** French
  recognition is measured on every release (FLEURS `fr_fr`, [§1](#1-speech-recognition-french-and-english)),
  and French thresholds gate every run — but the *meeting* fixtures are English
  speech, so no French cpWER exists yet, here or anywhere else. **SUMM-RE**, the
  91-hour French meeting corpus, is the run we owe you: no vendor has published a
  French meeting number, and published results for other open models sit at
  19–23 % WER. Preparation code ships in `hansard.evaluation.corpora`.
- **A recorded head-to-head against a live Teams transcript.** The protocol is
  written up in [metrics.md](metrics.md); it needs real meetings and real consent.
- **Minutes quality against Copilot's recap**, blind and rated by humans.

## 10. Checking the gates

The project defines quality gates in `src/hansard/evaluation/gates.py`: a
must-pass threshold and a stretch target for every headline metric, separately
for French and for English. They exist so that "is this good enough?" has an
answer that does not depend on anyone's opinion.

```bash
make bench     # produce measurements
make gates     # score them against the thresholds
```

The command prints every gate that is not met and exits non-zero if any
must-pass gate fails. A must-pass failure means the work is not finished.

Only the shipped profile is scored. Result files carrying a `profile` field —
the INT8 runs and the historical AMI runs — are skipped, so a gate can never be
passed by a configuration nobody installs.

Current status on the hardware described at the top of this page, over every
shipped-profile result in `bench/results/`:

```
FAIL must_pass ES2004a                            cpwer                   48.33% <= 27.00%
FAIL stretch   ES2004a                            cpwer                   48.33% <= 20.00%
FAIL must_pass ES2004a                            tcpwer                  48.81% <= 30.00%
FAIL stretch   ES2004a                            wder                     6.13% <= 5.00%
FAIL must_pass ES2004a                            wer                     43.20% <= 15.00%
FAIL stretch   ES2004a                            wer                     43.20% <= 12.00%
FAIL must_pass ES2004a                            der                     32.78% <= 15.00%
FAIL stretch   ES2004a                            der                     32.78% <= 8.00%
FAIL must_pass ES2004a                            speaker_count_error      6.00 <= 1.00
FAIL stretch   ES2004a                            rtf                      0.95 <= 0.35
FAIL must_pass IS1009a                            cpwer                   59.28% <= 27.00%
FAIL stretch   IS1009a                            cpwer                   59.28% <= 20.00%
FAIL must_pass IS1009a                            tcpwer                  59.89% <= 30.00%
FAIL must_pass IS1009a                            wder                    13.52% <= 10.00%
FAIL stretch   IS1009a                            wder                    13.52% <= 5.00%
FAIL must_pass IS1009a                            wer                     46.39% <= 15.00%
FAIL stretch   IS1009a                            wer                     46.39% <= 12.00%
FAIL must_pass IS1009a                            der                     30.83% <= 15.00%
FAIL stretch   IS1009a                            der                     30.83% <= 8.00%
FAIL must_pass IS1009a                            speaker_count_error      6.00 <= 1.00
FAIL stretch   IS1009a                            rtf                      0.91 <= 0.35
FAIL must_pass TS3003a                            cpwer                   48.29% <= 27.00%
FAIL stretch   TS3003a                            cpwer                   48.29% <= 20.00%
FAIL must_pass TS3003a                            tcpwer                  49.98% <= 30.00%
FAIL stretch   TS3003a                            wder                     7.61% <= 5.00%
FAIL must_pass TS3003a                            wer                     41.40% <= 15.00%
FAIL stretch   TS3003a                            wer                     41.40% <= 12.00%
FAIL must_pass TS3003a                            der                     32.96% <= 15.00%
FAIL stretch   TS3003a                            der                     32.96% <= 8.00%
FAIL must_pass TS3003a                            speaker_count_error      6.00 <= 1.00
FAIL stretch   TS3003a                            rtf                      0.87 <= 0.35
FAIL stretch   FLEURS en_us (read speech)         wer                      4.47% <= 3.00%
FAIL stretch   FLEURS en_us (read speech)         rtf                      0.49 <= 0.35
FAIL stretch   LibriSpeech dev-clean (read speech) wer                      3.34% <= 3.00%
FAIL stretch   LibriSpeech dev-clean (read speech) rtf                      0.57 <= 0.35
FAIL stretch   meeting_3spk                       der                      8.64% <= 8.00%
FAIL stretch   meeting_3spk                       rtf                      0.78 <= 0.35
FAIL stretch   meeting_6spk                       der                      9.40% <= 8.00%
FAIL stretch   meeting_6spk                       rtf                      0.81 <= 0.35
FAIL stretch   meeting_9spk                       der                      9.94% <= 8.00%
FAIL stretch   meeting_9spk                       rtf                      0.61 <= 0.35

58/99 gates met  (16 must-pass failures, 25 stretch misses)

Must-pass gates are not met. The work is not finished.
```

**Every must-pass failure is an AMI meeting.** That is the open problem of
[§8](#8-where-we-lose), stated by the tooling rather than by us. Nothing on the
synthetic meetings or on read speech blocks a release any more.

Two things changed when float32 became the default, and both are visible above:

- **FLEURS `fr_fr` now passes every gate it has, must-pass and stretch alike**
  — 4.63 % WER against a 6.00 % blocker and a 5.00 % target, 1.62 % CER against
  3.00 %. Under INT8 it failed both.
- **FLEURS `en_us` CER** (1.99 % against a 2.00 % blocker) also went from failing
  to passing.

The remaining stretch misses are the RTF target of 0.35 — which the float32
profile does not reach and INT8 does not reliably reach either — and DER on the
meeting fixtures, at roughly 9 % against an 8 % target.

The French meeting gates are defined and are not exercised, because there is no
French meeting corpus in `bench/results/` yet. That is a missing measurement, not
a pass; see [§9](#9-what-we-have-not-measured-yet).

We are not going to lower a threshold to turn a failure into a success. If a
threshold turns out to be wrong, it changes only with published evidence and a
note in this page saying what changed and why.

## Related reading

- [Metrics](metrics.md) — every formula and how it is computed
- [Architecture](architecture.md) — what runs where
- [Sovereignty](sovereignty.md) — the other reason to run this
