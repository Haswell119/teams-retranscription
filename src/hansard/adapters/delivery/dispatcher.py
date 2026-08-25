from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from hansard.adapters.delivery.registry import build_publisher
from hansard.config import DeliverySettings
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import MinutesPublisher, Payload

PublisherResolver = Callable[[DeliveryChannel], MinutesPublisher]
Clock = Callable[[], float]

DEFAULT_TARGET_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    channel: DeliveryChannel
    address: str
    succeeded: bool
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    outcomes: tuple[DeliveryOutcome, ...] = ()

    @property
    def delivered(self) -> tuple[DeliveryOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if outcome.succeeded)

    @property
    def failed(self) -> tuple[DeliveryOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.succeeded)

    @property
    def all_succeeded(self) -> bool:
        return not self.failed

    @property
    def any_succeeded(self) -> bool:
        return bool(self.delivered)

    def failure_summary(self) -> str:
        return "; ".join(
            f"{outcome.channel}:{outcome.address}: {outcome.error}" for outcome in self.failed
        )


@dataclass(frozen=True, slots=True)
class DeliveryDispatcher:
    resolve_publisher: PublisherResolver
    timeout_seconds: float = DEFAULT_TARGET_TIMEOUT_SECONDS
    clock: Clock = time.monotonic
    _cache: dict[DeliveryChannel, MinutesPublisher] = field(default_factory=dict, repr=False)

    async def deliver(self, targets: Sequence[DeliveryTarget], payload: Payload) -> DeliveryReport:
        if not targets:
            return DeliveryReport()
        outcomes = await asyncio.gather(
            *(self._deliver_one(target, payload) for target in targets)
        )
        return DeliveryReport(outcomes=tuple(outcomes))

    def _publisher_for(self, channel: DeliveryChannel) -> MinutesPublisher:
        cached = self._cache.get(channel)
        if cached is None:
            cached = self.resolve_publisher(channel)
            self._cache[channel] = cached
        return cached

    async def _deliver_one(self, target: DeliveryTarget, payload: Payload) -> DeliveryOutcome:
        started = self.clock()
        try:
            publisher = self._publisher_for(target.channel)
            await asyncio.wait_for(publisher.publish(target, payload), timeout=self.timeout_seconds)
        except TimeoutError:
            return self._failure(target, started, f"timed out after {self.timeout_seconds:g}s")
        except Exception as error:
            return self._failure(target, started, f"{type(error).__name__}: {error}")
        return DeliveryOutcome(
            channel=target.channel,
            address=target.address,
            succeeded=True,
            duration_seconds=self.clock() - started,
        )

    def _failure(self, target: DeliveryTarget, started: float, message: str) -> DeliveryOutcome:
        return DeliveryOutcome(
            channel=target.channel,
            address=target.address,
            succeeded=False,
            error=message,
            duration_seconds=self.clock() - started,
        )


def dispatcher_from_settings(
    settings: DeliverySettings,
    timeout_seconds: float = DEFAULT_TARGET_TIMEOUT_SECONDS,
) -> DeliveryDispatcher:
    return DeliveryDispatcher(
        resolve_publisher=lambda channel: build_publisher(channel, settings),
        timeout_seconds=timeout_seconds,
    )
