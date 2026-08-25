from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from hansard.domain.meeting import Capture, MeetingRequest


@runtime_checkable
class MeetingCapture(Protocol):
    @property
    def name(self) -> str: ...

    async def capture(self, request: MeetingRequest, workspace: Path) -> Capture: ...
