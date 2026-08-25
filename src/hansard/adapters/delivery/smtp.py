from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from pydantic import SecretStr

from hansard.adapters.delivery.markup import to_html, to_plain_text
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Attachment, Payload

_RECIPIENT_SEPARATORS = re.compile(r"[,;\s]+")
_MINIMAL_ADDRESS = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
DEFAULT_MEDIA_TYPE = "application/octet-stream"


class MessageSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


def parse_recipients(address: str) -> tuple[str, ...]:
    candidates = [item for item in _RECIPIENT_SEPARATORS.split(address.strip()) if item]
    if not candidates:
        raise DeliveryError("email delivery target has no recipient address")
    invalid = [item for item in candidates if not _MINIMAL_ADDRESS.match(item)]
    if invalid:
        raise DeliveryError(f"email delivery target contains invalid addresses: {', '.join(invalid)}")
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


def split_media_type(media_type: str) -> tuple[str, str]:
    cleaned = (media_type or DEFAULT_MEDIA_TYPE).split(";", 1)[0].strip().lower()
    main, _, sub = cleaned.partition("/")
    if not main or not sub:
        return "application", "octet-stream"
    return main, sub


def attach_file(message: EmailMessage, attachment: Attachment) -> None:
    main_type, sub_type = split_media_type(attachment.media_type)
    message.add_attachment(
        attachment.content,
        maintype=main_type,
        subtype=sub_type,
        filename=attachment.filename,
    )


def build_message(
    sender: str,
    recipients: tuple[str, ...],
    payload: Payload,
    reply_to: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = payload.subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(to_plain_text(payload.body, payload.body_format))
    message.add_alternative(_html_document(payload), subtype="html")
    for attachment in payload.attachments:
        attach_file(message, attachment)
    return message


def _html_document(payload: Payload) -> str:
    return f"<html><body>{to_html(payload.body, payload.body_format)}</body></html>"


@dataclass(frozen=True, slots=True)
class AiosmtplibSender:
    host: str = "localhost"
    port: int = 25
    username: str | None = None
    password: SecretStr | None = None
    use_tls: bool = False
    start_tls: bool = True
    timeout_seconds: float = 30.0
    validate_certificates: bool = True

    async def send(self, message: EmailMessage) -> None:
        import aiosmtplib

        try:
            await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password.get_secret_value() if self.password is not None else None,
                use_tls=self.use_tls,
                start_tls=self.start_tls and not self.use_tls,
                timeout=self.timeout_seconds,
                validate_certs=self.validate_certificates,
            )
        except aiosmtplib.SMTPAuthenticationError as error:
            raise DeliveryError(
                f"SMTP server {self.host}:{self.port} rejected the credentials of "
                f"'{self.username or 'anonymous'}'; check HANSARD_DELIVERY__SMTP__USERNAME and "
                f"HANSARD_DELIVERY__SMTP__PASSWORD"
            ) from error
        except aiosmtplib.SMTPConnectError as error:
            raise DeliveryError(
                f"cannot connect to SMTP server {self.host}:{self.port}; check "
                f"HANSARD_DELIVERY__SMTP__HOST and HANSARD_DELIVERY__SMTP__PORT ({error})"
            ) from error
        except aiosmtplib.SMTPException as error:
            raise DeliveryError(
                f"SMTP server {self.host}:{self.port} refused the message: {error}"
            ) from error
        except (OSError, TimeoutError) as error:
            raise DeliveryError(
                f"SMTP transport failure against {self.host}:{self.port}: {type(error).__name__}: {error}"
            ) from error


@dataclass(frozen=True, slots=True)
class EmailPublisher:
    sender_address: str = "hansard@localhost"
    message_sender: MessageSender = field(default_factory=AiosmtplibSender)
    reply_to: str | None = None

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.EMAIL

    def compose(self, target: DeliveryTarget, payload: Payload) -> EmailMessage:
        recipients = parse_recipients(target.address)
        return build_message(self.sender_address, recipients, payload, self.reply_to)

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None:
        message = self.compose(target, payload)
        try:
            await self.message_sender.send(message)
        except DeliveryError:
            raise
        except Exception as error:
            raise DeliveryError(
                f"email delivery to '{target.address}' failed: {type(error).__name__}: {error}"
            ) from error
