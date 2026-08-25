from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx

Sleeper = Callable[[float], Awaitable[None]]
ResponseSender = Callable[[], Awaitable[httpx.Response]]
Clock = Callable[[], float]

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 4
    initial_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 30.0
    max_retry_after_seconds: float = 120.0

    def backoff_for(self, attempt_index: int) -> float:
        exponential = self.initial_backoff_seconds * self.backoff_multiplier**attempt_index
        return min(exponential, self.max_backoff_seconds)


def retry_after_seconds(response: httpx.Response, now: Clock = time.time) -> float | None:
    header = response.headers.get("Retry-After")
    if not header:
        return None
    text = header.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return max(0.0, moment.timestamp() - now())


def _delay_for(response: httpx.Response, policy: RetryPolicy, attempt_index: int, now: Clock) -> float:
    advertised = retry_after_seconds(response, now)
    if advertised is None:
        return policy.backoff_for(attempt_index)
    return min(advertised, policy.max_retry_after_seconds)


async def send_with_retry(
    send: ResponseSender,
    policy: RetryPolicy = RetryPolicy(),
    sleep: Sleeper = asyncio.sleep,
    retryable_status_codes: frozenset[int] = RETRYABLE_STATUS_CODES,
    now: Clock = time.time,
) -> httpx.Response:
    if policy.attempts < 1:
        raise ValueError("RetryPolicy.attempts must be at least 1")
    for attempt_index in range(policy.attempts):
        is_final_attempt = attempt_index == policy.attempts - 1
        try:
            response = await send()
        except httpx.HTTPError:
            if is_final_attempt:
                raise
            await sleep(policy.backoff_for(attempt_index))
            continue
        if response.status_code not in retryable_status_codes or is_final_attempt:
            return response
        await sleep(_delay_for(response, policy, attempt_index, now))
    raise RuntimeError("unreachable retry state")
