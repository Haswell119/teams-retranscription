from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from hansard.adapters.delivery.graph import (
    DEFAULT_MAX_CHUNKS,
    TEAMS_POST_CHARACTER_LIMIT,
    paginate_html,
    render_message_html,
)
from hansard.adapters.delivery.markup import to_plain_text
from hansard.adapters.delivery.retry import RetryPolicy, Sleeper, send_with_retry
from hansard.adapters.delivery.tokens import CachedTokenProvider
from hansard.adapters.delivery.transport import http_session
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload

BOT_ADDRESS_HINT = (
    "Bot Framework delivery addresses look like "
    "'bot:https://smba.trafficmanager.net/emea/#19:meeting_abc@thread.v2', that is "
    "'bot:{serviceUrl}#{conversationId}' taken from an activity your bot already received."
)


@dataclass(frozen=True, slots=True)
class BotConversationTarget:
    service_url: str
    conversation_id: str

    def activities_url(self) -> str:
        return f"{self.service_url.rstrip('/')}/v3/conversations/{self.conversation_id}/activities"


def parse_bot_target(address: str) -> BotConversationTarget:
    text = address.strip()
    scheme, separator, remainder = text.partition(":")
    if not separator or scheme.strip().lower() != "bot":
        raise DeliveryError(f"Bot Framework address '{address}' must start with 'bot:'. {BOT_ADDRESS_HINT}")
    service_url, marker, conversation_id = remainder.strip().rpartition("#")
    if not marker or not service_url.strip() or not conversation_id.strip():
        raise DeliveryError(f"Bot Framework address '{address}' is incomplete. {BOT_ADDRESS_HINT}")
    if not service_url.strip().lower().startswith("https://"):
        raise DeliveryError(f"Bot Framework service URL '{service_url}' must start with https://")
    return BotConversationTarget(
        service_url=service_url.strip(),
        conversation_id=conversation_id.strip(),
    )


@dataclass(frozen=True, slots=True)
class TeamsBotPublisher:
    token_provider: CachedTokenProvider
    http_client: httpx.AsyncClient | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Sleeper = asyncio.sleep
    character_limit: int = TEAMS_POST_CHARACTER_LIMIT
    max_chunks: int = DEFAULT_MAX_CHUNKS
    artifact_reference: str | None = None
    timeout_seconds: float = 30.0

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.TEAMS_CHAT

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None:
        conversation = parse_bot_target(target.address)
        chunks = paginate_html(
            render_message_html(payload, self.artifact_reference),
            self.character_limit,
            self.max_chunks,
            self.artifact_reference,
        )
        url = conversation.activities_url()
        summary = to_plain_text(payload.body, payload.body_format)[:200]
        async with http_session(self.http_client, self.timeout_seconds) as client:
            token = await self.token_provider.token(client)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            for chunk in chunks:
                activity = {
                    "type": "message",
                    "textFormat": "xml",
                    "text": chunk,
                    "summary": summary,
                }
                await self._post_activity(client, url, headers, activity, target.address)

    async def _post_activity(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        activity: dict[str, str],
        address: str,
    ) -> None:
        try:
            response = await send_with_retry(
                lambda: client.post(url, json=activity, headers=headers),
                self.retry_policy,
                self.sleep,
            )
        except httpx.HTTPError as error:
            raise DeliveryError(
                f"cannot reach the Bot Connector at {url}: {type(error).__name__}: {error}"
            ) from error
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise DeliveryError(
                f"Bot Connector refused POST {url} for target '{address}': "
                f"{response.status_code} {response.text[:300]}"
            )
