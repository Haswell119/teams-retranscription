from __future__ import annotations

from email.message import EmailMessage

import pytest

from hansard.adapters.delivery.smtp import (
    EmailPublisher,
    parse_recipients,
    split_media_type,
)
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload


class RecordingSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)
        if self.error is not None:
            raise self.error


def target(address: str) -> DeliveryTarget:
    return DeliveryTarget(channel=DeliveryChannel.EMAIL, address=address)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("a@example.org", ("a@example.org",)),
        ("a@example.org,b@example.org", ("a@example.org", "b@example.org")),
        ("a@example.org; b@example.org", ("a@example.org", "b@example.org")),
        (" a@example.org ;;  b@example.org , c@example.org ",
         ("a@example.org", "b@example.org", "c@example.org")),
        ("a@example.org a@example.org", ("a@example.org",)),
    ],
)
def test_parse_recipients(address: str, expected: tuple[str, ...]) -> None:
    assert parse_recipients(address) == expected


@pytest.mark.parametrize("address", ["", "   ", "not-an-address", "missing@domain", "a@b@c.org"])
def test_invalid_recipients_are_refused(address: str) -> None:
    with pytest.raises(DeliveryError):
        parse_recipients(address)


@pytest.mark.parametrize(
    ("media_type", "expected"),
    [
        ("text/plain", ("text", "plain")),
        ("application/pdf; charset=utf-8", ("application", "pdf")),
        ("nonsense", ("application", "octet-stream")),
        ("", ("application", "octet-stream")),
    ],
)
def test_split_media_type(media_type: str, expected: tuple[str, str]) -> None:
    assert split_media_type(media_type) == expected


async def test_multipart_structure_and_headers(payload: Payload) -> None:
    sender = RecordingSender()
    publisher = EmailPublisher(sender_address="hansard@council.example", message_sender=sender)

    await publisher.publish(target("clerk@council.example, mayor@council.example"), payload)

    message = sender.messages[0]
    assert message["To"] == "clerk@council.example, mayor@council.example"
    assert message["From"] == "hansard@council.example"
    assert message["Subject"] == payload.subject
    assert message.get_content_type() == "multipart/mixed"
    alternative = message.get_payload(0)
    assert alternative.get_content_type() == "multipart/alternative"
    subtypes = [part.get_content_type() for part in alternative.get_payload()]
    assert subtypes == ["text/plain", "text/html"]
    html_part = alternative.get_payload(1).get_content()
    assert "<li>decision one</li>" in html_part
    assert "<strong>Hansard</strong>" in html_part


async def test_attachments_keep_their_media_types(payload: Payload) -> None:
    sender = RecordingSender()
    publisher = EmailPublisher(message_sender=sender)

    await publisher.publish(target("clerk@council.example"), payload)

    attachments = list(sender.messages[0].iter_attachments())
    assert [item.get_content_type() for item in attachments] == ["text/plain", "application/pdf"]
    assert [item.get_filename() for item in attachments] == ["transcript.txt", "minutes.pdf"]
    assert attachments[1].get_content() == b"%PDF-1.4"


async def test_html_payload_gets_a_plain_text_fallback() -> None:
    sender = RecordingSender()
    publisher = EmailPublisher(message_sender=sender)
    payload = Payload(subject="HTML", body="<h1>Agenda</h1><p>Item&nbsp;one</p>", body_format="html")

    await publisher.publish(target("clerk@council.example"), payload)

    alternative = sender.messages[0]
    assert alternative.get_content_type() == "multipart/alternative"
    assert "Agenda" in alternative.get_payload(0).get_content()
    assert "<h1>" not in alternative.get_payload(0).get_content()


async def test_transport_errors_become_delivery_errors(payload: Payload) -> None:
    publisher = EmailPublisher(message_sender=RecordingSender(error=OSError("connection reset")))

    with pytest.raises(DeliveryError) as failure:
        await publisher.publish(target("clerk@council.example"), payload)

    assert "clerk@council.example" in str(failure.value)
    assert "connection reset" in str(failure.value)


async def test_delivery_errors_from_the_sender_pass_through(payload: Payload) -> None:
    publisher = EmailPublisher(message_sender=RecordingSender(error=DeliveryError("relay refused")))

    with pytest.raises(DeliveryError, match="relay refused"):
        await publisher.publish(target("clerk@council.example"), payload)


def test_channel_is_email() -> None:
    assert EmailPublisher(message_sender=RecordingSender()).channel is DeliveryChannel.EMAIL
