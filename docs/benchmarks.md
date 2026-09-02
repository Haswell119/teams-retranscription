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
as the English ones do. French read speech is measured and passing
([§1](#1-speech-recognition-french-and-english)); French synthetic meetings are
built by the same generator as the English ones and recorded beside them
([§2.2](#22-french-synthetic-meetings)); one real French meeting is recorded too,
and it is our worst published result ([§2.5](#25-summ-re-real-french-meeting-audio)).
Nothing here is an English measurement with a French claim attached to it.

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

### 2.1 English synthetic meetings, exact ground truth

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
speech is English — LibriSpeech dev-clean speakers. They prove that recognition,
diarization and attribution compose correctly and that attribution survives nine
speakers. They do not prove anything about a real room.

### 2.2 French synthetic meetings

French meetings are now scored end to end, not only French read speech. Three
French fixtures are built by the **same generator** as the English ones, from
Multilingual LibriSpeech French dev speakers, so the two languages are directly
comparable — same recipe, same speaker counts, same overlap ratios, same metrics:

| Fixture | Speakers | Duration | Source speakers |
| --- | :---: | ---: | --- |
| `meeting_fr_3spk` | 3 | 360.6 s | MLS French dev |
| `meeting_fr_6spk` | 6 | 756.0 s | MLS French dev |
| `meeting_fr_9spk` | 9 | 842.5 s | MLS French dev |

`make bench-data` produces both language sets and `make bench-meetings` scores
all six fixtures, French and English, in one run.

Source:
[`bench/results/synthetic_meetings_fr.json`](../bench/results/synthetic_meetings_fr.json).

| Meeting | Speakers (reference → detected) | Words (reference → produced) | WER | CER | **cpWER** | tcpWER@5s | **WDER** | DER (collar 0) | RTF | Peak RAM |
| --- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `meeting_fr_3spk`, 361 s | 3 → **3** | 846 → 843 | 4.20 % | 1.62 % | **4.20 %** | 4.20 % | **0.00 %** | 11.88 % | 0.30 | 3391 MB |
| `meeting_fr_6spk`, 756 s | 6 → **6** | 1990 → 1998 | 5.08 % | 1.82 % | **6.48 %** | 6.67 % | **0.69 %** | 8.87 % | 0.29 | 3950 MB |
| `meeting_fr_9spk`, 843 s | 9 → **9** | 2091 → 2058 | 7.23 % | 4.16 % | **13.36 %** | 13.94 % | **3.42 %** | 13.98 % | 0.29 | 4118 MB |

```bash
make bench-data
make bench-meetings
```

The speaker count is exact at three, six and nine, as in English, and the word
counts show no systematic loss. French is *faster* than English here — 0.29
against 0.61–0.81 — because the source utterances are longer, so the recognizer
spends less of its time on segment overheads.

French cpWER rises more steeply with speaker count than English does (4.20 %,
6.48 %, 13.36 % against 2.52 %, 5.56 %, 6.51 %). The WER column shows why: at
nine speakers French WDER is 3.42 % against 1.52 % in English, so the extra
error is speaker attribution rather than recognition.

### 2.3 Code-switched meetings, French and English in one room

Source:
[`bench/results/mixed_meetings.json`](../bench/results/mixed_meetings.json).
Three fixtures built from the same French and English speaker pools as above,
with each speaker's utterances drawn from both languages so that the language
changes within the meeting and within a speaker's turns. No language tag is
given to the recognizer.

| Fixture | Speakers (reference → detected) | WER | **cpWER** | tcpWER@5s | WDER | **Language accuracy** |
| --- | :---: | ---: | ---: | ---: | ---: | ---: |
| `meeting_mixed_4spk` | 4 → **4** | 13.83 % | 23.56 % | 24.15 % | 3.55 % | 97.58 % |
| `meeting_mixed_6spk` | 6 → 7 | 4.44 % | 21.62 % | 22.30 % | 7.28 % | 97.79 % |
| `meeting_mixed_8spk` | 8 → **8** | 12.71 % | **12.45 %** | 12.45 % | **0.88 %** | 93.63 % |
| **macro average** | | **10.33 %** | **19.21 %** | 19.63 % | **3.90 %** | **96.33 %** |

```bash
make bench-mixed
```

**Language accuracy is 96.33 %, under the 98 % gate, and the errors run one
way.** 105 French words were labelled English; 41 English words were labelled
French. Language is currently decided from the recognized *text*, so a French
utterance that decodes into English-looking words is then confidently labelled
English — the recognition error and the language error have the same cause and
reinforce each other. Fixing this needs a language decision that comes from the
audio rather than from our own output; it has not been done.

Two further caveats. These fixtures are clean close-talk recordings summed
together, so they measure code-switching and not a real room — the same caveat
that applies to §2.1 and §2.2, and the reason [§2.4](#24-ami-real-meeting-audio)
and [§2.5](#25-summ-re-real-french-meeting-audio) exist. And the code-switching
is *between* utterances, not inside them; a fixture where a speaker switches
language mid-sentence is not built yet.

### 2.4 AMI, real meeting audio

Source:
[`bench/results/ami_mix_headset.json`](../bench/results/ami_mix_headset.json).
Three AMI test meetings, Mix-Headset condition, 56.6 minutes of spontaneous
four-person meeting audio, run end to end through the full pipeline and scored
with our own harness. No participant list is supplied — the system is told
nothing about how many people are in the room.

| Meeting | Duration | Speakers (reference → detected) | Words (reference → produced) | WER | **cpWER** | tcpWER@5s | WDER | DER (collar 0) | Reference overlap | RTF | Peak RAM |
| --- | ---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ES2004a | 17.5 min | 4 → 5 | 2614 → 2239 | 18.87 % | **28.30 %** | 29.93 % | 7.47 % | 31.06 % | 21.3 % | 0.57 | 4770 MB |
| IS1009a | 14.0 min | 4 → **4** | 1986 → 1729 | 22.66 % | **31.70 %** | 33.38 % | 8.25 % | 25.87 % | 18.6 % | 0.61 | 4805 MB |
| TS3003a | 25.1 min | 4 → 5 | 2518 → 2233 | 19.79 % | **26.25 %** | 27.75 % | 4.63 % | 28.74 % | 12.9 % | 0.40 | 4805 MB |
| **Macro average** | — | — | — | **20.44 %** | **28.75 %** | **30.35 %** | **6.78 %** | **28.56 %** | 17.6 % | — | — |

```bash
make bench-data-ami
make bench-ami
```

Word-weighted cpWER is 28.52 %; DER at the 0.25-second collar is 18.34 %.

**With a participant list, which is what the bot has.** When Hansard joins a
meeting it knows who is present, and the roster becomes a ceiling on the speaker
count. Source:
[`ami_mix_headset_roster.json`](../bench/results/ami_mix_headset_roster.json).

| Meeting | Speakers (reference → detected) | **cpWER** | WDER | DER (collar 0) | RTF |
| --- | :---: | ---: | ---: | ---: | ---: |
| ES2004a | 4 → **4** | **25.89 %** | 6.71 % | 29.87 % | 0.28 |
| IS1009a | 4 → **4** | **31.70 %** | 8.25 % | 25.87 % | 0.28 |
| TS3003a | 4 → **4** | **24.44 %** | 3.47 % | 27.46 % | 0.24 |
| **Macro average** | — | **27.34 %** | **6.14 %** | **27.73 %** | — |

Every meeting finds the right number of speakers, and macro cpWER lands at
**27.34 %**. Recognition is untouched — WER is 20.44 % in both configurations —
so the whole gain is attribution.

**How this run differs from the one it replaces.** The previously published
figure on this page was 49.39 % macro cpWER. That run used **INT8 weights**,
which delete words wholesale on real meeting audio (see
[§5](#5-choosing-a-quantization-profile)); the shipped default is float32. The
diarization retune and a batch-padding fix account for the rest:

| | Superseded (INT8) | Current (float32) | With a roster |
| --- | ---: | ---: | ---: |
| Macro WER | 41.38 % | **20.44 %** | 20.44 % |
| Macro cpWER | 49.39 % | **28.75 %** | **27.34 %** |
| Macro WDER | 9.38 % | 6.78 % | 6.14 % |
| Macro DER | 32.19 % | 28.56 % | 27.73 % |
| Speakers detected | 6, 6, 6 | 5, 4, 5 | **4, 4, 4** |
| Peak RSS | 7138 MB | **4805 MB** | 4794 MB |
| RTF | 0.61 – 0.74 | 0.40 – 0.61 | **0.24 – 0.28** |

The superseded run is kept as
[`ami_mix_headset_short_segments.json`](../bench/results/ami_mix_headset_short_segments.json),
labelled historical, because the distance between the two columns is the size of
the mistake.

**The DER gate cannot be met on this corpus, and that is arithmetic.** A diarizer
naming one speaker per instant cannot label overlapped speech, so its missed rate
has a floor equal to the reference overlap: 21.3 %, 18.6 % and 12.9 %. Our
must-pass gate asks for DER ≤ 15 %. On AMI that is unreachable by construction
for any single-stream system, ours included. The gate stays where it is because
it is right for the audio a Teams meeting produces; on AMI, read the confusion
and false-alarm components instead.

### 2.5 SUMM-RE, real French meeting audio

Source: [`bench/results/summ_re.json`](../bench/results/summ_re.json). AMI gave
us a real spontaneous *English* meeting to be measured against. SUMM-RE, a French
meeting corpus published by Linagora under CC-BY-SA-4.0, is the French
counterpart: per-speaker tracks summed into one mixed stream, which is the same
construction as the AMI Mix-Headset condition and the same thing Teams delivers.

| Meeting | Duration | Speakers (reference → detected) | Words (reference → produced) | WER | **cpWER** | tcpWER@5s | WDER | DER (collar 0) | Reference overlap | RTF |
| --- | ---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `020c_EBPZ` | 18.2 min | 4 → **4** | 3283 → 2356 | 37.52 % | **53.16 %** | 56.52 % | 17.17 % | 36.22 % | 5.06 % | 0.59 |

```bash
make bench-data-summre
make bench-summre
```

**This is our worst published result, and it is the honest one.** 53.16 % cpWER
on a real French meeting, against 28.75 % on real English meetings. A participant
list does not help here — `summ_re_roster.json` scores identically, because the
speaker count is already right and there is nothing for a roster to fix.

**The run this replaces caught a real defect.** The first recorded run used
`merge_similarity = 0.70`, a value tuned on AMI. On this meeting that threshold
fused genuinely different people, collapsing four speakers into two and carrying
cpWER to **89.82 %**. The default is now 0.77, the speaker count is exact, and
cpWER fell by 36 points. That run is not kept as a file; see
[configuration](configuration.md#minimum_speaker_seconds-and-merge_similarity-the-pair-that-was-retuned)
for the sweep and [§8](#8-where-we-lose) for what it means.

Three things are worth reading off the current row. Missed speech is 3.69 %
against 5.06 % reference overlap, so coverage of the audio is at the structural
floor — the pipeline is hearing the meeting. False alarm is 18.58 %, over half
of the 36.22 % DER and now the largest component: the diarizer claims speech
where the reference has none. Confusion is 13.96 %, another 38.5 %. Between them
they say this is an attribution failure, not a recognition failure — and yet
WER alone is 37.52 %, so recognition on casual French is not doing well either.

The corpus is also a harder speaker-count problem than AMI. Its four speakers
talk for 380, 326, 59 and 12 seconds; AMI's four each talk for minutes. A
meeting where two participants barely speak is the ordinary case in an
organisation, and it is exactly the case the synthetic fixtures do not test.

### 2.6 How this compares to Microsoft

| System | Corpus | cpWER |
| --- | --- | ---: |
| Azure Speech (the engine behind Teams transcription) | AMI | 27.39 % |
| Azure Speech | NOTSOFAR-1 test (Microsoft's own office-meeting corpus) | 35.68 % |
| Azure Speech | NOTSOFAR-1 dev | 45.38 % |
| **Hansard, with a participant list** | **AMI Mix-Headset, 3 meetings** | **27.34 %** |
| **Hansard, told nothing** | **AMI Mix-Headset, 3 meetings** | **28.75 %** |
| Hansard | SUMM-RE, real French meeting | 53.16 % |
| Hansard | our synthetic meetings, 3–9 speakers, French and English | 2.52 – 13.36 % |

*Azure figures: AssemblyAI's January 2026 competitive benchmark, which is the
only public source that scores Azure with cpWER on meeting corpora.*

**On AMI we are now level with Azure, and that claim needs three caveats before
you believe it.**

- The Azure number comes from a third party using their own reference
  preparation and normalizer, on conditions we cannot inspect. Many published
  cpWER figures score against reference utterance boundaries; ours starts from
  nothing but the raw audio, which is harder. That difference alone can be worth
  several points in either direction.
- Three meetings is a small sample. Per-meeting cpWER ranges from 24.44 % to
  31.70 %, so the macro average carries real variance.
- The only rigorous comparison is running Teams on the same recordings and
  scoring both outputs with one toolchain. The protocol is in
  [metrics](metrics.md); it needs real meetings and real consent, and we have
  not done it.

So: treat parity on AMI as *measured but not established*. What is not in doubt
is the direction — this page previously published 49.39 % against the same Azure
figure, and the change came from fixing our own defects rather than from
changing how we score.

**On French meetings we are behind, and nobody has a number to be behind.** Our
real French meeting scores 53.16 % cpWER. Neither Microsoft nor anyone else
publishes a French meeting figure, so there is nothing to compare it against —
which cuts both ways. It is not evidence that we are better than Teams in
French, and it is the reason [§2.5](#25-summ-re-real-french-meeting-audio) exists
at all.

Note also the gap in Microsoft's own numbers: Azure markets **2.4 % WER** on
curated short clips and scores **27.4 % cpWER** on AMI. That is not dishonesty —
it is the difference between read speech and a real meeting, and it is exactly
why this page separates the two. We are subject to the same gap: 4.63 % on
French read speech, 53.16 % on a French meeting.

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
| Full pipeline, English meeting fixtures | 0.61 – 0.81 | 3.6 GB | ~44 minutes |
| Full pipeline, French meeting fixtures | 0.29 – 0.30 | 4.1 GB | ~18 minutes |
| Recognition alone (read speech) | 0.31 – 0.57 | 2.9 GB | ~26 minutes |

RTF is processing seconds per second of audio; lower is better. The ranges are
the per-corpus extremes, and the 60-minute column uses the duration-weighted
figure within each set — 0.73, 0.29 and 0.44 respectively. The two fixture sets
are reported separately rather than blended: they were recorded in different
runs, and averaging a 0.73 with a 0.29 would produce a number that describes
neither. Take the English row as the conservative one. Minutes generation is not
included: it depends entirely on the model you point Hansard at.

Time is spent roughly 55 % on recognition, 40 % on diarization, and 5 % on
everything else. Both scale with CPU cores, so an 8- or 16-core node roughly
halves or quarters those figures, and a GPU profile is available for volume
deployments.

Model footprint on disk is **3.2 GB** in total: float32 recognition 2.5 GB,
INT8 recognition 670 MB, diarization 42 MB (segmentation 1.5 MB, embeddings
40 MB), voice activity detection 2 MB. The INT8 weights ship alongside so
`HANSARD_ASR__QUANTIZATION=int8` needs no second download.

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

**Real meeting audio, where the difference stops being a rounding error.** The
synthetic fixtures are clean close-talk recordings mixed together. AMI is not.
Measured on ES2004a with everything else held fixed — same audio, same
enhancement, the same 107 Silero spans covering 766 seconds, the same 93 planned
segments, the same batching — and only the weights changed:

| Weights | Hypothesis words | WER | Substitutions | Deletions | Insertions | Segments returning no text |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| float32 | **2239** | **18.87 %** | 82 | 386 | 37 | 2 of 93 |
| INT8 | 1410 | 47.23 % | 47 | **1210** | 7 | 11 of 93 |

INT8 does not mostly get words *wrong* on this audio. It stops producing them.
Substitutions actually fall — there is less text left to be wrong about — while
deletions more than triple and eleven whole segments come back as empty strings.
Reference words missing from the transcript go from 14 % to 46 %.

Read speech does not show this, and that is the trap: on FLEURS and LibriSpeech
the same weights cost between 0.1 and 2.0 points, so a read-speech benchmark
signs INT8 off as a cheap trade. The difference is the audio. Read speech is one
close talker at a steady level in a quiet room; a meeting is several people at
conversational level with crosstalk, room noise and a moving noise floor, and
that is where the quantized encoder's dynamic range runs out. **Never qualify a
quantized recogniser on read speech alone.**

**Cost and benefit.**

| | float32 (default) | INT8 (opt-in) |
| --- | ---: | ---: |
| On disk | 2.5 GB | 670 MB |
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
- **Use INT8** only when the recogniser has less than about 4 GB of memory to
  live in and the recording is close-talk and clean — dictation, a single
  presenter, a phone interview. On real multi-party meeting audio it costs 28
  points of word error rate and loses nearly half the words, which is not a
  trade any transcript should make. If a meeting worker cannot fit float32,
  give it more memory rather than fewer words.

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

`make bench-data` builds the English, French and code-switched meeting fixtures,
and `make bench-meetings` scores all nine in one run; `make bench-mixed` scores
the three bilingual ones on their own. Add `make bench-data-ami` and
`make bench-ami` for the AMI corpus. The code-switched fixtures need both speaker
pools, so they are skipped when the French corpus could not be fetched, and
`--skip-mixed-meetings` suppresses them explicitly.

Raw result files live in [`bench/results/`](../bench/results/) and carry the
normalizer version, the hardware, and the per-stage timings. A file with a
`profile` field — the INT8 runs, the historical AMI runs — is kept for comparison
and is excluded from the gate check.

Two more targets exist for asking questions rather than publishing answers.
`make bench-shootout` runs one or more recognizers over byte-identical
reference-boundary segments and scores them with one normalizer, reporting word
error split by overlap band and by word category; `ENGINES=parakeet-fp32,canary-1b-v2-fr`
selects what to compare. `make bench-sweep` runs recognition **once** per
meeting, caches the transcript, and then re-diarizes and re-attributes those same
words for every point on a grid, so a diarization question costs one recognition
pass instead of one per configuration. Neither writes a published number; both
write to `bench/results/` for the [quality-research log](quality-research.md).

**The read-speech benchmark used to build its own recognizer**, bypassing the
registry, which meant it ignored `HANSARD_RUNTIME__MODELS_DIR` and would fetch
weights from the network instead of using the verified local bundle. It now goes
through `build_recognizer` like everything else, so `make bench-asr` reproduces
[§1](#1-speech-recognition-french-and-english) offline and follows
`HANSARD_ASR__QUANTIZATION` the way the rest of the harness does.

## 8. Where we lose

Publishing this matters more than publishing the wins.

**On real English meetings we are level with Azure, not ahead of it.** We ran
three AMI test meetings (ES2004a, IS1009a, TS3003a — 56.6 minutes of real,
spontaneous, four-person meeting audio in the Mix-Headset condition) end to end
through the full pipeline, and scored them with our own harness. The macro
average is **28.75 % cpWER** told nothing, **27.34 %** with a participant list,
against Azure's published **27.39 %**. Level is not ahead, and on a three-meeting
sample it is not even reliably level. The per-meeting numbers are in
[§2.4](#24-ami-real-meeting-audio) and the raw file is
[`bench/results/ami_mix_headset.json`](../bench/results/ami_mix_headset.json).

The most legible symptom left is speaker counting: five, four and five clusters
detected where there are four speakers. It was ten in all three meetings before
the segmentation and clustering fixes, and 49.39 % macro cpWER; the direction of
travel is right and the distance left is real. Spontaneous overlapping speech
fragments a speaker across clusters in a way clean fixtures never do, and cpWER
charges for every fragment. A Teams roster removes this particular error, which
is why the roster row exists. Work on it is tracked by re-running
`make bench-ami`, not by rewording this paragraph.

**On real French meetings we are clearly behind, and nobody publishes a number
to be behind.** 53.16 % cpWER on SUMM-RE against 28.75 % on AMI. Half of that
gap is recognition — 37.52 % WER on casual French against 20.44 % on AMI — and
half is attribution. This is the largest open quality problem in the project.

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

**The words we were not producing were a quantization failure, not a pipeline
failure.** An earlier version of this page reported that we produced roughly
58 % of the reference words on AMI and called it the largest defect in the
project. It was real, and it was the INT8 weights. Measured on ES2004a with
everything else held fixed — same audio, same enhancement, the same 107 Silero
spans covering 766 seconds, the same 93 planned segments, the same batching —
float32 produces **2239 words at 18.87 %** word error rate and INT8 produces
**1410 at 47.23 %**. Deletions go from 386 to 1210, and eleven segments come back
as empty strings instead of two. INT8 does not mostly get this audio *wrong*; it
stops producing words. The same weights cost between 0.1 and 2.0 points on
FLEURS and LibriSpeech, which is exactly why read-speech benchmarks signed them
off, and it is why this page now insists that **a quantized recogniser is never
qualified on read speech alone**.

Two things were ruled out before the weights were found, and both are worth
recording because both are the obvious first guess:

- *Voice activity detection was not dropping them.* Silero covers 91.9 %, 97.9 %
  and 83.4 % of reference speech time, and the segments already handed to the
  recognizer contain 98.0 %, 99.5 % and 96.1 % of the reference words. The most
  aggressive VAD retune tried reaches 99.0 / 100.0 / 99.1 — worth about one point
  of macro word error rate for five changed defaults and 10–18 % more
  recognition time. It was not adopted.
- *Disfluencies in the reference were not it either.* Filled pauses and
  backchannels are 8.8 %, 10.2 % and 9.2 % of the reference words, and that count
  generously includes words the recognizer does emit.

Of the deletions that remain under float32, **67 %, 81 % and 39 % fall inside
reference-overlap regions** against base rates of 29 %, 28 % and 16 %. A
recognizer that emits one stream cannot emit two people talking at once. That
floor is architectural, not a tuning exercise.

**Some of the diarization error is structural and cannot be tuned away.** A
system that names one speaker per instant cannot label two people talking at
once, so overlapped speech is counted as missed however good the system is. AMI
reference overlap is 21.3 %, 18.5 % and 12.9 %; our missed-speech component sits
close to those figures. Read the missed column against that floor rather than
against zero — see [metrics](metrics.md#44-der--diarization-error-rate). Getting
under it needs overlap-aware diarization, which is a different architecture.

**A real French meeting exposed a default that clean fixtures could not.** On
SUMM-RE `020c_EBPZ`, the shipped `merge_similarity` of 0.70 fused genuinely
different speakers and collapsed four people into two, taking cpWER to 89.82 %.
The synthetic French fixtures gave no hint of it: their speakers all talk for
minutes, while two of SUMM-RE's talk for 59 and 12 seconds. The default is now
0.77, the speaker count is exact and cpWER is 53.16 %. The durable lesson is not
the number — **a default
tuned on one corpus is a hypothesis, not a result**, and the fixtures that pass
are the ones least likely to catch its failure.

**On that meeting our own segmentation loses words, and we do not know why.** The
shipped path hands the recognizer 906.6 seconds in 106 segments and returns 2356
of 3283 reference words at 37.52 % word error rate. The corpus's own utterance
boundaries hand it 756.3 seconds — twenty percent *less* audio — in 215 segments,
and reach 26.59 %. We feed it more and receive less, so nothing is missed for
want of detection. **Four explanations have been measured and all four
are dead:**

| Hypothesis | Test | Verdict |
| --- | --- | --- |
| Segments mix speakers | Single-speaker 4.82 s spans score **32.19 %**; mixed-speaker 4.95 s spans score **25.46 %** | Dead — mixed is *better* |
| Segments are too long | Full-harness ceiling sweep: 37.52 % at 120 s, **35.62 %** at 20 s, 36.54 % at 8 s | Dead — under two points where the oracle is worth eleven |
| We feed too much silence | 756 s → 26.59 %, 871 s → **25.46 %**, 907 s → 37.52 %, 1002 s → 32.19 % | Dead — not monotone; adding silence *helped* twice |
| The overlap and seam mechanism | Removing the overlap entirely: −0.56 points at a 20 s ceiling, **+0.69** at 8 s | Dead — noise |

Every configuration we can reach lands between 35.6 % and 37.5 %.

**That open question is now closed, and the answer is not boundaries.** Handing
the recognizer the corpus's own utterance spans across **seven** SUMM-RE tuning
meetings — 855 segments, 1803 seconds, no detector, no padding, no seams — leaves
**30.82 %** word error. Perfect boundaries are worth about seven points. Thirty-one
remain. Boundary precision was the leading candidate; it is a real term and it is
not the dominant one.

**The dominant term is the second voice.** Splitting the same hypotheses by how
much of each reference utterance another participant is talking over:

| Overlap with another speaker | Segments | Reference words | WER | Utterances returned empty |
| --- | ---: | ---: | ---: | ---: |
| clean, under 5 % | 414 | 3758 | **20.60 %** | 9 |
| light, 5–50 % | 177 | 2154 | 23.35 % | 7 |
| **heavy, over 50 %** | 238 | 1232 | **70.54 %** | **48** |

Heavily overlapped speech is **17 % of the reference words and 39 % of the
errors**. And the 66 utterances the recognizer answers with silence are buried
under another speaker **84.3 %** of the time, against **31.6 %** for the ones it
does transcribe; 75.8 % of them are more than half covered, against 27.4 % of the
rest.

Read the first row again: **on clean French spontaneous meeting speech the
shipped recognizer scores 20.60 %**, which is close to what it scores on English
AMI. It is not bad at French. It is bad at two people at once, and on one mixed
stream it has no way to be anything else. That is why
[§9](#9-what-we-have-not-measured-yet) now names speech separation as the largest
unexplored lever, and why it also explains why we cannot afford it.

**A bigger, newer, better-ranked recognizer does not fix it.** NVIDIA Canary 1B
v2 — CC-BY-4.0, ONNX, explicitly conditioned on French, and ahead of Parakeet on
the Open ASR multilingual French track (4.83 against 5.42) — was run on
byte-identical segments and scored **38.01 %** against Parakeet's 30.82 %. It
loses in every overlap band and every duration band, at twice the memory. Its
failure has a shape worth recording: it produced 1 empty output where Parakeet
produced 66, and paid for that with **672 insertions against 369** and 1190
substitutions against 879. On a short, half-buried turn Parakeet says nothing and
Canary says something wrong. For a verbatim record, invention is the worse
failure. The full table is in
[quality-research](quality-research.md#iteration-4--canary-1b-v2-instead-of-parakeet).

The floor underneath all of it is the register rather than the machinery. One
participant's own isolated 32 kHz track, scored against that participant's own
reference with oracle boundaries and no mixing or segmentation of ours involved,
still scores **28.05 %**, against 4.63 % on French read speech. Expect the low
twenties on clean casual multi-party French, and treat any claim that a
segmentation change alone will reach read-speech numbers as unsupported.

**One point of the published SUMM-RE figure was our own scoring.** SUMM-RE is
annotated in the SPPAS convention, where `+` marks a short pause. The French
normalizer expands a bare `+` into the word "plus", so 533 pause marks — 1.61 %
of every reference token — became words no recognizer could produce, each one a
guaranteed deletion. The corpus reader now strips them, which moved the
reference-boundary figure from 31.54 % to 30.82 % on unchanged hypotheses.

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

- **NOTSOFAR-1.** The harness supports it; we have not run it. The corpus is
  CC-BY-4.0 and downloadable, but the dev and eval splits are 40 GB and 84 GB,
  and the official metric is `tcpWER` scored with `fgnt/meeteval` — which we
  already depend on. It is a machine-time problem, not a code problem.
- **A recorded head-to-head against a live Teams transcript.** The protocol is
  written up in [metrics.md](metrics.md); it needs real meetings and real consent.
  `hansard compare` is the tool for it: it scores several systems against one
  reference and now breaks the result down by the language actually spoken, by
  word category (names, numbers, code-switched words, function words) and by how
  long each reference speaker actually spoke. The tool is tested; the head-to-head
  is not run.
- **Minutes quality against Copilot's recap**, blind and rated by humans.
- **Any speech separation front-end.** [§8](#8-where-we-lose) now shows that
  overlapped speech is where the French words go. Every credible single-channel
  separator for meetings — the NOTSOFAR-1 baseline's Conformer CSS, TF-GridNet,
  MossFormer2, SepFormer — costs one to two orders of magnitude more compute than
  this entire pipeline, and the NOTSOFAR baseline additionally runs three
  parallel ASR decodes on the separated streams. On 4 vCPU with no GPU that is
  not affordable, and we have not measured it. It remains the largest known
  unexplored lever.

## 10. Checking the gates

The project defines quality gates in `src/hansard/evaluation/gates.py`: a
must-pass threshold and a stretch target for every headline metric, separately
for French, for English and for meetings held in both at once. They exist so that "is this good enough?" has an
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
FAIL must_pass ES2004a                            cpwer                   28.30% <= 27.00%
FAIL stretch   ES2004a                            cpwer                   28.30% <= 20.00%
FAIL stretch   ES2004a                            wder                     7.47% <= 5.00%
FAIL must_pass ES2004a                            wer                     18.87% <= 15.00%
FAIL stretch   ES2004a                            wer                     18.87% <= 12.00%
FAIL must_pass ES2004a                            cer                     16.13% <= 8.00%
FAIL must_pass ES2004a                            der                     31.06% <= 15.00%
FAIL stretch   ES2004a                            der                     31.06% <= 8.00%
FAIL stretch   ES2004a                            rtf                      0.57 <= 0.35
FAIL must_pass IS1009a                            cpwer                   31.70% <= 27.00%
FAIL stretch   IS1009a                            cpwer                   31.70% <= 20.00%
FAIL must_pass IS1009a                            tcpwer                  33.38% <= 30.00%
FAIL stretch   IS1009a                            wder                     8.25% <= 5.00%
FAIL must_pass IS1009a                            wer                     22.66% <= 15.00%
FAIL stretch   IS1009a                            wer                     22.66% <= 12.00%
FAIL must_pass IS1009a                            cer                     18.22% <= 8.00%
FAIL must_pass IS1009a                            der                     25.87% <= 15.00%
FAIL stretch   IS1009a                            der                     25.87% <= 8.00%
FAIL stretch   IS1009a                            rtf                      0.61 <= 0.35
FAIL stretch   TS3003a                            cpwer                   26.25% <= 20.00%
FAIL must_pass TS3003a                            wer                     19.79% <= 15.00%
FAIL stretch   TS3003a                            wer                     19.79% <= 12.00%
FAIL must_pass TS3003a                            cer                     14.73% <= 8.00%
FAIL must_pass TS3003a                            der                     28.74% <= 15.00%
FAIL stretch   TS3003a                            der                     28.74% <= 8.00%
FAIL stretch   TS3003a                            rtf                      0.40 <= 0.35
FAIL stretch   FLEURS en_us (read speech)         wer                      4.47% <= 3.00%
FAIL stretch   FLEURS en_us (read speech)         rtf                      0.49 <= 0.35
FAIL stretch   LibriSpeech dev-clean (read speech) wer                      3.34% <= 3.00%
FAIL stretch   LibriSpeech dev-clean (read speech) rtf                      0.57 <= 0.35
FAIL must_pass 020c_EBPZ                          cpwer                   53.16% <= 30.00%
FAIL stretch   020c_EBPZ                          cpwer                   53.16% <= 22.00%
FAIL must_pass 020c_EBPZ                          tcpwer                  56.52% <= 33.00%
FAIL must_pass 020c_EBPZ                          wder                    17.17% <= 12.00%
FAIL stretch   020c_EBPZ                          wder                    17.17% <= 6.00%
FAIL must_pass 020c_EBPZ                          wer                     37.52% <= 20.00%
FAIL stretch   020c_EBPZ                          wer                     37.52% <= 17.00%
FAIL must_pass 020c_EBPZ                          cer                     28.69% <= 10.00%
FAIL must_pass 020c_EBPZ                          der                     36.22% <= 15.00%
FAIL stretch   020c_EBPZ                          der                     36.22% <= 8.00%
FAIL stretch   020c_EBPZ                          rtf                      0.59 <= 0.35
FAIL stretch   meeting_3spk                       der                      8.64% <= 8.00%
FAIL stretch   meeting_3spk                       rtf                      0.78 <= 0.35
FAIL stretch   meeting_6spk                       der                      9.40% <= 8.00%
FAIL stretch   meeting_6spk                       rtf                      0.81 <= 0.35
FAIL stretch   meeting_9spk                       der                      9.94% <= 8.00%
FAIL stretch   meeting_9spk                       rtf                      0.61 <= 0.35
FAIL stretch   meeting_fr_3spk                    der                     11.88% <= 8.00%
FAIL stretch   meeting_fr_6spk                    der                      8.87% <= 8.00%
FAIL stretch   meeting_fr_9spk                    der                     13.98% <= 8.00%

108/158 gates met  (18 must-pass failures, 32 stretch misses)

Must-pass gates are not met. The work is not finished.
```

**Every one of the eighteen must-pass failures is a real meeting** — twelve on
the three AMI meetings, six on SUMM-RE. That is the open problem of
[§8](#8-where-we-lose), stated by the tooling rather than by us. Nothing on the
synthetic meetings or on read speech blocks a release any more, and
`speaker_count_error` no longer appears at all: the count is within the gate on
every corpus that reaches it, where it was two over on all three AMI meetings
before the diarization retune and six over before the clustering fixes.

Two things changed when float32 became the default, and both show up here as
failures that have disappeared — the command prints only what fails:

- **FLEURS `fr_fr` now passes every gate it has, must-pass and stretch alike**
  — 4.63 % WER against a 6.00 % blocker and a 5.00 % target, 1.62 % CER against
  3.00 %, 0.31 RTF against a 0.35 target. At 6.67 % WER the INT8 profile failed
  both the French blocker and the French target.
- **FLEURS `en_us` CER** (1.99 % against a 2.00 % blocker) also went from failing
  to passing.

The remaining stretch misses are the RTF target of 0.35 — which only French read
speech currently reaches — and DER on the meeting fixtures, at roughly 9 %
against an 8 % target.

**The French meeting gates are exercised now.** The French fixtures are built and
scored by `make bench-meetings` ([§2.2](#22-french-synthetic-meetings)) and their
results reach the checker: `meeting_fr_3spk`, `_6spk` and `_9spk` appear in the
output above, missing only the 8 % DER stretch target. What remains unexercised
is the code-switched set — a gate with no data is a missing measurement, not a
pass; see
[§9](#9-what-we-have-not-measured-yet). French *read speech* is fully gated and
fully passing.

We are not going to lower a threshold to turn a failure into a success. If a
threshold turns out to be wrong, it changes only with published evidence and a
note in this page saying what changed and why.

## Related reading

- [Metrics](metrics.md) — every formula and how it is computed
- [Multilingual](multilingual.md) — the code-switched fixtures, gates and comparison harness
- [Architecture](architecture.md) — what runs where
- [Sovereignty](sovereignty.md) — the other reason to run this
