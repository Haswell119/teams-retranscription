from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from hansard.adapters.delivery.tokens import AccessToken, CachedTokenProvider
from hansard.ports.delivery import Attachment, Payload

MARKDOWN_BODY = "# Minutes\n\n- decision one\n- decision two\n\nSigned **Hansard**."


class StubTokenSource:
    def __init__(self, tokens: list[AccessToken]) -> None:
        self.tokens = tokens
        self.calls = 0

    async def fetch(self, client: httpx.AsyncClient) -> AccessToken:
        self.calls += 1
        return self.tokens[min(self.calls - 1, len(self.tokens) - 1)]


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def payload() -> Payload:
    return Payload(
        subject="Board meeting 2026-08-25",
        body=MARKDOWN_BODY,
        body_format="markdown",
        attachments=(
            Attachment(filename="transcript.txt", media_type="text/plain", content=b"hello"),
            Attachment(filename="minutes.pdf", media_type="application/pdf", content=b"%PDF-1.4"),
        ),
    )


@pytest.fixture
def token_provider() -> CachedTokenProvider:
    return CachedTokenProvider(
        source=StubTokenSource([AccessToken(value="graph-token", expires_at=1e9)])
    )


@pytest.fixture
def sleeper() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def mock_client() -> Callable[[Callable[[httpx.Request], httpx.Response]], httpx.AsyncClient]:
    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory
