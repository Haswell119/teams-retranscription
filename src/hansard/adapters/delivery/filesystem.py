from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import Payload

_UNSAFE_CHARACTERS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
_COLLAPSIBLE = re.compile(r"[\s]+")
_TRAVERSAL_PARTS = frozenset({"..", "...."})
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_MAX_NAME_LENGTH = 180

BODY_EXTENSIONS = {
    "markdown": ".md",
    "md": ".md",
    "html": ".html",
    "text/html": ".html",
    "text": ".txt",
    "json": ".json",
}


def sanitise_filename(name: str, fallback: str = "attachment") -> str:
    tail = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_CHARACTERS.sub("_", tail)
    cleaned = _COLLAPSIBLE.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned or cleaned in _TRAVERSAL_PARTS:
        return fallback
    stem = cleaned.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:_MAX_NAME_LENGTH]


def _validated_parts(address: str) -> tuple[str, ...]:
    candidate = PurePosixPath(address.replace("\\", "/"))
    parts: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise DeliveryError(f"delivery directory '{address}' must not contain '..' path segments")
        safe = sanitise_filename(part, fallback="")
        if not safe:
            raise DeliveryError(f"delivery directory '{address}' contains an unusable path segment '{part}'")
        parts.append(safe)
    return tuple(parts)


def resolve_output_directory(root: Path, address: str, allow_absolute_paths: bool = False) -> Path:
    text = address.strip()
    if not text:
        return root
    looks_absolute = text.startswith(("/", "\\")) or (len(text) > 1 and text[1] == ":")
    if looks_absolute:
        if not allow_absolute_paths:
            raise DeliveryError(
                f"absolute delivery directory '{text}' is refused; use a path relative to "
                f"HANSARD_DELIVERY__OUTPUT_DIR or enable allow_absolute_paths"
            )
        return Path(text)
    resolved_root = root.resolve()
    directory = resolved_root.joinpath(*_validated_parts(text)).resolve()
    if directory != resolved_root and resolved_root not in directory.parents:
        raise DeliveryError(f"delivery directory '{text}' escapes the artefact root {resolved_root}")
    return directory


def body_filename(payload: Payload, fallback_stem: str = "minutes") -> str:
    stem = sanitise_filename(payload.subject, fallback=fallback_stem).rstrip(".") or fallback_stem
    extension = BODY_EXTENSIONS.get(payload.body_format.lower(), ".txt")
    if stem.lower().endswith(extension):
        return stem
    return f"{stem}{extension}"


def unique_path(directory: Path, filename: str, taken: set[str]) -> Path:
    stem, dot, suffix = filename.rpartition(".")
    base = stem if dot else filename
    tail = f".{suffix}" if dot else ""
    candidate = filename
    index = 1
    while candidate.lower() in taken:
        candidate = f"{base}-{index}{tail}"
        index += 1
    taken.add(candidate.lower())
    return directory / candidate


@dataclass(frozen=True, slots=True)
class FilesystemPublisher:
    root: Path = Path("artifacts")
    allow_absolute_paths: bool = False
    encoding: str = "utf-8"

    @property
    def channel(self) -> DeliveryChannel:
        return DeliveryChannel.FILESYSTEM

    def plan(self, target: DeliveryTarget, payload: Payload) -> tuple[Path, tuple[tuple[Path, bytes], ...]]:
        directory = resolve_output_directory(self.root, target.address, self.allow_absolute_paths)
        taken: set[str] = set()
        body_path = unique_path(directory, body_filename(payload), taken)
        files = [(body_path, payload.body.encode(self.encoding))]
        files.extend(
            (unique_path(directory, sanitise_filename(item.filename), taken), item.content)
            for item in payload.attachments
        )
        return directory, tuple(files)

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None:
        directory, files = self.plan(target, payload)
        try:
            await asyncio.to_thread(self._write, directory, files)
        except OSError as error:
            raise DeliveryError(f"cannot write minutes into {directory}: {error}") from error

    def _write(self, directory: Path, files: tuple[tuple[Path, bytes], ...]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for path, content in files:
            path.write_bytes(content)
