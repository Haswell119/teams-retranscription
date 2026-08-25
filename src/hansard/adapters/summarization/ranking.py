from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from hansard.adapters.summarization.citations import SentenceUnit
from hansard.adapters.summarization.text import content_terms, jaccard
from hansard.adapters.summarization.topics import TopicSegment

DAMPING = 0.85
MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1.0e-6
MINIMUM_SUMMARY_WORDS = 6
DUPLICATE_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class RankedSentence:
    unit: SentenceUnit
    score: float
    terms: frozenset[str]

    @property
    def word_count(self) -> int:
        return len(self.unit.text.split())


def _term_sets(units: Sequence[SentenceUnit], language: str) -> tuple[frozenset[str], ...]:
    return tuple(frozenset(content_terms(unit.text, language)) for unit in units)


def similarity_matrix(term_sets: Sequence[frozenset[str]]) -> np.ndarray:
    size = len(term_sets)
    matrix = np.zeros((size, size), dtype=np.float64)
    lengths = [len(terms) for terms in term_sets]
    for row in range(size):
        if lengths[row] < 2:
            continue
        for column in range(row + 1, size):
            if lengths[column] < 2:
                continue
            shared = len(term_sets[row] & term_sets[column])
            if not shared:
                continue
            denominator = math.log(lengths[row]) + math.log(lengths[column])
            if denominator <= 0.0:
                continue
            weight = shared / denominator
            matrix[row, column] = weight
            matrix[column, row] = weight
    return matrix


def pagerank(
    matrix: np.ndarray,
    damping: float = DAMPING,
    iterations: int = MAX_ITERATIONS,
    tolerance: float = CONVERGENCE_TOLERANCE,
) -> np.ndarray:
    size = matrix.shape[0]
    if size == 0:
        return np.zeros(0, dtype=np.float64)
    totals = matrix.sum(axis=1)
    transition = np.divide(matrix, totals[:, None], out=np.zeros_like(matrix), where=totals[:, None] > 0.0)
    dangling = totals <= 0.0
    scores = np.full(size, 1.0 / size, dtype=np.float64)
    teleport = (1.0 - damping) / size
    for _ in range(iterations):
        redistributed = damping * float(scores[dangling].sum()) / size
        updated = teleport + redistributed + damping * (transition.T @ scores)
        if float(np.abs(updated - scores).sum()) < tolerance:
            return updated
        scores = updated
    return scores


def rank_sentences(units: Sequence[SentenceUnit], language: str) -> tuple[RankedSentence, ...]:
    term_sets = _term_sets(units, language)
    scores = pagerank(similarity_matrix(term_sets))
    return tuple(
        RankedSentence(unit=unit, score=float(score), terms=terms)
        for unit, score, terms in zip(units, scores, term_sets, strict=True)
    )


def is_summary_candidate(sentence: RankedSentence, minimum_words: int = MINIMUM_SUMMARY_WORDS) -> bool:
    return (
        sentence.word_count >= minimum_words
        and len(sentence.terms) >= 2
        and not sentence.unit.is_question
    )


def _is_novel(sentence: RankedSentence, selected: Sequence[RankedSentence], threshold: float) -> bool:
    return all(jaccard(sentence.terms, other.terms) < threshold for other in selected)


def _segment_of(sentence: RankedSentence, segments: Sequence[TopicSegment]) -> int:
    for segment in segments:
        if segment.first_utterance <= sentence.unit.utterance_index <= segment.last_utterance:
            return segment.index
    return -1


def select_summary_sentences(
    sentences: Sequence[RankedSentence],
    segments: Sequence[TopicSegment],
    limit: int,
    minimum_words: int = MINIMUM_SUMMARY_WORDS,
    duplicate_threshold: float = DUPLICATE_THRESHOLD,
) -> tuple[RankedSentence, ...]:
    candidates = [sentence for sentence in sentences if is_summary_candidate(sentence, minimum_words)]
    if not candidates:
        candidates = [sentence for sentence in sentences if sentence.terms]
    if not candidates:
        return ()
    ordered = sorted(candidates, key=lambda sentence: (-sentence.score, sentence.unit.index))
    selected: list[RankedSentence] = []
    for segment in segments:
        if len(selected) >= limit:
            break
        for sentence in ordered:
            if _segment_of(sentence, segments) != segment.index:
                continue
            if _is_novel(sentence, selected, duplicate_threshold):
                selected.append(sentence)
                break
    for sentence in ordered:
        if len(selected) >= limit:
            break
        if sentence not in selected and _is_novel(sentence, selected, duplicate_threshold):
            selected.append(sentence)
    return tuple(sorted(selected, key=lambda sentence: sentence.unit.index))


def sentences_in_segment(
    sentences: Sequence[RankedSentence],
    segment: TopicSegment,
) -> tuple[RankedSentence, ...]:
    return tuple(
        sentence
        for sentence in sentences
        if segment.first_utterance <= sentence.unit.utterance_index <= segment.last_utterance
    )


def top_sentences(
    sentences: Sequence[RankedSentence],
    limit: int,
    minimum_words: int = MINIMUM_SUMMARY_WORDS,
    duplicate_threshold: float = DUPLICATE_THRESHOLD,
) -> tuple[RankedSentence, ...]:
    candidates = [sentence for sentence in sentences if is_summary_candidate(sentence, minimum_words)]
    if not candidates:
        candidates = list(sentences)
    ordered = sorted(candidates, key=lambda sentence: (-sentence.score, sentence.unit.index))
    selected: list[RankedSentence] = []
    for sentence in ordered:
        if len(selected) >= limit:
            break
        if _is_novel(sentence, selected, duplicate_threshold):
            selected.append(sentence)
    return tuple(sorted(selected, key=lambda sentence: sentence.unit.index))
