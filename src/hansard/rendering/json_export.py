from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from hansard import __version__
from hansard.domain.minutes import Citation, Minutes
from hansard.domain.speakers import Participant
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Word
from hansard.rendering.composition import speaking_shares
from hansard.rendering.ports import RenderContext
from hansard.rendering.timecode import TimestampStyle, format_timestamp

SCHEMA_VERSION = "1.0"
TRANSCRIPT_KIND = "transcript"
MINUTES_KIND = "minutes"
JSON_MEDIA_TYPE = "application/json"
JSON_EXTENSION = ".json"
SECONDS_PRECISION = 3
CONFIDENCE_PRECISION = 4

JsonValue = dict[str, Any]


def _seconds(value: float) -> float:
    return round(value, SECONDS_PRECISION)


def _span(span: TimeSpan) -> JsonValue:
    return {
        "start": _seconds(span.start),
        "end": _seconds(span.end),
        "timecode": format_timestamp(span.start, TimestampStyle.WEB_VTT),
    }


def _participant(participant: Participant) -> JsonValue:
    return {
        "identifier": participant.identifier,
        "display_name": participant.display_name,
        "email": participant.email,
        "is_organizer": participant.is_organizer,
        "is_external": participant.is_external,
    }


def _word(word: Word) -> JsonValue:
    return {
        "text": word.text,
        "start": _seconds(word.span.start),
        "end": _seconds(word.span.end),
        "confidence": round(word.confidence, CONFIDENCE_PRECISION),
        "speaker": word.speaker,
    }


def _citations(citations: Sequence[Citation]) -> list[JsonValue]:
    return [
        {"speaker": citation.speaker, "quote": citation.quote, **_span(citation.span)}
        for citation in citations
    ]


def _envelope(kind: str, context: RenderContext) -> JsonValue:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "generator": {"name": context.generator, "version": __version__},
        "meeting": {
            "title": context.title,
            "started_at": context.started_at.isoformat() if context.started_at else None,
            "timezone": context.timezone,
            "language": context.language,
            "duration_seconds": _seconds(context.duration_seconds),
            "participants": [_participant(participant) for participant in context.participants],
            "provenance": [
                {"component": entry.component, "engine": entry.engine, "model_id": entry.model_id}
                for entry in context.provenance
            ],
        },
    }


def _transcript_payload(transcript: Transcript, include_word_timings: bool) -> JsonValue:
    utterances: list[JsonValue] = []
    for index, utterance in enumerate(transcript.utterances):
        payload: JsonValue = {
            "index": index,
            "speaker": utterance.speaker,
            "start": _seconds(utterance.span.start),
            "end": _seconds(utterance.span.end),
            "timecode": format_timestamp(utterance.span.start, TimestampStyle.WEB_VTT),
            "language": utterance.language,
            "confidence": round(utterance.confidence, CONFIDENCE_PRECISION),
            "text": utterance.text,
        }
        if include_word_timings and utterance.words:
            payload["words"] = [_word(word) for word in utterance.words]
        utterances.append(payload)
    return {
        "language": transcript.language,
        "audio_duration_seconds": _seconds(transcript.audio_duration),
        "word_count": transcript.word_count,
        "speakers": list(transcript.speakers),
        "utterances": utterances,
    }


def _minutes_payload(minutes: Minutes) -> JsonValue:
    return {
        "title": minutes.title,
        "language": minutes.language,
        "generated_at": minutes.generated_at.isoformat(),
        "abstract": minutes.abstract,
        "participants": [_participant(participant) for participant in minutes.participants],
        "topics": [
            {
                "title": topic.title,
                "summary": topic.summary,
                "key_points": list(topic.key_points),
                **_span(topic.span),
            }
            for topic in minutes.topics
        ],
        "decisions": [
            {
                "statement": decision.statement,
                "rationale": decision.rationale,
                "citations": _citations(decision.citations),
            }
            for decision in minutes.decisions
        ],
        "actions": [
            {
                "description": action.description,
                "owner": action.owner,
                "due_date": action.due_date,
                "citations": _citations(action.citations),
            }
            for action in minutes.actions
        ],
        "open_questions": [
            {
                "question": question.question,
                "raised_by": question.raised_by,
                "citations": _citations(question.citations),
            }
            for question in minutes.open_questions
        ],
        "speaking_time": [
            {
                "speaker": share.speaker,
                "seconds": _seconds(share.seconds),
                "share": round(share.share, CONFIDENCE_PRECISION),
            }
            for share in speaking_shares(minutes.speaking_time)
        ],
    }


@dataclass(frozen=True, slots=True)
class JsonRenderer:
    indent: int = 2
    include_word_timings: bool = True
    ensure_ascii: bool = False

    @property
    def name(self) -> str:
        return "json"

    @property
    def media_type(self) -> str:
        return JSON_MEDIA_TYPE

    @property
    def file_extension(self) -> str:
        return JSON_EXTENSION

    def render_transcript(self, transcript: Transcript, context: RenderContext) -> str:
        document = _envelope(TRANSCRIPT_KIND, context)
        document[TRANSCRIPT_KIND] = _transcript_payload(transcript, self.include_word_timings)
        return self._serialised(document)

    def render_minutes(self, minutes: Minutes, context: RenderContext) -> str:
        document = _envelope(MINUTES_KIND, context)
        document[MINUTES_KIND] = _minutes_payload(minutes)
        return self._serialised(document)

    def _serialised(self, document: JsonValue) -> str:
        return json.dumps(document, indent=self.indent, ensure_ascii=self.ensure_ascii) + "\n"
