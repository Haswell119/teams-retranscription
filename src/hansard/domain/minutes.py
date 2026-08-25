from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from hansard.domain.speakers import Participant
from hansard.domain.timespan import TimeSpan


@dataclass(frozen=True, slots=True)
class Citation:
    span: TimeSpan
    speaker: str
    quote: str


@dataclass(frozen=True, slots=True)
class ActionItem:
    description: str
    owner: str | None = None
    due_date: str | None = None
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    statement: str
    rationale: str | None = None
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    question: str
    raised_by: str | None = None
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class Topic:
    title: str
    span: TimeSpan
    summary: str
    key_points: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Minutes:
    title: str
    abstract: str
    language: str
    generated_at: datetime
    participants: tuple[Participant, ...] = ()
    topics: tuple[Topic, ...] = ()
    decisions: tuple[Decision, ...] = ()
    actions: tuple[ActionItem, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    speaking_time: tuple[tuple[str, float], ...] = ()
