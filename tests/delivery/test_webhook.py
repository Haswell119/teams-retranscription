from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest
from pydantic import SecretStr

from hansard.adapters.delivery.retry import RetryPolicy
from hansard.adapters.delivery.webhook import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    WebhookBodyFormat,
    WebhookPublisher,
    resolve_url,
    verify_signature,
)
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload

SECRET = SecretStr("shared-secret")
FIXED_TIME = 1_756_100_000.0


def target(address: str = "") -> DeliveryTarget:
    return DeliveryTarget(channel=DeliveryChannel.WEBHOOK, address=address)


def frozen_clock() -> float:
    return FIXED_TIME


@pytest.mark.parametrize(
    ("address", "default", "expected"),
    [
        ("https://intranet.example/hook", None, "https://intranet.example/hook"),
        ("workflow:https://prod-1.westeurope.logic.azure.com/x", None,
         "https://prod-1.westeurope.logic.azure.com/x"),
        ("webhook:https://intranet.example/a", None, "https://intranet.example/a"),
        ("", "https://fallback.example/hook", "https://fallback.example/hook"),
    ],
)
def test_url_resolution(address: str, default: str | None, expected: str) -> None:
    assert resolve_url(address, default) == expected


@pytest.mark.parametrize(
    ("address", "default"),
    [("", None), ("ftp://intranet.example/hook", None), ("intranet.example/hook", None)],
)
def test_invalid_urls_are_refused(address: str, default: str | None) -> None:
    with pytest.raises(DeliveryError):
        resolve_url(address, default)


def test_signature_matches_an_independent_hmac(payload: Payload) -> None:
    publisher = WebhookPublisher(secret=SECRET, clock=frozen_clock)

    body, headers = publisher.build_request(payload)

    expected = hmac.new(
        b"shared-secret",
        f"{int(FIXED_TIME)}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers[SIGNATURE_HEADER] == f"sha256={expected}"
    assert headers[TIMESTAMP_HEADER] == str(int(FIXED_TIME))
    assert verify_signature(SECRET, int(FIXED_TIME), body, headers[SIGNATURE_HEADER])


def test_signature_rejects_tampering(payload: Payload) -> None:
    publisher = WebhookPublisher(secret=SECRET, clock=frozen_clock)
    body, headers = publisher.build_request(payload)

    assert not verify_signature(SECRET, int(FIXED_TIME), body + b" ", headers[SIGNATURE_HEADER])
    assert not verify_signature(SECRET, int(FIXED_TIME) + 1, body, headers[SIGNATURE_HEADER])
    assert not verify_signature(SecretStr("other"), int(FIXED_TIME), body, headers[SIGNATURE_HEADER])


def test_no_signature_headers_without_a_secret(payload: Payload) -> None:
    _, headers = WebhookPublisher().build_request(payload)

    assert SIGNATURE_HEADER not in headers
    assert TIMESTAMP_HEADER not in headers


def test_json_body_describes_attachments_without_content(payload: Payload) -> None:
    body, _ = WebhookPublisher(clock=frozen_clock).build_request(payload)
    document = json.loads(body)

    assert document["subject"] == payload.subject
    assert document["body_format"] == "markdown"
    assert document["attachments"][0] == {
        "filename": "transcript.txt",
        "media_type": "text/plain",
        "size_bytes": 5,
    }
    assert document["generated_at"].startswith("2025-08-25T")


def test_json_body_can_embed_attachment_content(payload: Payload) -> None:
    publisher = WebhookPublisher(include_attachment_content=True, clock=frozen_clock)

    document = json.loads(publisher.build_request(payload)[0])

    assert document["attachments"][0]["content_base64"] == "aGVsbG8="


def test_message_card_shape(payload: Payload) -> None:
    publisher = WebhookPublisher(body_format=WebhookBodyFormat.MESSAGE_CARD, clock=frozen_clock)

    document = json.loads(publisher.build_request(payload)[0])

    assert document["@type"] == "MessageCard"
    assert document["@context"] == "https://schema.org/extensions"
    assert document["sections"][0]["markdown"] is True
    assert "decision one" in document["sections"][0]["text"]


def test_adaptive_card_shape(payload: Payload) -> None:
    publisher = WebhookPublisher(body_format=WebhookBodyFormat.ADAPTIVE_CARD, clock=frozen_clock)

    document = json.loads(publisher.build_request(payload)[0])

    assert document["type"] == "message"
    card = document["attachments"][0]
    assert card["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert card["content"]["type"] == "AdaptiveCard"
    assert card["content"]["body"][0]["text"] == payload.subject
    assert "Attachments: transcript.txt, minutes.pdf" in card["content"]["body"][-1]["text"]


async def test_publish_posts_the_signed_body(mock_client, payload: Payload) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    async with mock_client(handler) as client:
        publisher = WebhookPublisher(secret=SECRET, http_client=client, clock=frozen_clock)
        await publisher.publish(target("https://intranet.example/hook"), payload)

    request = requests[0]
    assert request.headers["Content-Type"] == "application/json"
    assert verify_signature(SECRET, int(FIXED_TIME), request.read(), request.headers[SIGNATURE_HEADER])


async def test_publish_retries_on_503(mock_client, sleeper, payload: Payload) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, headers={"Retry-After": "2"})
        return httpx.Response(200)

    async with mock_client(handler) as client:
        publisher = WebhookPublisher(http_client=client, sleep=sleeper)
        await publisher.publish(target("https://intranet.example/hook"), payload)

    assert len(calls) == 3
    assert sleeper.delays == [2.0, 2.0]


async def test_publish_reports_rejections(mock_client, sleeper, payload: Payload) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Bad card payload")

    async with mock_client(handler) as client:
        publisher = WebhookPublisher(http_client=client, sleep=sleeper, retry_policy=RetryPolicy(attempts=1))
        with pytest.raises(DeliveryError, match="Bad card payload"):
            await publisher.publish(target("https://intranet.example/hook"), payload)


async def test_extra_headers_are_sent(mock_client, payload: Payload) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with mock_client(handler) as client:
        publisher = WebhookPublisher(http_client=client, extra_headers={"X-Tenant": "council"})
        await publisher.publish(target("https://intranet.example/hook"), payload)

    assert seen[0].headers["X-Tenant"] == "council"


def test_channel_is_webhook() -> None:
    assert WebhookPublisher().channel is DeliveryChannel.WEBHOOK
