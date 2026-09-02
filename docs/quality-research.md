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
[benchmarks §2.5](benchmarks.md#25-how-this-compares-to-microsoft).

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

<!-- ITERATIONS -->

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
