from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from hansard.domain.language import MIXED, normalise_tag
from hansard.domain.minutes import Minutes
from hansard.domain.speakers import Participant
from hansard.domain.transcript import Transcript

DEFAULT_GENERATOR = "Hansard"
DEFAULT_TIMEZONE = "UTC"


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    component: str
    engine: str
    model_id: str = ""

    @property
    def label(self) -> str:
        return f"{self.engine} ({self.model_id})" if self.model_id else self.engine


@dataclass(frozen=True, slots=True)
class RenderContext:
    title: str = "Meeting"
    started_at: datetime | None = None
    duration_seconds: float = 0.0
    participants: tuple[Participant, ...] = ()
    language: str = "en"
    languages: tuple[str, ...] = ()
    timezone: str = DEFAULT_TIMEZONE
    provenance: tuple[ModelProvenance, ...] = ()
    generator: str = DEFAULT_GENERATOR

    @property
    def participant_names(self) -> tuple[str, ...]:
        return tuple(participant.display_name for participant in self.participants)

    @property
    def is_multilingual(self) -> bool:
        return normalise_tag(self.language) == MIXED or len(self.languages) > 1

    @property
    def display_language(self) -> str:
        if normalise_tag(self.language) == MIXED:
            return self.languages[0] if self.languages else "en"
        return self.language

    @property
    def spoken_languages(self) -> tuple[str, ...]:
        if self.languages:
            return self.languages
        resolved = normalise_tag(self.language)
        return () if resolved in (None, MIXED) else (resolved,)


@runtime_checkable
class RendererIdentity(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def media_type(self) -> str: ...

    @property
    def file_extension(self) -> str: ...


@runtime_checkable
class TranscriptRenderer(RendererIdentity, Protocol):
    def render_transcript(self, transcript: Transcript, context: RenderContext) -> str | bytes: ...


@runtime_checkable
class MinutesRenderer(RendererIdentity, Protocol):
    def render_minutes(self, minutes: Minutes, context: RenderContext) -> str | bytes: ...


AnyRenderer = TranscriptRenderer | MinutesRenderer
