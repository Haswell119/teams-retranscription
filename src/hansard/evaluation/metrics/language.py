from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.language import normalise_tag
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance


@dataclass(frozen=True, slots=True)
class LanguageIdentificationResult:
    matched_words: int
    scored_words: int
    unlabelled_words: int
    confusions: tuple[tuple[str, str, int], ...]

    @property
    def accuracy(self) -> float:
        return self.matched_words / self.scored_words if self.scored_words else 1.0

    @property
    def error_rate(self) -> float:
        return 1.0 - self.accuracy


def _overlap(left: TimeSpan, right: TimeSpan) -> float:
    return max(0.0, min(left.end, right.end) - max(left.start, right.start))


def reference_language_at(reference: Transcript, span: TimeSpan) -> str | None:
    best: tuple[float, str] | None = None
    for utterance in reference.utterances:
        tag = normalise_tag(utterance.language)
        if tag is None:
            continue
        shared = _overlap(utterance.span, span)
        if shared <= 0.0:
            continue
        if best is None or shared > best[0]:
            best = (shared, tag)
    return best[1] if best is not None else None


def _weight(utterance: Utterance) -> int:
    return max(1, utterance.word_count)


def language_identification(
    hypothesis: Transcript,
    reference: Transcript,
) -> LanguageIdentificationResult:
    matched = 0
    scored = 0
    unlabelled = 0
    confusions: dict[tuple[str, str], int] = {}
    for utterance in hypothesis.utterances:
        expected = reference_language_at(reference, utterance.span)
        if expected is None:
            continue
        weight = _weight(utterance)
        observed = normalise_tag(utterance.language)
        if observed is None:
            unlabelled += weight
            scored += weight
            continue
        scored += weight
        if observed == expected:
            matched += weight
        else:
            key = (expected, observed)
            confusions[key] = confusions.get(key, 0) + weight
    ranked = sorted(confusions.items(), key=lambda item: (-item[1], item[0]))
    return LanguageIdentificationResult(
        matched_words=matched,
        scored_words=scored,
        unlabelled_words=unlabelled,
        confusions=tuple((expected, observed, count) for (expected, observed), count in ranked),
    )
