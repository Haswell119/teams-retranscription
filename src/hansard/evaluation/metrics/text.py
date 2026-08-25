from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import jiwer

from hansard.evaluation.normalizers import TextNormalizer


@dataclass(frozen=True, slots=True)
class ErrorCounts:
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0
    hits: int = 0
    reference_units: int = 0

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def rate(self) -> float:
        return self.errors / max(self.reference_units, 1)

    def __add__(self, other: ErrorCounts) -> ErrorCounts:
        return ErrorCounts(
            substitutions=self.substitutions + other.substitutions,
            deletions=self.deletions + other.deletions,
            insertions=self.insertions + other.insertions,
            hits=self.hits + other.hits,
            reference_units=self.reference_units + other.reference_units,
        )


@dataclass(frozen=True, slots=True)
class WerResult:
    wer: float
    cer: float
    substitutions: int
    deletions: int
    insertions: int
    hits: int
    reference_words: int


def word_error_counts(reference: str, hypothesis: str) -> ErrorCounts:
    reference_tokens = reference.split()
    hypothesis_tokens = hypothesis.split()
    if not reference_tokens:
        return ErrorCounts(insertions=len(hypothesis_tokens))
    if not hypothesis_tokens:
        return ErrorCounts(deletions=len(reference_tokens), reference_units=len(reference_tokens))
    output = jiwer.process_words(reference, hypothesis)
    return ErrorCounts(
        substitutions=int(output.substitutions),
        deletions=int(output.deletions),
        insertions=int(output.insertions),
        hits=int(output.hits),
        reference_units=int(output.substitutions + output.deletions + output.hits),
    )


def character_error_counts(reference: str, hypothesis: str) -> ErrorCounts:
    if not reference:
        return ErrorCounts(insertions=len(hypothesis))
    if not hypothesis:
        return ErrorCounts(deletions=len(reference), reference_units=len(reference))
    output = jiwer.process_characters(reference, hypothesis)
    return ErrorCounts(
        substitutions=int(output.substitutions),
        deletions=int(output.deletions),
        insertions=int(output.insertions),
        hits=int(output.hits),
        reference_units=int(output.substitutions + output.deletions + output.hits),
    )


def aligned_word_pairs(reference: str, hypothesis: str) -> tuple[tuple[int, int], ...]:
    if not reference.split() or not hypothesis.split():
        return ()
    output = jiwer.process_words(reference, hypothesis)
    pairs: list[tuple[int, int]] = []
    for chunk in output.alignments[0]:
        if chunk.type != "equal":
            continue
        span = range(int(chunk.ref_start_idx), int(chunk.ref_end_idx))
        offset = int(chunk.hyp_start_idx) - int(chunk.ref_start_idx)
        pairs.extend((index, index + offset) for index in span)
    return tuple(pairs)


def normalized_pairs(
    references: str | Sequence[str],
    hypotheses: str | Sequence[str],
    normalizer: TextNormalizer | None = None,
) -> tuple[tuple[str, str], ...]:
    reference_list = _as_list(references)
    hypothesis_list = _as_list(hypotheses)
    if len(reference_list) != len(hypothesis_list):
        raise ValueError(
            f"reference/hypothesis count mismatch: {len(reference_list)} != {len(hypothesis_list)}"
        )
    if normalizer is None:
        return tuple(zip(reference_list, hypothesis_list, strict=True))
    return tuple(
        (normalizer.normalize(reference), normalizer.normalize(hypothesis))
        for reference, hypothesis in zip(reference_list, hypothesis_list, strict=True)
    )


def word_error_rate(
    references: str | Sequence[str],
    hypotheses: str | Sequence[str],
    normalizer: TextNormalizer | None = None,
) -> WerResult:
    pairs = normalized_pairs(references, hypotheses, normalizer)
    words = ErrorCounts()
    characters = ErrorCounts()
    for reference, hypothesis in pairs:
        words = words + word_error_counts(reference, hypothesis)
        characters = characters + character_error_counts(reference, hypothesis)
    return WerResult(
        wer=words.rate,
        cer=characters.rate,
        substitutions=words.substitutions,
        deletions=words.deletions,
        insertions=words.insertions,
        hits=words.hits,
        reference_words=words.reference_units,
    )


def character_error_rate(
    references: str | Sequence[str],
    hypotheses: str | Sequence[str],
    normalizer: TextNormalizer | None = None,
) -> float:
    counts = ErrorCounts()
    for reference, hypothesis in normalized_pairs(references, hypotheses, normalizer):
        counts = counts + character_error_counts(reference, hypothesis)
    return counts.rate


def _as_list(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        return [value]
    return list(value)
