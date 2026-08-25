from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from hansard.adapters.summarization.citations import SentenceUnit, citation_for
from hansard.adapters.summarization.ranking import RankedSentence, top_sentences
from hansard.adapters.summarization.text import join_sentences, truncate
from hansard.adapters.summarization.topics import TopicSegment
from hansard.domain.minutes import Citation, Minutes, Topic
from hansard.domain.speakers import UNKNOWN_SPEAKER, Participant, Roster
from hansard.domain.transcript import Transcript
from hansard.rendering.composition import speaking_seconds

TITLE_CHARACTER_LIMIT = 120


def _identifier(display_name: str) -> str:
    return display_name.strip().casefold().replace(" ", ".") or "unknown"


def participants_for(transcript: Transcript, roster: Roster) -> tuple[Participant, ...]:
    known = {participant.display_name: participant for participant in roster.participants}
    participants = list(roster.participants)
    for speaker in transcript.speakers:
        if not speaker or speaker == UNKNOWN_SPEAKER or speaker in known:
            continue
        participants.append(Participant(identifier=_identifier(speaker), display_name=speaker))
    return tuple(participants)


def speaking_time_for(transcript: Transcript) -> tuple[tuple[str, float], ...]:
    return speaking_seconds(transcript)


def topic_from_segment(
    segment: TopicSegment,
    sentences: Sequence[RankedSentence],
    key_point_limit: int,
    title: str = "",
    summary: str = "",
) -> Topic:
    texts = tuple(sentence.unit.text for sentence in top_sentences(sentences, key_point_limit + 1))
    if summary:
        return Topic(
            title=title or segment.title,
            span=segment.span,
            summary=summary,
            key_points=texts[:key_point_limit],
        )
    return Topic(
        title=title or segment.title,
        span=segment.span,
        summary=texts[0] if texts else "",
        key_points=texts[1:],
    )


def fallback_abstract(units: Sequence[SentenceUnit], sentence_limit: int = 3) -> str:
    return join_sentences([unit.text for unit in units[:sentence_limit]])


def is_empty(minutes: Minutes) -> bool:
    return not (
        minutes.abstract.strip()
        or minutes.topics
        or minutes.decisions
        or minutes.actions
        or minutes.open_questions
    )


def ensure_non_empty(
    minutes: Minutes,
    units: Sequence[SentenceUnit],
    segments: Sequence[TopicSegment],
) -> Minutes:
    if not units:
        return minutes
    abstract = minutes.abstract.strip() or fallback_abstract(units)
    topics = minutes.topics
    if not topics and segments:
        topics = (
            Topic(
                title=segments[0].title,
                span=segments[0].span,
                summary=abstract,
                key_points=tuple(unit.text for unit in units[:3]),
            ),
        )
    return replace(minutes, abstract=abstract, topics=topics)


def meeting_title(requested: str, segments: Sequence[TopicSegment]) -> str:
    if requested.strip():
        return truncate(requested, TITLE_CHARACTER_LIMIT)
    if segments:
        return truncate(segments[0].title, TITLE_CHARACTER_LIMIT)
    return "Meeting"


def citations_of(units: Sequence[SentenceUnit], include_citations: bool) -> tuple[Citation, ...]:
    if not include_citations:
        return ()
    seen: dict[tuple[float, float], Citation] = {}
    for unit in units:
        seen.setdefault((unit.span.start, unit.span.end), citation_for(unit))
    return tuple(seen.values())
