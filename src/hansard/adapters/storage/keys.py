from __future__ import annotations

from pathlib import Path

from hansard.domain.errors import ArtifactKeyError

MAXIMUM_KEY_LENGTH = 512
FORBIDDEN_SEGMENTS = frozenset({"", ".", ".."})
FORBIDDEN_CHARACTERS = frozenset({"\\", ":", "\x00"})


def sanitised_key(key: str) -> str:
    if not key or len(key) > MAXIMUM_KEY_LENGTH:
        raise ArtifactKeyError(f"artifact key must be 1..{MAXIMUM_KEY_LENGTH} characters, got {len(key)}")
    if key != key.strip() or key.startswith("/"):
        raise ArtifactKeyError(f"artifact key must be relative and unpadded: {key!r}")
    if any(character in FORBIDDEN_CHARACTERS for character in key):
        raise ArtifactKeyError(f"artifact key contains a forbidden character: {key!r}")
    if any(character < " " or character == "\x7f" for character in key):
        raise ArtifactKeyError(f"artifact key contains a control character: {key!r}")
    segments = key.split("/")
    for segment in segments:
        if segment in FORBIDDEN_SEGMENTS or segment != segment.strip():
            raise ArtifactKeyError(f"artifact key segment {segment!r} is not allowed: {key!r}")
    return "/".join(segments)


def resolved_path(root: Path, key: str) -> Path:
    target = root / sanitised_key(key)
    base = root.resolve()
    resolved = target.resolve()
    if base != resolved and base not in resolved.parents:
        raise ArtifactKeyError(f"artifact key escapes the store root {base}: {key!r}")
    return target


def key_for_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
