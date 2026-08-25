from __future__ import annotations

from pathlib import Path

import pytest

from hansard.adapters.delivery.filesystem import (
    FilesystemPublisher,
    body_filename,
    resolve_output_directory,
    sanitise_filename,
)
from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Attachment, Payload

TRAVERSAL_DIRECTORIES = [
    "../escape",
    "../../etc",
    "minutes/../../etc",
    "..\\..\\windows",
    "/etc/passwd",
    "\\\\server\\share",
    "C:\\Windows",
]

TRAVERSAL_FILENAMES = [
    ("../../etc/passwd", "passwd"),
    ("..\\..\\windows\\system32\\config", "config"),
    ("/absolute/secret.txt", "secret.txt"),
    ("..", "attachment"),
    ("", "attachment"),
    ("   ", "attachment"),
    ("normal name.md", "normal name.md"),
    ("weird:name*.txt", "weird_name_.txt"),
]


def target(address: str) -> DeliveryTarget:
    return DeliveryTarget(channel=DeliveryChannel.FILESYSTEM, address=address)


@pytest.mark.parametrize("address", TRAVERSAL_DIRECTORIES)
def test_directory_traversal_is_refused(tmp_path: Path, address: str) -> None:
    with pytest.raises(DeliveryError):
        resolve_output_directory(tmp_path, address)


@pytest.mark.parametrize(("raw", "expected"), TRAVERSAL_FILENAMES)
def test_filename_sanitisation(raw: str, expected: str) -> None:
    assert sanitise_filename(raw) == expected


def test_null_byte_and_control_characters_are_replaced() -> None:
    assert sanitise_filename("bad\x00name\x1f.txt") == "bad_name_.txt"


def test_windows_reserved_names_are_prefixed() -> None:
    assert sanitise_filename("CON.txt") == "_CON.txt"


def test_nested_directories_are_allowed(tmp_path: Path) -> None:
    directory = resolve_output_directory(tmp_path, "2026/august/board")
    assert directory == (tmp_path / "2026" / "august" / "board").resolve()


def test_absolute_directory_allowed_when_enabled(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    assert resolve_output_directory(tmp_path, str(elsewhere), allow_absolute_paths=True) == elsewhere


def test_empty_address_uses_root(tmp_path: Path) -> None:
    assert resolve_output_directory(tmp_path, "  ") == tmp_path


def test_body_filename_uses_format_extension() -> None:
    assert body_filename(Payload(subject="Weekly sync", body="x")) == "Weekly sync.md"
    assert body_filename(Payload(subject="", body="x", body_format="html")) == "minutes.html"


async def test_publish_writes_body_and_attachments(tmp_path: Path, payload: Payload) -> None:
    publisher = FilesystemPublisher(root=tmp_path)

    await publisher.publish(target("meetings/board"), payload)

    directory = tmp_path / "meetings" / "board"
    assert (directory / "Board meeting 2026-08-25.md").read_text() == payload.body
    assert (directory / "transcript.txt").read_bytes() == b"hello"
    assert (directory / "minutes.pdf").read_bytes() == b"%PDF-1.4"


async def test_publish_keeps_traversing_attachments_inside_the_directory(tmp_path: Path) -> None:
    publisher = FilesystemPublisher(root=tmp_path)
    payload = Payload(
        subject="Escape",
        body="body",
        attachments=(Attachment(filename="../../evil.sh", media_type="text/plain", content=b"rm -rf /"),),
    )

    await publisher.publish(target("out"), payload)

    written = sorted(path.name for path in (tmp_path / "out").iterdir())
    assert written == ["Escape.md", "evil.sh"]
    assert not (tmp_path.parent / "evil.sh").exists()


async def test_duplicate_attachment_names_do_not_overwrite(tmp_path: Path) -> None:
    publisher = FilesystemPublisher(root=tmp_path)
    payload = Payload(
        subject="Dupes",
        body="body",
        attachments=(
            Attachment(filename="notes.txt", media_type="text/plain", content=b"first"),
            Attachment(filename="notes.txt", media_type="text/plain", content=b"second"),
        ),
    )

    await publisher.publish(target(""), payload)

    assert (tmp_path / "notes.txt").read_bytes() == b"first"
    assert (tmp_path / "notes-1.txt").read_bytes() == b"second"


def test_channel_is_filesystem() -> None:
    assert FilesystemPublisher().channel is DeliveryChannel.FILESYSTEM
