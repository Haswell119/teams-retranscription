from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from hansard.adapters.delivery.tokens import (
    AccessToken,
    CachedTokenProvider,
    ClientCredentials,
    HttpTokenSource,
    build_token_provider,
)
from hansard.domain.errors import DeliveryError

CREDENTIALS = ClientCredentials(
    tenant_id="contoso.onmicrosoft.com",
    client_id="11111111-2222-3333-4444-555555555555",
    client_secret=SecretStr("s3cr3t"),
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_endpoint_follows_the_v2_shape() -> None:
    assert CREDENTIALS.token_endpoint == (
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token"
    )


def test_scope_and_tenant_overrides_keep_the_secret() -> None:
    connector = CREDENTIALS.with_scope("https://api.botframework.com/.default").with_tenant("botframework.com")

    assert connector.scope == "https://api.botframework.com/.default"
    assert connector.token_endpoint.endswith("/botframework.com/oauth2/v2.0/token")
    assert connector.client_secret.get_secret_value() == "s3cr3t"


async def test_client_credentials_request_shape(mock_client) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"access_token": "abc", "expires_in": 3599})

    source = HttpTokenSource(credentials=CREDENTIALS, clock=FakeClock())
    async with mock_client(handler) as client:
        token = await source.fetch(client)

    body = seen[0].content.decode()
    assert seen[0].url == httpx.URL(CREDENTIALS.token_endpoint)
    assert "grant_type=client_credentials" in body
    assert "scope=https%3A%2F%2Fgraph.microsoft.com%2F.default" in body
    assert token.value == "abc"
    assert token.expires_at == 3599


async def test_token_is_cached_until_it_nears_expiry(mock_client) -> None:
    clock = FakeClock()
    source_calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        source_calls.append(1)
        return httpx.Response(200, json={"access_token": f"token-{len(source_calls)}", "expires_in": 3600})

    provider = CachedTokenProvider(
        source=HttpTokenSource(credentials=CREDENTIALS, clock=clock), clock=clock
    )
    async with mock_client(handler) as client:
        first = await provider.token(client)
        clock.now = 3000.0
        second = await provider.token(client)
        clock.now = 3560.0
        third = await provider.token(client)

    assert first == second == "token-1"
    assert third == "token-2"
    assert len(source_calls) == 2


async def test_forget_forces_a_refresh(mock_client) -> None:
    counter = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["value"] += 1
        return httpx.Response(200, json={"access_token": f"t{counter['value']}", "expires_in": 3600})

    provider = CachedTokenProvider(source=HttpTokenSource(credentials=CREDENTIALS, clock=FakeClock()))
    async with mock_client(handler) as client:
        await provider.token(client)
        provider.forget()
        await provider.token(client)

    assert counter["value"] == 2


async def test_rejected_credentials_produce_an_actionable_error(mock_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret"},
        )

    source = HttpTokenSource(credentials=CREDENTIALS)
    async with mock_client(handler) as client:
        with pytest.raises(DeliveryError) as failure:
            await source.fetch(client)

    message = str(failure.value)
    assert "invalid_client" in message
    assert "AADSTS7000215" in message
    assert "s3cr3t" not in message


async def test_token_endpoint_429_is_retried(mock_client, sleeper) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"access_token": "later", "expires_in": 60})

    source = HttpTokenSource(credentials=CREDENTIALS, sleep=sleeper)
    async with mock_client(handler) as client:
        token = await source.fetch(client)

    assert token.value == "later"
    assert sleeper.delays == [3.0]


async def test_missing_access_token_is_reported(mock_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "Bearer"})

    source = HttpTokenSource(credentials=CREDENTIALS)
    async with mock_client(handler) as client:
        with pytest.raises(DeliveryError, match="without an access_token"):
            await source.fetch(client)


def test_build_token_provider_falls_back_to_httpx_without_msal() -> None:
    provider = build_token_provider(CREDENTIALS, prefer_msal=False)

    assert isinstance(provider.source, HttpTokenSource)


async def test_provider_accepts_any_token_source() -> None:
    class Fixed:
        async def fetch(self, client: httpx.AsyncClient) -> AccessToken:
            return AccessToken(value="fixed", expires_at=1e9)

    provider = CachedTokenProvider(source=Fixed())

    assert await provider.token(httpx.AsyncClient()) == "fixed"
