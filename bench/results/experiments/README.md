# Diagnostic runs

Nothing in this directory is a published result. The quality gates
(`hansard.evaluation.check`) glob only the top level of `bench/results/`, so a
file here is a measurement kept for the record, not a claim about how Hansard
performs. Every one of them is explained in `docs/quality-research.md`.

## Runs measured under a sweep that did not reproduce production

`diarization_sweep_summre_clean.json` and `diarization_sweep_ami_clean.json`
were produced before commit `553487d`. Until then the sweep clustered on the raw
clip while production clusters on the high-pass-filtered diarization clip, so the
speaker counts and the confusion figures in those two files describe a pipeline
Hansard does not run. They are kept because iteration 15 of the research log is
about being misled by them; do not read a decision out of them.

`overlap_mask_summre.json` is a frame-level diagnostic, not a transcription run: it scores the segmentation model's powerset overlap mask against the reference and carries no word error at all. Iteration 16 explains what it does and does not establish.

The other sweep files (`diarization_sweep_summre.json`, `_merge`, `_absorption`,
`_thresholds`) predate the clean-sample work and compare consolidation settings
against each other under the same bug, which is why every conclusion drawn from
them was re-measured end to end before it was believed.
