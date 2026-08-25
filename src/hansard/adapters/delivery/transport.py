from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

DEFAULT_TIMEOUT_SECONDS = 30.0


@asynccontextmanager
async def http_session(
    client: httpx.AsyncClient | None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    owned = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)
    try:
        yield owned
    finally:
        await owned.aclose()
