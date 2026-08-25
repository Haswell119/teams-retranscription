from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from hansard.adapters.delivery.bot_framework import TeamsBotPublisher
from hansard.adapters.delivery.filesystem import FilesystemPublisher
from hansard.adapters.delivery.graph import TeamsChatPublisher
from hansard.adapters.delivery.registry import (
    available_channels,
    build_publisher,
    register_publisher,
)
from hansard.adapters.delivery.routing import AddressRoutedPublisher, address_scheme
from hansard.adapters.delivery.smtp import EmailPublisher
from hansard.adapters.delivery.webhook import WebhookBodyFormat, WebhookPublisher
from hansard.config import DeliverySettings, GraphSettings, Settings, SmtpSettings
from hansard.domain.errors import ConfigurationError, DeliveryError
from hansard.domain.meeting import DeliveryChannel
from hansard.ports.delivery import MinutesPublisher

GRAPH = GraphSettings(
    tenant_id="contoso.onmicrosoft.com",
    client_id="11111111-2222-3333-4444-555555555555",
    client_secret=SecretStr("s3cr3t"),
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HANSARD_DELIVERY__WEBHOOK_SECRET",
        "HANSARD_DELIVERY__WEBHOOK_FORMAT",
        "HANSARD_DELIVERY__BOT_TENANT_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def test_available_channels_cover_the_domain_enum() -> None:
    assert available_channels() == tuple(sorted(str(channel) for channel in DeliveryChannel))


def test_unknown_channel_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="unknown delivery channel"):
        build_publisher("carrier-pigeon", DeliverySettings())


def test_filesystem_publisher_uses_the_output_directory(tmp_path: Path) -> None:
    publisher = build_publisher(DeliveryChannel.FILESYSTEM, DeliverySettings(output_dir=tmp_path))

    assert isinstance(publisher, FilesystemPublisher)
    assert publisher.root == tmp_path


def test_email_publisher_uses_the_smtp_settings() -> None:
    settings = DeliverySettings(smtp=SmtpSettings(host="mail.internal", port=587, sender="bot@internal"))

    publisher = build_publisher(DeliveryChannel.EMAIL, settings)

    assert isinstance(publisher, EmailPublisher)
    assert publisher.sender_address == "bot@internal"


def test_webhook_publisher_defaults_to_plain_json() -> None:
    settings = DeliverySettings(webhook_url="https://intranet.example/hook")

    publisher = build_publisher(DeliveryChannel.WEBHOOK, settings)

    assert isinstance(publisher, WebhookPublisher)
    assert publisher.body_format is WebhookBodyFormat.JSON
    assert publisher.default_url == "https://intranet.example/hook"
    assert publisher.secret is None


def test_webhook_secret_and_format_are_configurable() -> None:
    settings = DeliverySettings(webhook_secret=SecretStr("topsecret"), webhook_format="message_card")

    publisher = build_publisher(DeliveryChannel.WEBHOOK, settings)

    assert isinstance(publisher, WebhookPublisher)
    assert publisher.secret is not None
    assert publisher.secret.get_secret_value() == "topsecret"
    assert publisher.body_format is WebhookBodyFormat.MESSAGE_CARD
    assert "topsecret" not in repr(publisher)


def test_unknown_webhook_format_is_refused() -> None:
    settings = DeliverySettings.model_construct(
        **{**DeliverySettings().model_dump(), "webhook_format": "smoke-signal"}
    )

    with pytest.raises(ConfigurationError, match="unknown webhook body format"):
        build_publisher(DeliveryChannel.WEBHOOK, settings)


def test_the_environment_reaches_delivery_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HANSARD_DELIVERY__WEBHOOK_FORMAT", "message_card")
    monkeypatch.setenv("HANSARD_DELIVERY__WEBHOOK_SECRET", "topsecret")

    settings = Settings().delivery

    assert settings.webhook_format == "message_card"
    assert settings.webhook_secret is not None
    assert settings.webhook_secret.get_secret_value() == "topsecret"


def test_teams_channel_without_graph_credentials_only_routes_webhooks() -> None:
    publisher = build_publisher(DeliveryChannel.TEAMS_CHAT, DeliverySettings())

    assert isinstance(publisher, AddressRoutedPublisher)
    assert publisher.channel is DeliveryChannel.TEAMS_CHAT
    assert sorted(publisher.routes) == ["https", "webhook", "workflow"]
    with pytest.raises(DeliveryError, match="HANSARD_DELIVERY__GRAPH__TENANT_ID"):
        publisher.route_for("chat:19:abc@thread.v2")


def test_teams_channel_with_graph_credentials_routes_graph_and_bot() -> None:
    publisher = build_publisher(DeliveryChannel.TEAMS_CHAT, DeliverySettings(graph=GRAPH))

    assert isinstance(publisher, AddressRoutedPublisher)
    assert isinstance(publisher.route_for("chat:19:abc@thread.v2"), TeamsChatPublisher)
    assert isinstance(publisher.route_for("channel:team/channel"), TeamsChatPublisher)
    assert isinstance(publisher.route_for("bot:https://smba.example/#19:abc"), TeamsBotPublisher)
    assert isinstance(publisher.route_for("https://prod.logic.azure.com/hook"), WebhookPublisher)


def test_teams_webhook_route_defaults_to_adaptive_cards() -> None:
    publisher = build_publisher(DeliveryChannel.TEAMS_CHAT, DeliverySettings())

    route = publisher.route_for("https://prod.logic.azure.com/hook")

    assert isinstance(route, WebhookPublisher)
    assert route.body_format is WebhookBodyFormat.ADAPTIVE_CARD


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("chat:19:abc", "chat"),
        ("CHANNEL:team/channel", "channel"),
        ("https://x.example/y", "https"),
        ("http://x.example/y", "https"),
        ("bot:https://x/#19", "bot"),
        ("plain-address", ""),
    ],
)
def test_address_scheme_detection(address: str, expected: str) -> None:
    assert address_scheme(address) == expected


def test_custom_channels_can_be_registered() -> None:
    sentinel = FilesystemPublisher(root=Path("/tmp/sentinel"))

    def factory(settings: DeliverySettings) -> MinutesPublisher:
        return sentinel

    register_publisher("sentinel", factory)
    try:
        assert build_publisher("sentinel", DeliverySettings()) is sentinel
        assert "sentinel" in available_channels()
    finally:
        from hansard.adapters.delivery import registry

        registry._FACTORIES.pop("sentinel")
