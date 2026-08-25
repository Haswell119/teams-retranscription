from __future__ import annotations

from typing import Protocol, runtime_checkable

from hansard.domain.meeting import MeetingRequest
from hansard.domain.minutes import Minutes
from hansard.domain.speakers import Roster
from hansard.domain.transcript import Transcript


@runtime_checkable
class TextGenerator(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def context_tokens(self) -> int: ...

    def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, object] | None) -> str: ...


@runtime_checkable
class MinutesWriter(Protocol):
    @property
    def name(self) -> str: ...

    def compose(self, transcript: Transcript, roster: Roster, request: MeetingRequest) -> Minutes: ...
