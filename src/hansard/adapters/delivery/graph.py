from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import quote

import httpx

from hansard.adapters.delivery.markup import to_html
from hansard.adapters.delivery.retry import RetryPolicy, Sleeper, send_with_retry
from hansard.adapters.delivery.tokens import CachedTokenProvider
from hansard.adapters.delivery.transport import http_session
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload

TEAMS_POST_CHARACTER_LIMIT = 28_000
CHUNK_HEADER_RESERVE = 96
DEFAULT_MAX_CHUNKS = 4
APP_ONLY_HINT = (
    "Microsoft Graph only accepts application-only chatMessage POSTs with the Teamwork.Migrate.All "
    "role against chats and channels in migration mode. For everyday posting use a Power Automate "
    "Workflows webhook (channel 'webhook'), a Bot Framework conversation (address 'bot:...'), or "
    "delegated credentials. See docs/delivery.md."
)


class TeamsTargetKind(StrEnum):
    CHAT = "chat"
    CHANNEL = "channel"


@dataclass(frozen=True, slots=True)
class TeamsTarget:
    kind: TeamsTargetKind
    primary_id: str
    secondary_id: str | None = None

    def message_path(self) -> str:
        if self.kind is TeamsTargetKind.CHAT:
            return f"/chats/{quote(self.primary_id, safe='')}/messages"
        return (
            f"/teams/{quote(self.primary_id, safe='')}"
            f"/channels/{quote(str(self.secondary_id), safe='')}/messages"
        )


def parse_teams_target(address: str) -> TeamsTarget:
    text = address.strip()
    scheme, separator, remainder = text.partition(":")
    if not separator:
        raise DeliveryError(
            f"Teams delivery address '{address}' must start with 'chat:' or 'channel:', "
            f"for example 'chat:19:abc@thread.v2' or 'channel:{{team-id}}/{{channel-id}}'"
        )
    scheme = scheme.strip().lower()
    remainder = remainder.strip()
    if scheme == TeamsTargetKind.CHAT:
        if not remainder:
            raise DeliveryError(f"Teams chat address '{address}' is missing the chat id")
        return TeamsTarget(kind=TeamsTargetKind.CHAT, primary_id=remainder)
    if scheme == TeamsTargetKind.CHANNEL:
        team_id, slash, channel_id = remainder.partition("/")
        if not slash or not team_id.strip() or not channel_id.strip():
            raise DeliveryError(
                f"Teams channel address '{address}' must be 'channel:{{team-id}}/{{channel-id}}'"
            )
        return TeamsTarget(
            kind=TeamsTargetKind.CHANNEL,
            primary_id=team_id.strip(),
            secondary_id=channel_id.strip(),
        )
    raise DeliveryError(f"unsupported Teams address scheme '{scheme}'; expected 'chat:' or 'channel:'")


def _hard_split(block: str, limit: int) -> list[str]:
    return [block[index : index + limit] for index in range(0, len(block), limit)] or [""]


def chunk_html(markup: str, limit: int = TEAMS_POST_CHARACTER_LIMIT) -> tuple[str, ...]:
    usable = max(1, limit - CHUNK_HEADER_RESERVE)
    chunks: list[str] = []
    current = ""
    for block in markup.split("\n"):
        pieces = _hard_split(block, usable) if len(block) > usable else [block]
        for piece in pieces:
            candidate = f"{current}\n{piece}" if current else piece
            if len(candidate) <= usable:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = piece
    if current or not chunks:
        chunks.append(current)
    return tuple(chunks)


def paginate_html(
    markup: str,
    limit: int = TEAMS_POST_CHARACTER_LIMIT,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    artifact_reference: str | None = None,
) -> tuple[str, ...]:
    chunks = chunk_html(markup, limit)
    truncated = len(chunks) > max_chunks
    kept = list(chunks[:max_chunks])
    total = len(kept)
    if total == 1 and not truncated:
        return (kept[0],)
    numbered = [f"<p><em>Part {index + 1} of {total}</em></p>\n{chunk}" for index, chunk in enumerate(kept)]
    if truncated:
        numbered[-1] = f"{numbered[-1]}\n{_truncation_notice(artifact_reference)}"
    return tuple(numbered)


def _truncation_notice(artifact_reference: str | None) -> str:
    if artifact_reference:
        safe = html.escape(artifact_reference, quote=True)
        return f'<p><strong>Truncated.</strong> Full minutes: <a href="{safe}">{safe}</a></p>'
    return (
        "<p><strong>Truncated.</strong> The complete minutes are in the artefact directory "
        "produced by the filesystem delivery channel.</p>"
    )


def render_message_html(payload: Payload, artifact_reference: str | None = None) -> str:
    parts = [f"<h3>{html.escape(payload.subject, quote=False)}</h3>"] if payload.subject else []
    parts.append(to_html(payload.body, payload.body_format))
    if payload.attachments:
        listed = "".join(
            f"<li>{html.escape(item.filename, quote=False)}</li>" for item in payload.attachments
        )
        parts.append(f"<p><em>Attachments (not uploaded to Teams):</em></p><ul>{listed}</ul>")
    if artifact_reference:
        safe = html.escape(artifact_reference, quote=True)
        parts.append(f'<p><a href="{safe}">Full artefact</a></p>')
    return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class TeamsChatPublisher:
    token_provider: CachedTokenProvider
    base_url: str = "https://graph.microsoft.com/v1.0"
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
        teams_target = parse_teams_target(target.address)
        chunks = paginate_html(
            render_message_html(payload, self.artifact_reference),
            self.character_limit,
            self.max_chunks,
            self.artifact_reference,
        )
        url = f"{self.base_url.rstrip('/')}{teams_target.message_path()}"
        async with http_session(self.http_client, self.timeout_seconds) as client:
            token = await self.token_provider.token(client)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            for chunk in chunks:
                await self._post_chunk(client, url, headers, chunk, target.address)

    async def _post_chunk(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        chunk: str,
        address: str,
    ) -> None:
        body = {"body": {"contentType": "html", "content": chunk}}
        try:
            response = await send_with_retry(
                lambda: client.post(url, json=body, headers=headers),
                self.retry_policy,
                self.sleep,
            )
        except httpx.HTTPError as error:
            raise DeliveryError(
                f"cannot reach Microsoft Graph at {url}: {type(error).__name__}: {error}"
            ) from error
        if response.status_code not in {httpx.codes.OK, httpx.codes.CREATED}:
            raise DeliveryError(_graph_failure_message(address, url, response))


def _graph_failure_message(address: str, url: str, response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code", f"http_{response.status_code}")
    message = error.get("message", response.text[:300])
    base = (
        f"Microsoft Graph refused POST {url} for target '{address}': "
        f"{response.status_code} {code} - {message}"
    )
    if response.status_code in {httpx.codes.FORBIDDEN, httpx.codes.UNAUTHORIZED}:
        return f"{base}. {APP_ONLY_HINT}"
    return base
