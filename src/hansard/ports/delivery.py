from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from hansard.domain.meeting import DeliveryChannel, DeliveryTarget


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    media_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class Payload:
    subject: str
    body: str
    body_format: str = "markdown"
    attachments: tuple[Attachment, ...] = ()


@runtime_checkable
class MinutesPublisher(Protocol):
    @property
    def channel(self) -> DeliveryChannel: ...

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None: ...
