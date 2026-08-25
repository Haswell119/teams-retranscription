from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from hansard.adapters.delivery.retry import RetryPolicy, Sleeper, send_with_retry
from hansard.domain.errors import DeliveryError

Clock = Callable[[], float]

EXPIRY_SKEW_SECONDS = 60.0
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
BOT_CONNECTOR_SCOPE = "https://api.botframework.com/.default"
BOT_CONNECTOR_TENANT = "botframework.com"


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class ClientCredentials:
    tenant_id: str
    client_id: str
    client_secret: SecretStr
    authority: str = "https://login.microsoftonline.com"
    scope: str = GRAPH_SCOPE

    @property
    def token_endpoint(self) -> str:
        return f"{self.authority.rstrip('/')}/{self.tenant_id}/oauth2/v2.0/token"

    def with_scope(self, scope: str) -> ClientCredentials:
        return ClientCredentials(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
            authority=self.authority,
            scope=scope,
        )

    def with_tenant(self, tenant_id: str) -> ClientCredentials:
        return ClientCredentials(
            tenant_id=tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
            authority=self.authority,
            scope=self.scope,
        )


class TokenSource(Protocol):
    async def fetch(self, client: httpx.AsyncClient, /) -> AccessToken: ...


def msal_available() -> bool:
    try:
        import msal
    except ImportError:
        return False
    return msal is not None


@dataclass(frozen=True, slots=True)
class HttpTokenSource:
    credentials: ClientCredentials
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Sleeper = asyncio.sleep
    clock: Clock = time.monotonic

    async def fetch(self, client: httpx.AsyncClient, /) -> AccessToken:
        form = {
            "grant_type": "client_credentials",
            "client_id": self.credentials.client_id,
            "client_secret": self.credentials.client_secret.get_secret_value(),
            "scope": self.credentials.scope,
        }
        try:
            response = await send_with_retry(
                lambda: client.post(self.credentials.token_endpoint, data=form),
                self.retry_policy,
                self.sleep,
            )
        except httpx.HTTPError as error:
            raise DeliveryError(
                f"cannot reach the Microsoft Entra ID token endpoint {self.credentials.token_endpoint}: "
                f"{type(error).__name__}"
            ) from error
        if response.status_code != httpx.codes.OK:
            raise DeliveryError(_token_failure_message(self.credentials, response))
        return _token_from_payload(response.json(), self.clock)


@dataclass(frozen=True, slots=True)
class MsalTokenSource:
    credentials: ClientCredentials
    clock: Clock = time.monotonic

    async def fetch(self, _client: httpx.AsyncClient, /) -> AccessToken:
        payload = await asyncio.to_thread(self._acquire)
        if "access_token" not in payload:
            raise DeliveryError(
                "Microsoft Entra ID refused the client credentials for scope "
                f"{self.credentials.scope}: {payload.get('error', 'unknown_error')} "
                f"({payload.get('error_description', 'no description')})"
            )
        return _token_from_payload(payload, self.clock)

    def _acquire(self) -> dict[str, Any]:
        import msal

        application = msal.ConfidentialClientApplication(
            client_id=self.credentials.client_id,
            authority=f"{self.credentials.authority.rstrip('/')}/{self.credentials.tenant_id}",
            client_credential=self.credentials.client_secret.get_secret_value(),
        )
        result: dict[str, Any] = application.acquire_token_for_client(scopes=[self.credentials.scope])
        return result


@dataclass(slots=True)
class CachedTokenProvider:
    source: TokenSource
    clock: Clock = time.monotonic
    expiry_skew_seconds: float = EXPIRY_SKEW_SECONDS
    _cached: AccessToken | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def token(self, client: httpx.AsyncClient) -> str:
        async with self._lock:
            cached = self._cached
            if cached is not None and cached.expires_at - self.expiry_skew_seconds > self.clock():
                return cached.value
            fresh = await self.source.fetch(client)
            self._cached = fresh
            return fresh.value

    def forget(self) -> None:
        self._cached = None


def build_token_provider(
    credentials: ClientCredentials,
    retry_policy: RetryPolicy = RetryPolicy(),
    sleep: Sleeper = asyncio.sleep,
    clock: Clock = time.monotonic,
    prefer_msal: bool = True,
) -> CachedTokenProvider:
    source: TokenSource = (
        MsalTokenSource(credentials=credentials, clock=clock)
        if prefer_msal and msal_available()
        else HttpTokenSource(credentials=credentials, retry_policy=retry_policy, sleep=sleep, clock=clock)
    )
    return CachedTokenProvider(source=source, clock=clock)


def _token_from_payload(payload: dict[str, Any], clock: Clock) -> AccessToken:
    value = payload.get("access_token")
    if not isinstance(value, str) or not value:
        raise DeliveryError("Microsoft Entra ID returned a token response without an access_token")
    try:
        lifetime = float(payload.get("expires_in", 0))
    except (TypeError, ValueError):
        lifetime = 0.0
    return AccessToken(value=value, expires_at=clock() + lifetime)


def _token_failure_message(credentials: ClientCredentials, response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    code = payload.get("error", f"http_{response.status_code}")
    description = payload.get("error_description", response.text[:300])
    return (
        f"Microsoft Entra ID refused the client credentials for scope {credentials.scope} "
        f"(tenant {credentials.tenant_id}, client {credentials.client_id}): {code} - {description}"
    )
