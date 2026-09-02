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
