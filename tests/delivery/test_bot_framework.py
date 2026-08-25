from __future__ import annotations

import json

import httpx
import pytest

from hansard.adapters.delivery.bot_framework import TeamsBotPublisher, parse_bot_target
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload

SERVICE_URL = "https://smba.trafficmanager.net/emea/"
CONVERSATION_ID = "19:meeting_NjQ2Nzg@thread.v2"
ADDRESS = f"bot:{SERVICE_URL}#{CONVERSATION_ID}"


def target(address: str = ADDRESS) -> DeliveryTarget:
    return DeliveryTarget(channel=DeliveryChannel.TEAMS_CHAT, address=address)


def test_conversation_address_is_parsed() -> None:
    parsed = parse_bot_target(ADDRESS)

    assert parsed.service_url == SERVICE_URL
    assert parsed.conversation_id == CONVERSATION_ID
    assert parsed.activities_url() == (
        f"https://smba.trafficmanager.net/emea/v3/conversations/{CONVERSATION_ID}/activities"
    )


@pytest.mark.parametrize(
    "address",
    [
        "",
        "chat:19:abc@thread.v2",
        "bot:19:abc@thread.v2",
        "bot:https://smba.example/#",
        "bot:#19:abc",
        "bot:http://smba.example/#19:abc",
    ],
)
def test_invalid_bot_addresses_are_refused(address: str) -> None:
    with pytest.raises(DeliveryError):
        parse_bot_target(address)


async def test_publish_sends_a_message_activity(mock_client, token_provider, payload: Payload) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "1616990032035"})

    async with mock_client(handler) as client:
        publisher = TeamsBotPublisher(token_provider=token_provider, http_client=client)
        await publisher.publish(target(), payload)

    activity = json.loads(requests[0].read())
    assert requests[0].headers["Authorization"] == "Bearer graph-token"
    assert str(requests[0].url).endswith("/activities")
    assert activity["type"] == "message"
    assert activity["textFormat"] == "xml"
    assert "<li>decision one</li>" in activity["text"]


async def test_publish_reports_rejections(mock_client, token_provider, payload: Payload) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="BotNotInConversationRoster")

    async with mock_client(handler) as client:
        publisher = TeamsBotPublisher(token_provider=token_provider, http_client=client)
        with pytest.raises(DeliveryError, match="BotNotInConversationRoster"):
            await publisher.publish(target(), payload)


async def test_throttling_is_retried(mock_client, sleeper, token_provider, payload: Payload) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "5"})
        return httpx.Response(200, json={"id": "x"})

    async with mock_client(handler) as client:
        publisher = TeamsBotPublisher(token_provider=token_provider, http_client=client, sleep=sleeper)
        await publisher.publish(target(), payload)

    assert sleeper.delays == [5.0]
    assert len(calls) == 2


def test_channel_is_teams_chat(token_provider) -> None:
    assert TeamsBotPublisher(token_provider=token_provider).channel is DeliveryChannel.TEAMS_CHAT
