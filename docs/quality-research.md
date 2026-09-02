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
| 7 | Score four meetings instead of one | 4 SUMM-RE meetings | 020c is the best of four; macro **63.19 %** | Retire the single-meeting headline |
| 8 | Remove the gap filler / drop the absorption floor / swap the embedding | same words | none beat the default | **REVERT** all three |
| 9 | Merge threshold per embedding space | same words | apparent 1.5-point win; found a regression I shipped | Superseded by 11 |
| 10 | Gate absorption on voice similarity | same words | no gate value restores speaker counts; ordering was the cause | **REVERT** |
| 11 | Merge threshold, re-measured after the revert | same words | 0.72 worth 0.17 points, and costs a quiet speaker | **No change** |
| 12 | Score eight meetings end to end | 8 SUMM-RE meetings | macro **71.92 %** cpWER, **57.49 %** WER | The honest French figure |

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

### Iteration 9 — the merge threshold moves, and my own change did not

**Hypothesis.** Two things at once. Iteration 8 ran the alternative embeddings at
TitaNet's thresholds, which was not a fair test; each embedding space needs its
own merge threshold. And the shipped `merge_similarity = 0.77` was tuned when
`020c_EBPZ` was the only meeting, so it may be wrong for the other three.

**Experiment.** A merge-threshold grid inside each embedding space, on the same
four meetings and the same cached words. With clustering shared across every
point that agrees on the diarizer settings, four embeddings cost four clustering
passes rather than eleven.

**Result.**

| Point | cpWER | WDER | DER | speaker-count error | speakers detected |
| --- | ---: | ---: | ---: | ---: | --- |
| **TitaNet-small, merge 0.72** | **61.91 %** | 13.99 % | **40.17 %** | 6.75 | 14/4 10/4 13/3 5/4 |
| TitaNet-small, merge 0.77 | 63.37 % | 12.55 % | 42.23 % | 8.00 | 14/4 12/4 15/3 6/4 |
| TitaNet-small, merge 0.82 | 63.37 % | 12.48 % | 42.54 % | 8.25 | 14/4 13/4 15/3 6/4 |
| TitaNet-small, merge 0.68 | 63.73 % | 20.61 % | 45.57 % | 6.00 | 12/4 9/4 13/3 5/4 |
| TitaNet-large, merge 0.82 | 66.31 % | 14.89 % | 43.67 % | 12.75 | 17/4 11/4 23/3 15/4 |
| ERes2Net, merge 0.86 | 67.74 % | 15.91 % | 45.08 % | 9.75 | 13/4 10/4 19/3 12/4 |
| WeSpeaker, merge 0.86 / 0.91 / 0.95 | 88.34 % | 38.51 % | 60.86 % | 1.50 | 3/4 4/4 1/3 1/4 |

**Conclusion, in three parts, and the middle one is about a defect I introduced.**

*The merge threshold does move, and 0.77 is not the best value on four meetings.*
0.72 is worth **1.5 points of cpWER** and two points of DER over 0.77. Not yet
adopted: it is one grid on the tuning split and it changes a default that
[configuration](configuration.md#minimum_speaker_seconds-and-merge_similarity-the-pair-that-was-retuned)
records as already retuned once. It gets re-measured on the held-out split before
anything moves.

*WeSpeaker's collapse is not a merge-threshold problem.* It scores **identically
at 0.86, 0.91 and 0.95** — the three points are the same number to two decimals —
which means consolidation is not what is collapsing it. Four speakers are already
down to 3, 4, 1 and 1 clusters before consolidation runs, so the collapse happens
inside sherpa-onnx's own clustering at `clustering_threshold = 0.99`. That is a
diarizer setting, so fixing it costs a clustering pass per value rather than a
free consolidation, and TitaNet-small at 0.72 is ahead of anything WeSpeaker
reached. Recorded as untested rather than as a verdict.

*And the cluster counts exposed a regression I had shipped.* Compare the speaker
counts against [iteration 8](#iteration-8--a-better-speaker-embedding-and-a-gap-filler-worth-removing):
6/4, 5/4, 5/3, 4/4 there, **14/4, 12/4, 15/3, 6/4** here, at the same merge
threshold. The difference is the gated absorption from
[the quiet-speaker change](#iteration-8--a-better-speaker-embedding-and-a-gap-filler-worth-removing) —
moving the floor from the diarizer, where it absorbed unconditionally into the
nearest neighbour in time, to the consolidator, where it now requires a cosine
similarity of 0.55 first. TitaNet-small's embeddings on short spontaneous
segments are not confident enough to clear that bar, so most of the phantom
clusters the floor used to remove now survive. cpWER barely notices (63.19 →
63.37) but speaker-count error goes from 1.25 to 8.00, and speaker count is
exactly what a roster has to match.

**REVERTED.** The gate was measured against 0.0, 0.25 and 0.40, and it turned out
not to be the gate at all:

| Absorption gate, at merge 0.72 | cpWER | speaker-count error | speakers detected |
| --- | ---: | ---: | --- |
| 0.00 | 61.86 % | **4.75** | 12/4 8/4 9/3 5/4 |
| 0.25 | 61.86 % | 5.00 | 12/4 8/4 10/3 5/4 |
| 0.40 | 61.85 % | 5.75 | 13/4 9/4 11/3 5/4 |

The three values are the same number to two decimals, and **even at 0.0 — absorb
whenever similarity is not negative, which is always — the speaker counts do not
come back**. The original absorbed in the diarizer, on raw clusters, *before*
agglomeration; mine absorbs in the consolidator, on merged groups, *after* it. A
group that has already swallowed three phantoms is no longer under the
ten-second floor, so the floor stops seeing anything to remove. The gate was
never the problem — the ordering was.

The change is reverted in full: the floor goes back to the diarizer,
`absorption_similarity` is gone, and the tests and documentation go with it. The
protection it was built for cannot be demonstrated on this corpus — quiet-speaker
recall is **100 % with and without it** — and shipping a change that costs
speaker counting to defend against a failure nobody can produce is exactly what
this log exists to prevent.

What survives: `min_duration_on` and `min_duration_off` are still configuration,
because being able to turn them was what killed the false-alarm hypothesis.

### Iteration 11 — the merge threshold, measured again on code that works

**Hypothesis.** [Iteration 9](#iteration-9--the-merge-threshold-moves-and-my-own-change-did-not)
found `merge_similarity = 0.72` worth 1.5 points of cpWER over the shipped 0.77.
That grid ran on code carrying the absorption regression. Re-measure it on the
reverted code before adopting anything.

**Experiment.** The same five-point grid, the same four meetings, the same cached
words, on `HEAD` after the revert.

**Result.** The revert reproduces the original behaviour exactly — 6/4, 5/4, 5/3,
4/4 speakers at 0.77, and 63.06 % cpWER against iteration 8's 63.19 %, the
difference being normalizer 1.3.0. And the gain evaporates:

| `merge_similarity` | cpWER | WDER | DER | speaker-count error | quiet-speaker recall | speakers |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0.68 | 63.79 % | 21.05 % | 45.89 % | 1.00 | 87.5 % | 3/4 2/4 3/3 3/4 |
| 0.72 | **62.89 %** | **12.12 %** | **41.35 %** | 1.00 | **87.5 %** | 5/4 5/4 4/3 **3/4** |
| 0.75 | 62.89 % | 12.12 % | 41.35 % | 1.25 | 87.5 % | 5/4 5/4 5/3 3/4 |
| **0.77 (shipped)** | 63.06 % | 12.25 % | 41.94 % | 1.25 | **100 %** | 6/4 5/4 5/3 **4/4** |
| 0.80 | 63.11 % | 12.14 % | 42.14 % | 1.50 | 100 % | 6/4 6/4 5/3 4/4 |

**Conclusion. No change.** 0.72 is worth **0.17 points**, not 1.5 — the 1.5 was
an artefact of the regression it was measured against. And it buys those
0.17 points by collapsing `020c_EBPZ` from four speakers to three, taking
quiet-speaker recall from 100 % to 87.5 %. That is the same failure
[configuration](configuration.md#minimum_speaker_seconds-and-merge_similarity-the-pair-that-was-retuned)
records at 0.70, arriving three hundredths earlier than expected. `0.77` stays.

**The diarization exploration ends here with nothing adopted.** Seven
configurations, four embedding models, five merge thresholds and four absorption
gates, all measured on identical words, and not one of them beats the shipped
default by more than noise. That is a result: the diarization defaults are not
where the remaining French error lives, and
[the roadmap](#what-to-do-next-in-the-order-the-evidence-supports) says where it
does.

### Iteration 12 — eight real French meetings, and the number is much worse

**Hypothesis.** Eight meetings will give a French figure that can be published
without a straight face problem. It will be worse than the single-meeting 53.16 %.

**Experiment.** The full pipeline, unchanged defaults, on all eight SUMM-RE
tuning meetings — 151.9 minutes of real French meeting audio.

**Result.**

| Meeting | Duration | Speakers | Words ref → produced | WER | **cpWER** | WDER | DER | Reference overlap |
| --- | ---: | :---: | :---: | ---: | ---: | ---: | ---: | ---: |
| `020c_EBPZ` | 18.2 min | 4 → **4** | 3376 → 2369 | **36.36 %** | **51.99 %** | 17.03 % | 32.28 % | 5.04 % |
| `004c_PAPH` | 21.1 min | 4 → 7 | 4110 → 2332 | 47.55 % | 56.92 % | 11.22 % | 36.02 % | 10.97 % |
| `021a_EARD` | 18.8 min | 4 → 6 | 3751 → 2125 | 49.67 % | 52.96 % | 6.88 % | 26.18 % | 9.55 % |
| `017a_EBRZ` | 12.5 min | 3 → 4 | 1131 → 718 | 52.19 % | 59.07 % | 5.32 % | 44.62 % | 8.06 % |
| `018b_EADZ` | 19.4 min | 4 → **4** | 4377 → 1884 | 66.33 % | 71.60 % | 13.60 % | 35.15 % | 12.57 % |
| `033c_EBPH` | 20.7 min | 4 → 3 | 5472 → 1935 | 72.25 % | **100.86 %** | 65.69 % | 73.30 % | **21.83 %** |
| `006b_EADH` | 21.4 min | 4 → **4** | 6462 → 1586 | **83.05 %** | 89.79 % | 40.97 % | 58.58 % | **18.89 %** |
| `035b_EADH` | 19.8 min | 4 → 2 | 4402 → 2338 | 52.55 % | 92.19 % | 52.52 % | 68.57 % | 12.57 % |
| **macro** | 151.9 min | | | **57.49 %** | **71.92 %** | **26.65 %** | **46.84 %** | 12.43 % |

**Conclusion.** The published 53.16 % was a figure for the easiest meeting in the
corpus. The honest eight-meeting number is **71.92 % cpWER and 57.49 % WER**, and
`020c_EBPZ` is the best row in the table by fourteen points.

Order the rows by reference overlap and the table sorts itself: 5.0 % overlap →
51.99 % cpWER, 21.8 % overlap → 100.86 %. The two worst meetings are the two most
overlapped, which is [iteration 3](#iteration-3--the-recogniser-is-not-the-bottleneck-the-second-voice-is)
arriving end to end instead of on reference boundaries.

**And one row does not fit that story, which is the useful part.** `006b_EADH`
detects its four speakers correctly and still scores 83.05 % word error, producing
**1586 of 6462 reference words — a quarter**. Its reference contains **1377
seconds of speech inside a 1281-second meeting**, because the reference is the sum
of four per-speaker tracks and they overlap. To the voice-activity detector that
is one continuous 21-minute utterance: it hands the recognizer **45 segments**
where the same pipeline gives `020c_EBPZ` 108, and a 120-second span of four
people talking over each other is not something a one-stream recognizer can
transcribe.

That points at a default this project has already tested and retired.
[Benchmarks §8](benchmarks.md#8-where-we-lose) records that changing
`audio.max_segment_seconds` from 120 s to 20 s to 8 s was worth under two points
— but that was measured on `020c_EBPZ`, which has 777 seconds of speech in 1094
seconds of audio and is the *sparsest* meeting in the corpus. A dead hypothesis
tested on one meeting is a dead hypothesis about one meeting. It is being
re-measured on a dense one.

---

## What to do next, in the order the evidence supports

Written down because the ordering changed twice during this campaign and the
reasons are worth keeping.

**1. Overlapped speech, and nothing else, is the French meeting problem.**
Seventeen percent of the reference words, thirty-nine percent of the errors, and
a recognizer that returns silence for utterances buried under another voice
84.3 % of the time. Every other lever measured here is worth one to seven points;
this one is worth the difference between 20.60 % and 70.54 %.

The honest position is that we cannot afford the fix on this hardware. Every
credible single-channel separator for meetings — the NOTSOFAR-1 baseline's
Conformer CSS, TF-GridNet, MossFormer2, SepFormer — costs one to two orders of
magnitude more compute than this entire pipeline, and NOTSOFAR's own baseline
then runs three parallel ASR decodes on the separated streams. On 4 vCPU with no
GPU that is not a tuning exercise, it is a different machine. **The first thing
to do with a GPU is measure a separation front-end**, and the harness is ready
for it: the shootout already reports word error per overlap band, so the question
"did separation help where it was supposed to?" has a one-command answer.

Two cheaper things are worth trying first, and neither needs a GPU:

- **Teams already tells us who is overlapping.** The browser instrumentation
  polls `getContributingSources()` on the WebRTC receivers, so during overlap we
  know *which participants* are contributing even though the audio arrives
  pre-mixed. That cannot recover a lost word, but it is a strong prior for
  attribution and speaker counting that no open corpus benchmark can measure and
  that AMI and SUMM-RE therefore under-state.
- **Overlap-aware output.** The pyannote segmentation model already emits
  powerset labels with up to two concurrent speakers; sherpa-onnx collapses them
  to one. Surfacing the overlap mask would at minimum let the transcript say "two
  people are talking here" instead of silently dropping one, and would let
  attribution stop charging an overlapped word to a single speaker.

**2. Speaker over-detection, not quiet speakers, is the diarization problem.**
Four, five and six clusters where there are three or four people
([iteration 7](#iteration-7--one-meeting-was-an-anecdote-and-it-was-the-flattering-one)),
and cpWER charges for every fragment. Quiet-speaker recall is already 100 % on
these four meetings. The merge threshold is the lever and it is corpus-sensitive:
0.70 collapsed speakers on `020c_EBPZ`, 0.77 over-splits three other meetings.
A per-meeting decision — eigengap on the similarity matrix, or the constrained
reassignment pyannote's community-1 back-end uses — is the principled version of
what is currently one global constant.

**3. Language identification should come from the audio.** 105 French words
labelled English against 41 the other way, and the same defect shows up in word
error as `ouais` produced as `well`, `right` or `yeah` twenty-one times. Text-based
identification reads our own transcript, so the recognition error and the language
error confirm each other. Note the bound on what this costs today: Parakeet has no
language token, so a wrong label changes what the transcript says about itself and
not which words it contains. That makes this a correctness-of-metadata problem
rather than a word-error problem — which is why it sits below the first two.

**4. What is not worth doing.** Replacing the recognizer, on the evidence here.
Parakeet at 20.60 % on clean French spontaneous speech is not the bottleneck, and
the one larger, newer, better-ranked candidate measured seven points worse. A
French-specialised model — LinTO's FastConformer is the only open model trained
on French meeting and telephone corpora — is worth a shootout run if somebody
exports it to ONNX, but it should be expected to move the clean band, which is
already the good one.

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
