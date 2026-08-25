from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from pydantic import SecretStr

from hansard.adapters.delivery.markup import to_plain_text
from hansard.adapters.delivery.retry import RetryPolicy, Sleeper, send_with_retry
from hansard.adapters.delivery.transport import http_session
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload

SIGNATURE_HEADER = "X-Hansard-Signature"
TIMESTAMP_HEADER = "X-Hansard-Timestamp"
SIGNATURE_PREFIX = "sha256="
ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
ADAPTIVE_CARD_VERSION = "1.5"
MESSAGE_CARD_CONTEXT = "https://schema.org/extensions"
MESSAGE_CARD_THEME_COLOUR = "1F3864"
CARD_TEXT_LIMIT = 20_000

Clock = Callable[[], float]


class WebhookBodyFormat(StrEnum):
    JSON = "json"
    MESSAGE_CARD = "message_card"
    ADAPTIVE_CARD = "adaptive_card"


def canonical_payload_bytes(document: Mapping[str, object]) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def signing_string(timestamp: int, body: bytes) -> bytes:
    return f"{timestamp}.".encode() + body


def compute_signature(secret: SecretStr, timestamp: int, body: bytes) -> str:
    digest = hmac.new(
        secret.get_secret_value().encode("utf-8"),
        signing_string(timestamp, body),
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: SecretStr, timestamp: int, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(compute_signature(secret, timestamp, body), signature)


def json_document(payload: Payload, include_attachment_content: bool, generated_at: str) -> dict[str, object]:
    attachments = [
        {
            "filename": item.filename,
            "media_type": item.media_type,
            "size_bytes": len(item.content),
            **(
                {"content_base64": base64.b64encode(item.content).decode("ascii")}
                if include_attachment_content
                else {}
            ),
        }
        for item in payload.attachments
    ]
    return {
        "subject": payload.subject,
        "body": payload.body,
        "body_format": payload.body_format,
        "attachments": attachments,
        "generated_at": generated_at,
        "source": "hansard",
    }


def message_card_document(payload: Payload) -> dict[str, object]:
    text = to_plain_text(payload.body, payload.body_format)[:CARD_TEXT_LIMIT]
    return {
        "@type": "MessageCard",
        "@context": MESSAGE_CARD_CONTEXT,
        "summary": payload.subject or "Meeting minutes",
        "themeColor": MESSAGE_CARD_THEME_COLOUR,
        "title": payload.subject,
        "sections": [{"text": text, "markdown": True}],
    }


def adaptive_card_document(payload: Payload) -> dict[str, object]:
    text = to_plain_text(payload.body, payload.body_format)[:CARD_TEXT_LIMIT]
    blocks: list[dict[str, object]] = [
        {"type": "TextBlock", "text": payload.subject, "weight": "Bolder", "size": "Medium", "wrap": True},
        {"type": "TextBlock", "text": text, "wrap": True},
    ]
    if payload.attachments:
        listed = ", ".join(item.filename for item in payload.attachments)
        blocks.append({"type": "TextBlock", "text": f"Attachments: {listed}", "wrap": True, "isSubtle": True})
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": ADAPTIVE_CARD_CONTENT_TYPE,
                "content": {
                    "$schema": ADAPTIVE_CARD_SCHEMA,
                    "type": "AdaptiveCard",
                    "version": ADAPTIVE_CARD_VERSION,
                    "body": blocks,
                },
            }
        ],
    }


def build_document(
    payload: Payload,
    body_format: WebhookBodyFormat,
    include_attachment_content: bool,
    generated_at: str,
) -> dict[str, object]:
    if body_format is WebhookBodyFormat.MESSAGE_CARD:
        return message_card_document(payload)
    if body_format is WebhookBodyFormat.ADAPTIVE_CARD:
        return adaptive_card_document(payload)
    return json_document(payload, include_attachment_content, generated_at)


def resolve_url(address: str, default_url: str | None) -> str:
    text = address.strip()
    if text.lower().startswith(("workflow:", "webhook:")):
        text = text.split(":", 1)[1].strip()
    candidate = text or (default_url or "")
    if not candidate:
        raise DeliveryError(
            "webhook delivery needs a URL, set it on the delivery target address or in "
            "HANSARD_DELIVERY__WEBHOOK_URL"
        )
    if not candidate.lower().startswith(("http://", "https://")):
        raise DeliveryError(f"webhook URL '{candidate}' must start with http:// or https://")
    return candidate


@dataclass(frozen=True, slots=True)
class WebhookPublisher:
    default_url: str | None = None
    secret: SecretStr | None = None
    body_format: WebhookBodyFormat = WebhookBodyFormat.JSON
    http_client: httpx.AsyncClient | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Sleeper = asyncio.sleep
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    include_attachment_content: bool = False
    timeout_seconds: float = 30.0
    clock: Clock = time.time

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.WEBHOOK

    def build_request(self, payload: Payload) -> tuple[bytes, dict[str, str]]:
        stamped = int(self.clock())
        generated_at = datetime.fromtimestamp(stamped, tz=UTC).isoformat()
        document = build_document(payload, self.body_format, self.include_attachment_content, generated_at)
        body = canonical_payload_bytes(document)
        headers = {"Content-Type": "application/json", **dict(self.extra_headers)}
        if self.secret is not None:
            headers[TIMESTAMP_HEADER] = str(stamped)
            headers[SIGNATURE_HEADER] = compute_signature(self.secret, stamped, body)
        return body, headers

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None:
        url = resolve_url(target.address, self.default_url)
        body, headers = self.build_request(payload)
        async with http_session(self.http_client, self.timeout_seconds) as client:
            try:
                response = await send_with_retry(
                    lambda: client.post(url, content=body, headers=headers),
                    self.retry_policy,
                    self.sleep,
                )
            except httpx.HTTPError as error:
                raise DeliveryError(
                    f"cannot reach webhook {url}: {type(error).__name__}: {error}"
                ) from error
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise DeliveryError(
                f"webhook {url} answered {response.status_code}: {response.text[:300]}"
            )
