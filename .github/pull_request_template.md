## What this changes

<!-- One paragraph. Why, not just what — the code carries no comments, so the
     commit history and this description are where the reasoning lives. -->

## Checklist

- [ ] `make check` passes (lint, types, tests)
- [ ] No comments or docstrings added to `src/hansard/` (CI enforces this)
- [ ] Documentation updated in the same pull request
- [ ] Tests added, and they pass offline with no network

## If this touches recognition, diarization or attribution

Paste `make bench` before and after. Numbers from different normalizer
versions or different hardware are not comparable, so include both headers.

| Metric | Before | After |
| --- | ---: | ---: |
| | | |

## If this touches text handling

- [ ] Verified in French and in English
