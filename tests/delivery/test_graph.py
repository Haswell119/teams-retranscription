from __future__ import annotations

import httpx
import pytest

from hansard.adapters.delivery.graph import (
    TeamsChatPublisher,
    TeamsTargetKind,
    chunk_html,
    paginate_html,
    parse_teams_target,
    render_message_html,
)
from hansard.adapters.delivery.retry import RetryPolicy
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload

CHAT_ID = "19:2da4c29f6d7041eca70b638b43d45437@thread.v2"
TEAM_ID = "fbe2bf47-16c8-47cf-b4a5-4b9b187c508b"
CHANNEL_ID = "19:4a95f7d8db4c4e7fae857bcebe0623e6@thread.tacv2"


def target(address: str) -> DeliveryTarget:
    return DeliveryTarget(channel=DeliveryChannel.TEAMS_CHAT, address=address)


def test_chat_address_is_parsed() -> None:
    parsed = parse_teams_target(f"chat:{CHAT_ID}")

    assert parsed.kind is TeamsTargetKind.CHAT
    assert parsed.primary_id == CHAT_ID
    assert parsed.message_path() == f"/chats/{CHAT_ID.replace(':', '%3A').replace('@', '%40')}/messages"


def test_channel_address_is_parsed() -> None:
    parsed = parse_teams_target(f"channel:{TEAM_ID}/{CHANNEL_ID}")

    assert parsed.kind is TeamsTargetKind.CHANNEL
    assert parsed.primary_id == TEAM_ID
    assert parsed.secondary_id == CHANNEL_ID
    assert parsed.message_path().startswith(f"/teams/{TEAM_ID}/channels/")


@pytest.mark.parametrize(
    "address",
    ["", "19:abc@thread.v2", "chat:", "channel:only-team", "channel:team/", "mail:someone"],
)
def test_invalid_addresses_are_refused(address: str) -> None:
    with pytest.raises(DeliveryError):
        parse_teams_target(address)


def test_short_html_is_a_single_chunk() -> None:
    assert chunk_html("<p>short</p>") == ("<p>short</p>",)


def test_chunking_splits_on_block_boundaries() -> None:
    markup = "\n".join(f"<p>{'x' * 90}</p>" for _ in range(6))

    chunks = chunk_html(markup, limit=300)

    assert len(chunks) == 3
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert "".join(chunks).count("<p>") == 6


def test_oversized_single_block_is_hard_split() -> None:
    chunks = chunk_html("y" * 500, limit=200)

    assert len(chunks) == 5
    assert "".join(chunks) == "y" * 500


def test_pagination_numbers_the_parts() -> None:
    markup = "\n".join(f"<p>{'x' * 90}</p>" for _ in range(6))

    pages = paginate_html(markup, limit=300, max_chunks=4)

    assert len(pages) == 3
    assert pages[0].startswith("<p><em>Part 1 of 3</em></p>")
    assert "Truncated" not in "".join(pages)


def test_pagination_truncates_with_a_reference() -> None:
    markup = "\n".join(f"<p>{'x' * 90}</p>" for _ in range(20))

    pages = paginate_html(markup, limit=300, max_chunks=2, artifact_reference="https://files/minutes.md")

    assert len(pages) == 2
    assert "Truncated" in pages[-1]
    assert 'href="https://files/minutes.md"' in pages[-1]


def test_pagination_without_reference_points_at_the_artefact_directory() -> None:
    markup = "\n".join(f"<p>{'x' * 90}</p>" for _ in range(20))

    pages = paginate_html(markup, limit=300, max_chunks=1)

    assert "artefact directory" in pages[-1]


def test_rendered_message_lists_attachments(payload: Payload) -> None:
    markup = render_message_html(payload)

    assert markup.startswith("<h3>Board meeting 2026-08-25</h3>")
    assert "<li>transcript.txt</li>" in markup
    assert "<li>decision one</li>" in markup


async def test_publish_posts_html_to_a_chat(mock_client, token_provider, payload: Payload) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "1616991463150"})

    async with mock_client(handler) as client:
        publisher = TeamsChatPublisher(token_provider=token_provider, http_client=client)
        await publisher.publish(target(f"chat:{CHAT_ID}"), payload)

    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer graph-token"
    body = requests[0].read().decode()
    assert '"contentType":"html"' in body.replace(" ", "")
    assert str(requests[0].url).endswith("/messages")


async def test_publish_posts_each_chunk(mock_client, token_provider) -> None:
    posted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(request.read().decode())
        return httpx.Response(201, json={"id": "x"})

    payload = Payload(subject="Long", body="\n\n".join("paragraph " + "z" * 200 for _ in range(10)))
    async with mock_client(handler) as client:
        publisher = TeamsChatPublisher(
            token_provider=token_provider, http_client=client, character_limit=600, max_chunks=5
        )
        await publisher.publish(target(f"channel:{TEAM_ID}/{CHANNEL_ID}"), payload)

    assert len(posted) > 1
    assert "Part 1 of" in posted[0]


async def test_throttling_is_retried_with_retry_after(
    mock_client, sleeper, token_provider, payload: Payload
) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "12"})
        return httpx.Response(201, json={"id": "x"})

    async with mock_client(handler) as client:
        publisher = TeamsChatPublisher(token_provider=token_provider, http_client=client, sleep=sleeper)
        await publisher.publish(target(f"chat:{CHAT_ID}"), payload)

    assert len(calls) == 2
    assert sleeper.delays == [12.0]


async def test_forbidden_explains_the_application_permission_limitation(
    mock_client, token_provider, payload: Payload
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": "Forbidden",
                    "message": "Missing role permissions on the request. API requires one of "
                    "'Teamwork.Migrate.All'. Roles on the request 'Group.Selected'.",
                }
            },
        )

    async with mock_client(handler) as client:
        publisher = TeamsChatPublisher(token_provider=token_provider, http_client=client)
        with pytest.raises(DeliveryError) as failure:
            await publisher.publish(target(f"chat:{CHAT_ID}"), payload)

    message = str(failure.value)
    assert "Teamwork.Migrate.All" in message
    assert "Power Automate" in message


async def test_transport_failure_is_wrapped(mock_client, token_provider, payload: Payload) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure", request=request)

    async with mock_client(handler) as client:
        publisher = TeamsChatPublisher(
            token_provider=token_provider,
            http_client=client,
            retry_policy=RetryPolicy(attempts=1),
        )
        with pytest.raises(DeliveryError, match="cannot reach Microsoft Graph"):
            await publisher.publish(target(f"chat:{CHAT_ID}"), payload)


def test_channel_is_teams_chat(token_provider) -> None:
    assert TeamsChatPublisher(token_provider=token_provider).channel is DeliveryChannel.TEAMS_CHAT
