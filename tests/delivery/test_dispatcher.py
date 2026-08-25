from __future__ import annotations

import asyncio

from hansard.adapters.delivery.dispatcher import DeliveryDispatcher, DeliveryReport
from hansard.domain.errors import ConfigurationError, DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import MinutesPublisher, Payload

PAYLOAD = Payload(subject="Minutes", body="body")


class SpyPublisher:
    def __init__(self, channel: DeliveryChannel, error: Exception | None = None, delay: float = 0.0) -> None:
        self._channel = channel
        self.error = error
        self.delay = delay
        self.published: list[DeliveryTarget] = []
        self.started = asyncio.Event()

    @property
    def channel(self) -> DeliveryChannel:
        return self._channel

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None:
        self.started.set()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        self.published.append(target)


def dispatcher(
    publishers: dict[DeliveryChannel, MinutesPublisher], timeout: float = 5.0
) -> DeliveryDispatcher:
    return DeliveryDispatcher(
        resolve_publisher=lambda channel: publishers[channel], timeout_seconds=timeout
    )


def targets() -> tuple[DeliveryTarget, ...]:
    return (
        DeliveryTarget(channel=DeliveryChannel.FILESYSTEM, address="out"),
        DeliveryTarget(channel=DeliveryChannel.EMAIL, address="clerk@example.org"),
        DeliveryTarget(channel=DeliveryChannel.WEBHOOK, address="https://example.org/hook"),
    )


async def test_empty_target_list_gives_an_empty_report() -> None:
    report = await dispatcher({}).deliver((), PAYLOAD)

    assert report == DeliveryReport()
    assert report.all_succeeded


async def test_all_channels_receive_the_payload() -> None:
    publishers = {
        DeliveryChannel.FILESYSTEM: SpyPublisher(DeliveryChannel.FILESYSTEM),
        DeliveryChannel.EMAIL: SpyPublisher(DeliveryChannel.EMAIL),
        DeliveryChannel.WEBHOOK: SpyPublisher(DeliveryChannel.WEBHOOK),
    }

    report = await dispatcher(publishers).deliver(targets(), PAYLOAD)

    assert report.all_succeeded
    assert len(report.delivered) == 3
    assert all(publisher.published for publisher in publishers.values())


async def test_one_failing_channel_does_not_stop_the_others() -> None:
    publishers = {
        DeliveryChannel.FILESYSTEM: SpyPublisher(DeliveryChannel.FILESYSTEM),
        DeliveryChannel.EMAIL: SpyPublisher(DeliveryChannel.EMAIL, error=DeliveryError("relay down")),
        DeliveryChannel.WEBHOOK: SpyPublisher(DeliveryChannel.WEBHOOK),
    }

    report = await dispatcher(publishers).deliver(targets(), PAYLOAD)

    assert not report.all_succeeded
    assert report.any_succeeded
    assert {outcome.channel for outcome in report.delivered} == {
        DeliveryChannel.FILESYSTEM,
        DeliveryChannel.WEBHOOK,
    }
    assert report.failed[0].channel is DeliveryChannel.EMAIL
    assert "relay down" in report.failure_summary()


async def test_unresolvable_channel_is_reported_not_raised() -> None:
    def resolve(channel: DeliveryChannel) -> MinutesPublisher:
        raise ConfigurationError(f"unknown delivery channel '{channel}'")

    report = await DeliveryDispatcher(resolve_publisher=resolve).deliver(targets(), PAYLOAD)

    assert not report.any_succeeded
    assert len(report.failed) == 3
    assert "ConfigurationError" in report.failed[0].error


async def test_slow_channel_times_out_without_blocking_the_rest() -> None:
    publishers = {
        DeliveryChannel.FILESYSTEM: SpyPublisher(DeliveryChannel.FILESYSTEM, delay=5.0),
        DeliveryChannel.EMAIL: SpyPublisher(DeliveryChannel.EMAIL),
        DeliveryChannel.WEBHOOK: SpyPublisher(DeliveryChannel.WEBHOOK),
    }

    report = await dispatcher(publishers, timeout=0.05).deliver(targets(), PAYLOAD)

    assert len(report.delivered) == 2
    assert "timed out after 0.05s" in report.failed[0].error


async def test_targets_run_concurrently() -> None:
    slow = SpyPublisher(DeliveryChannel.FILESYSTEM, delay=0.05)
    other = SpyPublisher(DeliveryChannel.EMAIL, delay=0.05)
    publishers = {DeliveryChannel.FILESYSTEM: slow, DeliveryChannel.EMAIL: other}
    pair = (
        DeliveryTarget(channel=DeliveryChannel.FILESYSTEM, address="out"),
        DeliveryTarget(channel=DeliveryChannel.EMAIL, address="clerk@example.org"),
    )

    started = asyncio.get_running_loop().time()
    report = await dispatcher(publishers).deliver(pair, PAYLOAD)
    elapsed = asyncio.get_running_loop().time() - started

    assert report.all_succeeded
    assert elapsed < 0.09


async def test_publishers_are_built_once_per_channel() -> None:
    builds: list[DeliveryChannel] = []
    publisher = SpyPublisher(DeliveryChannel.FILESYSTEM)

    def resolve(channel: DeliveryChannel) -> MinutesPublisher:
        builds.append(channel)
        return publisher

    pair = (
        DeliveryTarget(channel=DeliveryChannel.FILESYSTEM, address="a"),
        DeliveryTarget(channel=DeliveryChannel.FILESYSTEM, address="b"),
    )
    report = await DeliveryDispatcher(resolve_publisher=resolve).deliver(pair, PAYLOAD)

    assert report.all_succeeded
    assert builds == [DeliveryChannel.FILESYSTEM]
    assert [item.address for item in publisher.published] == ["a", "b"]


async def test_outcomes_carry_durations() -> None:
    publishers = {DeliveryChannel.FILESYSTEM: SpyPublisher(DeliveryChannel.FILESYSTEM)}
    single = (DeliveryTarget(channel=DeliveryChannel.FILESYSTEM, address="out"),)

    report = await dispatcher(publishers).deliver(single, PAYLOAD)

    assert report.outcomes[0].duration_seconds >= 0.0
    assert report.outcomes[0].error is None
