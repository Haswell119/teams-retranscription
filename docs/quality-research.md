# Quality research log

This file is the laboratory notebook for transcription quality. It records every
experiment that was run against a measurable hypothesis, including the ones that
failed, so that the next engineer does not pay again for an answer we already
bought.

The rules it follows:

- **One hypothesis per iteration**, stated before the run, in a form that a
  benchmark can refute.
- **Before and after on the same corpus**, with the configuration and the commit
  written down.
- **KEEP or REVERT**, decided by the numbers, not by how good the idea sounded.
- **Failures stay on the page.** A dead hypothesis is a result.
- **Tuning and reporting use different audio.** SUMM-RE meetings are split by a
  deterministic hash of the meeting identifier into a `tuning` half and a
  `held-out` half (`hansard.evaluation.corpora.summ_re_split`). Iteration happens
  on `tuning`. Nothing is claimed on the strength of `held-out` numbers until the
  change is frozen.

Related pages: [benchmarks](benchmarks.md) carries the published results,
[metrics](metrics.md) defines what each number means, and
[configuration](configuration.md) documents every setting an experiment can turn.

---

## Hardware for this campaign

Every number below was produced on the machine described here unless the row
says otherwise. It matters, because it bounds which experiments were affordable.

| | |
| --- | --- |
| CPU | 4 vCPU |
| RAM | 15 GB |
| GPU | none |
| Recogniser precision | float32 unless stated |

A GPU would change which recognisers are worth running, not which are worth
wanting. Where a candidate was rejected for cost rather than for quality, the
row says so.

---

## Baseline, before anything in this campaign

Frozen at commit `d65aa57`, the merge point this work branched from.

| Corpus | Meetings | WER | cpWER | WDER | DER (collar 0) |
| --- | ---: | ---: | ---: | ---: | ---: |
| AMI Mix-Headset, told nothing | 3 | 20.44 % | 28.75 % | 6.78 % | 28.56 % |
| AMI Mix-Headset, with a roster | 3 | 20.44 % | 27.34 % | 6.14 % | 27.73 % |
| SUMM-RE `020c_EBPZ` | 1 | 37.52 % | 53.16 % | 17.17 % | 36.22 % |
| Synthetic code-switched meetings | 3 | 10.33 % | 19.21 % | 3.90 % | — |

Read-speech health checks: FLEURS `fr_fr` 4.63 %, FLEURS `en_us` 4.47 %,
LibriSpeech dev-clean 3.34 % word error rate.

The competitive bar, from AssemblyAI's January 2026 benchmark of Azure Speech —
the engine behind Teams transcription — is **27.39 %** cpWER on AMI, **35.68 %**
on NOTSOFAR-1 test and **45.38 %** on NOTSOFAR-1 dev. Those figures come from a
third party using its own reference preparation, so parity with them is
*measured*, not *established*; see
[benchmarks §2.6](benchmarks.md#26-how-this-compares-to-microsoft).

---

## What the corpus actually looks like

Recorded here because two of the experiments below only make sense against it.
Reference speech time per speaker, from the SUMM-RE tuning meetings prepared so
far:

| Meeting | Duration | Speakers | Speech per speaker |
| --- | ---: | ---: | --- |
| `004c_PAPH` | 20.9 min | 4 | 523 s, 297 s, 232 s, 109 s |
| `006b_EADH` | 21.3 min | 4 | 528 s, 487 s, 250 s, 125 s |
| `017a_EBRZ` | 12.4 min | 3 | 149 s, 102 s, 48 s |
| `020c_EBPZ` | 18.2 min | 4 | 380 s, 326 s, 59 s, **12 s** |

`020c_EBPZ` — the only meeting the project had scored before this campaign — is
the *most* skewed of the four, not a typical one. A conclusion drawn from it
alone is a conclusion about a meeting with a twelve-second participant. That is
a real and common case, and it is not the only case, which is exactly why the
corpus was widened before anything was tuned.

---

## Running these experiments yourself

Three commands cover everything in this log. All of them write to
`bench/results/` and none of them publishes a headline number.

```bash
make bench-data-summre SUMM_RE_MEETINGS=8      # tuning split, streamed and deleted shard by shard
make bench-shootout ENGINES=parakeet-fp32,canary-1b-v2-fr SHOOTOUT_SECONDS=1800
make bench-sweep CORPUS=summ-re
```

**The shootout** decodes reference utterance spans — no detector, no padding, no
seams — through every engine named, scores them with one normalizer, and reports
word error split by language, by word category, and by how much of each segment
another participant is talking over. Every hypothesis is written to
`bench/results/transcripts/`, so a change to the reference or the normalizer can
be re-scored in seconds without decoding anything again. That is how iteration 2
below was measured.

**The sweep** runs recognition once per meeting, caches the transcript and the
speech spans, and then re-diarizes and re-attributes those same words for every
point on the grid. A point is written on the command line:

```bash
.venv/bin/python -m hansard.evaluation.run diarization-sweep --corpus summ-re \
  --point "default:" \
  --point "no-gap-fill:min_duration_off=0.0" \
  --point "wespeaker:embedding_model=wespeaker_en_voxceleb_resnet34_LM.onnx"
```

Because the words are identical across points, a difference in cpWER is a
difference in speaker handling and nothing else.

---

## Summary of the campaign so far

| # | Change | Measured on | Result | Decision |
| ---: | --- | --- | --- | --- |
| 0 | Run the code-switched benchmark | 3 fixtures | 19.21 % cpWER, 96.33 % language accuracy | KEEP as baseline |
| 1 | Reference boundaries instead of ours | 7 SUMM-RE meetings | 37.52 % → **30.82 %** WER | Boundaries are worth 7 points, not 25 |
| 2 | Stop scoring SPPAS pause marks as words | same hypotheses | 31.54 % → **30.82 %** | KEEP |
| 3 | Split the errors by overlap | same hypotheses | clean **20.60 %**, heavy **70.54 %** | The finding of the campaign |
| 4 | Canary 1B v2 instead of Parakeet | identical segments | 30.82 % → **38.01 %** | **REVERT** |
| 5 | Run the gates | everything measured | 143/206, 20 must-pass failures | Checkpoint |
| 6 | Unify `ok`/`okay` and `etc` spellings | same hypotheses | 30.82 % → **30.59 %** | KEEP |

## Iterations

Each iteration below states the hypothesis, the smallest experiment that could
refute it, the before and after numbers, and the decision.

### Iteration 0 — reproduce, and fill the empty cell

**Hypothesis.** The published baseline is reproducible on this machine, and the
code-switched benchmark that [benchmarks §9](benchmarks.md#9-what-we-have-not-measured-yet)
lists as unmeasured can simply be run.

**Experiment.** `make bench-mixed` on the three synthetic code-switched fixtures.

**Result.** Reproduced bit-for-bit against the committed run.

| Fixture | Speakers (ref → detected) | WER | cpWER | tcpWER@5s | WDER | Language accuracy |
| --- | :---: | ---: | ---: | ---: | ---: | ---: |
| `meeting_mixed_4spk` | 4 → **4** | 13.83 % | 23.56 % | 24.15 % | 3.55 % | 97.58 % |
| `meeting_mixed_6spk` | 6 → 7 | 4.44 % | 21.62 % | 22.30 % | 7.28 % | 97.79 % |
| `meeting_mixed_8spk` | 8 → **8** | 12.71 % | 12.45 % | 12.45 % | 0.88 % | 93.63 % |
| **macro** | | **10.33 %** | **19.21 %** | 19.63 % | **3.90 %** | **96.33 %** |

**Conclusion.** The cell is no longer empty. Language accuracy is **96.33 %**,
under the 98 % target, and the errors are asymmetric: 105 French words were
labelled English against 41 the other way. That asymmetry is the signature the
brief predicted — French audio decoded into English-looking text, and a
text-based identifier that then believes the text. KEEP as the bilingual
baseline.

---

### Iteration 1 — is the recogniser the problem, or the segmentation in front of it?

**Hypothesis.** [Benchmarks §8](benchmarks.md#8-where-we-lose) leaves boundary
precision as the leading suspect for SUMM-RE, on the evidence that the corpus's
own utterance boundaries reach 26.59 % word error where our segmentation reaches
37.52 %. If boundaries are the dominant term, giving the current recogniser
perfect boundaries should recover most of that gap.

**Experiment.** The new ASR shootout, which decodes reference utterance spans
directly and scores them with the corpus normalizer. Seven SUMM-RE tuning
meetings, 855 segments, 1803 seconds of audio, Parakeet TDT 0.6B v3 in float32,
four threads.

**Result.**

| Condition | Word error | Substitutions | Deletions | Insertions |
| --- | ---: | ---: | ---: | ---: |
| Full pipeline, `020c_EBPZ` only (published) | 37.52 % | — | — | — |
| **Reference boundaries, 7 meetings** | **30.82 %** | 879 | 954 | 369 |

**Conclusion.** Perfect boundaries are worth roughly seven points, and
**thirty-one points remain**. Deletions are 45 % of all errors and the
recogniser returns nothing at all for 66 of 855 reference utterances — 7.7 % of
segments, 259 reference words — with a median duration of 0.79 seconds against
1.38 seconds for the corpus as a whole. Short spontaneous turns are where the
words disappear.

This reframes the project. Segmentation is a real but secondary term; the
recogniser is the primary one. KEEP the finding, and redirect the effort from
boundary work to model work.

---

### Iteration 2 — a pause is not a word

**Hypothesis.** Some of the SUMM-RE word error is a transcription convention
rather than a recognition failure.

**Experiment.** Inspect the raw reference tokens. SUMM-RE follows the SPPAS
convention: `+` for a short pause, `@` for laughter, `*` for an unintelligible
word. The French normalizer already discards `@` and `*` — and expands a bare
`+` into the word **"plus"**.

**Result.** 533 of 33,013 prepared reference tokens are `+`, 1.61 % of the
corpus, each of them an invented reference word that no recogniser can produce.
Stripping the three markers where the corpus is read moves reference-boundary
word error from **31.54 % to 30.82 %** on the same hypotheses, scored again
without re-running the recogniser.

**Conclusion.** KEEP. It is a small correction and it goes the honest way: the
number gets smaller because a defect in our scoring is removed, not because the
system improved. Every SUMM-RE figure in this document is on the corrected
reference.

---

### Iteration 3 — the recogniser is not the bottleneck, the second voice is

**Hypothesis.** Iteration 1 left thirty-one points of word error at perfect
boundaries and blamed the recogniser. Before replacing it, check *which* audio
it fails on. The brief's hypothesis C says a one-stream architecture has a
structural floor in overlapped speech. If that floor is the dominant term, the
errors will concentrate where another participant is talking.

**Experiment.** For every reference utterance, compute the fraction of its
duration covered by *another speaker's* reference speech, from the per-speaker
tracks. Then score the same 855 Parakeet hypotheses split by that fraction.

**Result.**

| Overlap with another speaker | Segments | Reference words | WER | Empty outputs |
| --- | ---: | ---: | ---: | ---: |
| clean, under 5 % | 414 | 3758 | **20.60 %** | 9 |
| light, 5–50 % | 177 | 2154 | 23.35 % | 7 |
| **heavy, over 50 %** | 238 | 1232 | **70.54 %** | **48** |

And the 66 utterances the recogniser returns *nothing* for are covered by
another speaker **84.3 %** of the time, against **31.6 %** for the utterances it
does transcribe. 75.8 % of them are more than half buried; only 13.6 % are
clean, against 49.8 % of the rest.

**Conclusion.** This is the finding of the campaign. On clean French
spontaneous meeting speech Parakeet scores **20.6 %**, which is respectable and
close to the AMI English figure. Heavily overlapped speech is **17 % of the
reference words and 39 % of the errors.** The recogniser is not failing at
French; it is failing at two people at once, and on a single mixed stream it
cannot do otherwise — it transcribes the loud speaker and the quiet one
disappears.

KEEP as the ordering principle for everything that follows: overlap first, model
second. And note what it means for the earlier segmentation work — feeding the
recogniser tighter boundaries cannot recover a word that was never separable
from the voice on top of it.

---

### Iteration 4 — Canary 1B v2 instead of Parakeet

**Hypothesis.** NVIDIA Canary 1B v2 is a larger, newer, CC-BY-4.0 model with an
explicit French decoding token, published as ONNX by the same author as our
Parakeet export and loadable through the `onnx-asr` package the project already
depends on. Its predecessor holds the best published SUMM-RE figure. It should
beat Parakeet on French meeting audio.

**Experiment.** The shootout, on byte-identical segments: 829 SUMM-RE reference
utterances shared by both runs, Canary decoded with `language=fr`, float32,
four threads.

**Result. It is worse everywhere, and there is no band in which it wins.**

| | Parakeet TDT 0.6B v3 | Canary 1B v2 |
| --- | ---: | ---: |
| **Word error, all segments** | **30.82 %** | 38.01 % |
| Substitutions / deletions / insertions | 879 / 954 / 369 | 1190 / 854 / 672 |
| Empty outputs | 66 | 1 |
| clean, under 5 % overlap | **20.60 %** | 27.38 % |
| light, 5–50 % | **23.35 %** | 30.36 % |
| heavy, over 50 % | **70.54 %** | 78.41 % |
| under 1 s | **73.89 %** | 75.41 % |
| 1–3 s | **36.98 %** | 49.77 % |
| 3–6 s | **15.91 %** | 22.04 % |
| over 6 s | **16.68 %** | 18.05 % |
| Peak memory | 3.0 GB | 5.5 GB |

The shape of the failure is worth keeping. Canary almost never stays silent — 1
empty output against Parakeet's 66 — and it pays for that in **672 insertions
against 369** and **1190 substitutions against 879**. On a short, half-buried
turn Parakeet emits nothing and Canary emits something wrong. Fewer deletions,
more invention. For a verbatim record that is the worse trade.

**Conclusion. REVERT.** Canary 1B v2 is not adopted. Read-speech leaderboards
put it comfortably ahead of Parakeet on French (4.83 against 5.42 on the Open
ASR multilingual track) and it loses by seven points on real meeting audio, at
nearly twice the memory and roughly six times the compute. Read-speech rank does
not transfer to meetings — the same lesson INT8 taught this project, arriving
from the other direction.

Recorded so nobody buys it twice.

### Iteration 5 — where the gates actually stand

Not a hypothesis, a checkpoint. `make gates` scores whatever result files exist,
so adding the code-switched run added its gates to the tally for the first time.

```
143/206 gates met  (20 must-pass failures, 43 stretch misses)
```

The must-pass failures worth naming:

| Gate | Measured | Required |
| --- | ---: | ---: |
| `meeting_mixed_8spk` language accuracy | **0.94** | ≥ 0.95 |
| `meeting_mixed_4spk` CER | 10.39 % | ≤ 10.00 % |
| `020c_EBPZ` cpWER | 53.16 % | ≤ 30.00 % |
| `020c_EBPZ` WER | 37.52 % | ≤ 20.00 % |
| `020c_EBPZ` WDER | 17.17 % | ≤ 12.00 % |
| `020c_EBPZ` DER | 36.22 % | ≤ 15.00 % |

The bilingual language-accuracy gate is a **new** must-pass failure, and it is
new only because nobody had run the benchmark. That is the argument for running
benchmarks you expect to fail.

The real-time-factor stretch gates fail across the board at 0.35 and are ignored
for this campaign by instruction: quality first, speed later.

### Iteration 6 — what the French errors actually are

**Hypothesis.** Word error is a number, not a diagnosis. Before spending
anything on French, look at which words are wrong.

**Experiment.** Align every Parakeet hypothesis against its reference on the
seven tuning meetings and count the individual substitutions, deletions and
insertions.

**Result.** Two findings, one a defect in our scoring and one a defect in the
system.

*The backchannels are being translated.* The most frequent substitutions are not
mishearings, they are language switches on single words:

| Reference | Produced | Count |
| --- | --- | ---: |
| `ouais` | `well` / `right` / `yeah` / `what` | 21 |
| `non` | `no` | 7 |
| `oui` | `yeah` / `right` | 5 |
| `et` | `yeah` | 4 |
| `voilà` | `no` | 3 |

A monosyllabic French backchannel carries almost no acoustic evidence of which
language it belongs to, and the recognizer resolves the ambiguity towards
English. This is the same failure the code-switched run measures as 105 French
words labelled English, arriving through word error instead of through language
accuracy — and it is worth about 0.6 points here.

*And `ok` was scoring as an error against `okay`.* Ten substitutions, plus three
for `et cetera` against `etcetera`, were one word written two ways. The
normalizer now unifies both spellings in French, in English and in the mixed
path, which moves reference-boundary word error from **30.82 % to 30.59 %** on
unchanged hypotheses. Normalizer version `hansard-normalizers-1.3.0`.

*The deletions are function words and elisions.* `est` (56), `ouais` (39), `c`
(32), `le` (29), `ça` (29), `je` (18). Not names, not numbers, not jargon — the
unstressed glue of spoken French, which is exactly what disappears first under
another speaker's voice.

**Conclusion.** KEEP the normalizer fix. KEEP the backchannel finding as the
first concrete demonstration that the bilingual defect costs words and not only
labels.

### Iteration 7 — one meeting was an anecdote, and it was the flattering one

**Hypothesis.** The published SUMM-RE figure comes from a single meeting. Four
meetings will say something different.

**Experiment.** The diarization sweep at the shipped defaults, on four SUMM-RE
tuning meetings, scoring one cached recognition pass per meeting.

**Result.**

| Meeting | Speakers (ref → detected) | cpWER | WDER | DER | missed | false alarm | confusion |
| --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `004c_PAPH` | 4 → 6 | 56.11 % | 10.49 % | 36.38 % | 5.0 % | 18.9 % | 12.5 % |
| `006b_EADH` | 4 → 5 | **85.80 %** | 17.06 % | 41.82 % | 6.0 % | 23.2 % | 12.7 % |
| `017a_EBRZ` | 3 → 5 | 61.66 % | 8.62 % | 54.64 % | 5.8 % | 29.7 % | 19.1 % |
| `020c_EBPZ` | 4 → **4** | **49.18 %** | 12.97 % | 34.92 % | 4.0 % | 18.1 % | 12.9 % |
| **macro** | | **63.19 %** | 12.28 % | 41.94 % | 5.2 % | 22.5 % | 14.3 % |

**Conclusion.** Two things, and neither is comfortable.

`020c_EBPZ` scores **49.18 %** here against the published **53.16 %** — the
corrected reference and normalizer 1.3.0 are worth four points, as
[iterations 2](#iteration-2--a-pause-is-not-a-word) and
[6](#iteration-6--what-the-french-errors-actually-are) predicted. That is the
honest current figure for that meeting.

And `020c_EBPZ` is the **best** of the four. The macro average across four
meetings is **63.19 %**, fourteen points worse, because it is the only one of the
four where the speaker count comes out right. `006b_EADH` at 85.80 % is a
different order of failure. The project has been reasoning about French meetings
from its most flattering sample. KEEP the wider corpus as the reporting unit;
`020c_EBPZ` alone is retired as a headline.

---

### Iteration 8 — a better speaker embedding, and a gap-filler worth removing

**Hypothesis.** Three separate ideas, each with published support behind it.
TitaNet-small is the weakest embedding in its family (1.15 % EER against 0.72 %
for WeSpeaker ResNet34-LM); `min_duration_off = 0.4` fills same-speaker gaps and
against a word-aligned reference that manufactures false alarm, which is 22.5 %
of our DER; and the ten-second absorption floor is what removes phantom speakers,
so it should be worth its cost.

**Experiment.** Seven points over the same four meetings and the same cached
words, so any difference is speaker handling alone.

**Result.**

| Point | cpWER | WDER | DER | false alarm | speaker-count error | quiet-speaker recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **default** | **63.19 %** | **12.28 %** | 41.94 % | 22.46 % | 1.25 | 100 % |
| `min_duration_off=0.0` | 63.24 % | 12.15 % | **41.01 %** | **21.40 %** | 1.50 | 87.5 % |
| `minimum_speaker_seconds=0` | 63.70 % | 12.76 % | 42.96 % | 22.92 % | **10.75** | 100 % |
| TitaNet-large | 66.59 % | 20.96 % | 47.30 % | 20.33 % | 1.25 | 100 % |
| ERes2Net | 67.11 % | 14.77 % | 44.58 % | 22.12 % | 1.50 | 87.5 % |
| WeSpeaker ResNet34-LM | 90.50 % | 45.17 % | 65.40 % | 18.38 % | 2.25 | 50 % |
| CAM++ | 96.59 % | 54.44 % | 72.19 % | 20.32 % | 2.00 | 50 % |

**Conclusion. REVERT all three, and read the last two rows carefully.**

*Removing the gap filler is noise.* False alarm does fall, 22.46 % → 21.40 %, and
DER with it — and cpWER does not move at all (63.19 → 63.24). The false alarm was
real and it was not costing us words. Dead hypothesis, recorded.

*The absorption floor earns its place.* Setting it to zero takes the speaker-count
error from 1.25 to **10.75** — eighteen clusters where there are four speakers —
while quiet-speaker recall stays at 100 % either way. The floor is not what
threatens quiet participants here, and the gated absorption shipped alongside it
is what makes sure it never will be.

*The embedding swaps were run at TitaNet's thresholds, and that is a flaw in the
experiment, not a verdict on the models.* `clustering_threshold = 0.99` and
`merge_similarity = 0.77` were calibrated in TitaNet's cosine geometry, which
[configuration](configuration.md#tuning-clustering_threshold-by-symptom) already
warns does not transfer. WeSpeaker and CAM++ collapse four speakers into one or
two, which is the signature of a merge threshold that is far too low for their
similarity distribution, not of a bad embedding. The follow-up — a merge-threshold
grid inside each embedding space, which now costs one clustering pass per
embedding rather than one per threshold — is the honest version of this test.

---

## Dead hypotheses inherited from earlier work

These were measured before this campaign and are **not** worth re-running
without new evidence. Detail in
[benchmarks §8](benchmarks.md#8-where-we-lose).

| Hypothesis | How it died |
| --- | --- |
| SUMM-RE segments mix speakers | Single-speaker spans scored *worse* than mixed-speaker spans |
| SUMM-RE segments are too long | 120 s → 20 s → 8 s moved word error under two points; the oracle boundaries are worth eleven |
| Too much silence reaches the recogniser | Not monotone: adding silence helped twice |
| The segment overlap and seam mechanism | Removing it entirely was worth ±0.7 points, which is noise |
| Voice activity detection drops the missing words | Silero already hands the recogniser 96–99 % of reference words |
| INT8 weights are a free win | They delete words wholesale on real meeting audio: 386 → 1210 deletions on ES2004a |
