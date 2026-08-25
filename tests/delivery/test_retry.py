from __future__ import annotations

from email.utils import formatdate

import httpx
import pytest

from hansard.adapters.delivery.retry import (
    RetryPolicy,
    retry_after_seconds,
    send_with_retry,
)

POLICY = RetryPolicy(attempts=4, initial_backoff_seconds=1.0, backoff_multiplier=2.0)


def response(status_code: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code=status_code, headers=headers or {}, request=httpx.Request("POST", "https://host/x"))


class Responder:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.calls = 0

    async def __call__(self) -> httpx.Response:
        item = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


async def test_successful_call_is_not_retried(sleeper) -> None:
    responder = Responder([response(201)])

    result = await send_with_retry(responder, POLICY, sleeper)

    assert result.status_code == 201
    assert responder.calls == 1
    assert sleeper.delays == []


async def test_429_honours_retry_after(sleeper) -> None:
    responder = Responder([response(429, {"Retry-After": "7"}), response(201)])

    result = await send_with_retry(responder, POLICY, sleeper)

    assert result.status_code == 201
    assert sleeper.delays == [7.0]


async def test_503_without_retry_after_uses_exponential_backoff(sleeper) -> None:
    responder = Responder([response(503), response(503), response(200)])

    result = await send_with_retry(responder, POLICY, sleeper)

    assert result.status_code == 200
    assert sleeper.delays == [1.0, 2.0]


async def test_retry_after_is_capped(sleeper) -> None:
    policy = RetryPolicy(attempts=2, max_retry_after_seconds=30.0)
    responder = Responder([response(429, {"Retry-After": "600"}), response(200)])

    await send_with_retry(responder, policy, sleeper)

    assert sleeper.delays == [30.0]


async def test_retries_are_bounded_by_the_policy(sleeper) -> None:
    responder = Responder([response(429, {"Retry-After": "1"})])

    result = await send_with_retry(responder, RetryPolicy(attempts=3), sleeper)

    assert result.status_code == 429
    assert responder.calls == 3
    assert len(sleeper.delays) == 2


async def test_transport_errors_are_retried_then_raised(sleeper) -> None:
    responder = Responder([httpx.ConnectError("no route")])

    with pytest.raises(httpx.ConnectError):
        await send_with_retry(responder, RetryPolicy(attempts=2), sleeper)

    assert responder.calls == 2


async def test_transport_error_then_success(sleeper) -> None:
    responder = Responder([httpx.ReadTimeout("slow"), response(200)])

    result = await send_with_retry(responder, POLICY, sleeper)

    assert result.status_code == 200
    assert sleeper.delays == [1.0]


def test_retry_after_http_date_is_converted() -> None:
    header = formatdate(timeval=1_000_120.0, usegmt=True)
    seconds = retry_after_seconds(response(429, {"Retry-After": header}), now=lambda: 1_000_100.0)

    assert seconds is not None
    assert 19.0 <= seconds <= 21.0


def test_retry_after_absent_or_invalid() -> None:
    assert retry_after_seconds(response(429)) is None
    assert retry_after_seconds(response(429, {"Retry-After": "soon"})) is None


def test_backoff_is_capped_by_the_policy() -> None:
    policy = RetryPolicy(initial_backoff_seconds=5.0, backoff_multiplier=10.0, max_backoff_seconds=20.0)

    assert [policy.backoff_for(index) for index in range(3)] == [5.0, 20.0, 20.0]


async def test_zero_attempts_is_refused(sleeper) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await send_with_retry(Responder([response(200)]), RetryPolicy(attempts=0), sleeper)
