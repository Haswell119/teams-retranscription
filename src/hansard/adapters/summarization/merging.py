from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar

from hansard.adapters.asr.phonetics import similarity, sound_key
from hansard.adapters.summarization.text import jaccard, term_set
from hansard.domain.minutes import ActionItem, Citation, Decision, OpenQuestion

ITEM = TypeVar("ITEM")

DEFAULT_MERGE_THRESHOLD = 0.6
DEFAULT_MAX_CITATIONS = 4
PHONETIC_FLOOR = 0.85


@dataclass(frozen=True, slots=True)
class MergeOptions:
    threshold: float = DEFAULT_MERGE_THRESHOLD
    max_citations: int = DEFAULT_MAX_CITATIONS


def text_similarity(left: str, right: str, language: str) -> float:
    lexical = jaccard(term_set(left, language), term_set(right, language))
    phonetic = similarity(sound_key(left, language), sound_key(right, language))
    return max(lexical, phonetic if phonetic >= PHONETIC_FLOOR else 0.0)


def merge_citations(
    left: Sequence[Citation],
    right: Sequence[Citation],
    limit: int = DEFAULT_MAX_CITATIONS,
) -> tuple[Citation, ...]:
    seen: dict[tuple[float, float, str], Citation] = {}
    for citation in (*left, *right):
        seen.setdefault((citation.span.start, citation.span.end, citation.speaker), citation)
    ordered = sorted(seen.values(), key=lambda citation: (citation.span.start, citation.span.end))
    return tuple(ordered[:limit])


def merge_similar(
    items: Sequence[ITEM],
    text_of: Callable[[ITEM], str],
    combine: Callable[[ITEM, ITEM], ITEM],
    language: str,
    options: MergeOptions | None = None,
) -> tuple[ITEM, ...]:
    active = options or MergeOptions()
    merged: list[ITEM] = []
    for item in items:
        target = _closest(item, merged, text_of, language, active.threshold)
        if target is None:
            merged.append(item)
        else:
            merged[target] = combine(merged[target], item)
    return tuple(merged)


def _closest(
    item: ITEM,
    merged: Sequence[ITEM],
    text_of: Callable[[ITEM], str],
    language: str,
    threshold: float,
) -> int | None:
    best: tuple[float, int] | None = None
    for position, existing in enumerate(merged):
        score = text_similarity(text_of(item), text_of(existing), language)
        if score >= threshold and (best is None or score > best[0]):
            best = (score, position)
    return best[1] if best is not None else None


def _longer(left: str, right: str) -> str:
    return left if len(left) >= len(right) else right


def combine_decisions(left: Decision, right: Decision, limit: int = DEFAULT_MAX_CITATIONS) -> Decision:
    return replace(
        left,
        statement=_longer(left.statement, right.statement),
        rationale=left.rationale or right.rationale,
        citations=merge_citations(left.citations, right.citations, limit),
    )


def combine_actions(
    left: ActionItem,
    right: ActionItem,
    limit: int = DEFAULT_MAX_CITATIONS,
) -> ActionItem:
    return replace(
        left,
        description=_longer(left.description, right.description),
        owner=left.owner or right.owner,
        due_date=left.due_date or right.due_date,
        citations=merge_citations(left.citations, right.citations, limit),
    )


def combine_questions(
    left: OpenQuestion,
    right: OpenQuestion,
    limit: int = DEFAULT_MAX_CITATIONS,
) -> OpenQuestion:
    return replace(
        left,
        question=_longer(left.question, right.question),
        raised_by=left.raised_by or right.raised_by,
        citations=merge_citations(left.citations, right.citations, limit),
    )


def merge_decisions(
    decisions: Sequence[Decision],
    language: str,
    options: MergeOptions | None = None,
) -> tuple[Decision, ...]:
    active = options or MergeOptions()
    return merge_similar(
        decisions,
        lambda decision: decision.statement,
        lambda left, right: combine_decisions(left, right, active.max_citations),
        language,
        active,
    )


def merge_actions(
    actions: Sequence[ActionItem],
    language: str,
    options: MergeOptions | None = None,
) -> tuple[ActionItem, ...]:
    active = options or MergeOptions()
    return merge_similar(
        actions,
        lambda action: action.description,
        lambda left, right: combine_actions(left, right, active.max_citations),
        language,
        active,
    )


def merge_questions(
    questions: Sequence[OpenQuestion],
    language: str,
    options: MergeOptions | None = None,
) -> tuple[OpenQuestion, ...]:
    active = options or MergeOptions()
    return merge_similar(
        questions,
        lambda question: question.question,
        lambda left, right: combine_questions(left, right, active.max_citations),
        language,
        active,
    )
