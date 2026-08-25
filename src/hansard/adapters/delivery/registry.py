from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass

from pydantic import SecretStr

from hansard.adapters.delivery.bot_framework import TeamsBotPublisher
from hansard.adapters.delivery.graph import TeamsChatPublisher
from hansard.adapters.delivery.routing import AddressRoutedPublisher
from hansard.adapters.delivery.smtp import AiosmtplibSender, EmailPublisher
from hansard.adapters.delivery.tokens import (
    BOT_CONNECTOR_SCOPE,
    CachedTokenProvider,
    ClientCredentials,
    build_token_provider,
)
from hansard.adapters.delivery.webhook import WebhookBodyFormat, WebhookPublisher
from hansard.config import DeliverySettings
from hansard.domain.errors import ConfigurationError
from hansard.domain.meeting import DeliveryChannel
from hansard.ports.delivery import MinutesPublisher

PublisherFactory = Callable[[DeliverySettings], MinutesPublisher]

WEBHOOK_SECRET_ENV = "HANSARD_DELIVERY__WEBHOOK_SECRET"
WEBHOOK_FORMAT_ENV = "HANSARD_DELIVERY__WEBHOOK_FORMAT"
BOT_TENANT_ENV = "HANSARD_DELIVERY__BOT_TENANT_ID"
TEAMS_GUIDANCE = (
    "Set HANSARD_DELIVERY__GRAPH__TENANT_ID, HANSARD_DELIVERY__GRAPH__CLIENT_ID and "
    "HANSARD_DELIVERY__GRAPH__CLIENT_SECRET for 'chat:'/'channel:'/'bot:' addresses, or point the "
    "target at a Power Automate Workflows URL."
)

_FACTORIES: MutableMapping[str, PublisherFactory] = {}


def register_publisher(channel: DeliveryChannel | str, factory: PublisherFactory) -> None:
    _FACTORIES[str(channel)] = factory


def available_channels() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def build_publisher(channel: DeliveryChannel | str, settings: DeliverySettings) -> MinutesPublisher:
    factory = _FACTORIES.get(str(channel))
    if factory is None:
        raise ConfigurationError(f"unknown delivery channel '{channel}', available: {available_channels()}")
    return factory(settings)


@dataclass(frozen=True, slots=True)
class WebhookOptions:
    secret: SecretStr | None
    body_format: WebhookBodyFormat


def webhook_options(settings: DeliverySettings, default_format: WebhookBodyFormat) -> WebhookOptions:
    raw_secret = settings.webhook_secret
    secret = raw_secret if isinstance(raw_secret, SecretStr) else _optional_secret(raw_secret)
    raw_format = settings.webhook_format
    return WebhookOptions(secret=secret, body_format=_parse_format(raw_format, default_format))


def _optional_secret(value: object) -> SecretStr | None:
    if isinstance(value, str) and value:
        return SecretStr(value)
    return None


def _parse_format(value: object, fallback: WebhookBodyFormat) -> WebhookBodyFormat:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return WebhookBodyFormat(value.strip().lower())
    except ValueError as error:
        supported = ", ".join(item.value for item in WebhookBodyFormat)
        raise ConfigurationError(f"unknown webhook body format '{value}', supported: {supported}") from error


def graph_credentials(settings: DeliverySettings) -> ClientCredentials | None:
    graph = settings.graph
    if not (graph.tenant_id and graph.client_id and graph.client_secret):
        return None
    return ClientCredentials(
        tenant_id=graph.tenant_id,
        client_id=graph.client_id,
        client_secret=graph.client_secret,
        authority=graph.authority,
        scope=graph.scope,
    )


def _graph_token_provider(credentials: ClientCredentials) -> CachedTokenProvider:
    return build_token_provider(credentials)


def _bot_credentials(settings: DeliverySettings, graph: ClientCredentials) -> ClientCredentials:
    connector = graph.with_scope(BOT_CONNECTOR_SCOPE)
    tenant = settings.bot_tenant_id
    if isinstance(tenant, str) and tenant:
        return connector.with_tenant(tenant)
    return connector


def build_filesystem_publisher(settings: DeliverySettings) -> MinutesPublisher:
    from hansard.adapters.delivery.filesystem import FilesystemPublisher

    return FilesystemPublisher(root=settings.output_dir)


def build_email_publisher(settings: DeliverySettings) -> MinutesPublisher:
    smtp = settings.smtp
    return EmailPublisher(
        sender_address=smtp.sender,
        message_sender=AiosmtplibSender(
            host=smtp.host,
            port=smtp.port,
            username=smtp.username,
            password=smtp.password,
            use_tls=smtp.use_tls,
            start_tls=smtp.start_tls,
        ),
    )


def build_webhook_publisher(settings: DeliverySettings) -> MinutesPublisher:
    options = webhook_options(settings, WebhookBodyFormat.JSON)
    return WebhookPublisher(
        default_url=settings.webhook_url,
        secret=options.secret,
        body_format=options.body_format,
    )


def build_teams_publisher(settings: DeliverySettings) -> MinutesPublisher:
    options = webhook_options(settings, WebhookBodyFormat.ADAPTIVE_CARD)
    webhook = WebhookPublisher(
        default_url=settings.webhook_url,
        secret=options.secret,
        body_format=options.body_format,
    )
    routes: dict[str, MinutesPublisher] = {
        "https": webhook,
        "workflow": webhook,
        "webhook": webhook,
    }
    credentials = graph_credentials(settings)
    if credentials is not None:
        graph_publisher = TeamsChatPublisher(
            token_provider=_graph_token_provider(credentials),
            base_url=settings.graph.base_url,
        )
        routes["chat"] = graph_publisher
        routes["channel"] = graph_publisher
        routes["bot"] = TeamsBotPublisher(
            token_provider=_graph_token_provider(_bot_credentials(settings, credentials)),
        )
    return AddressRoutedPublisher(
        routed_channel=DeliveryChannel.TEAMS_CHAT,
        routes=routes,
        guidance=TEAMS_GUIDANCE,
    )


register_publisher(DeliveryChannel.FILESYSTEM, build_filesystem_publisher)
register_publisher(DeliveryChannel.EMAIL, build_email_publisher)
register_publisher(DeliveryChannel.WEBHOOK, build_webhook_publisher)
register_publisher(DeliveryChannel.TEAMS_CHAT, build_teams_publisher)
