from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from hansard.domain.errors import SummarizationError

FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$")
OPENING = "{"
CLOSING = "}"


def strip_fences(text: str) -> str:
    stripped = text.strip()
    if "```" not in stripped:
        return stripped
    without_fences = FENCE.sub("", stripped)
    return without_fences.strip()


def extract_json_object(text: str) -> str | None:
    source = strip_fences(text)
    start = source.find(OPENING)
    if start < 0:
        return None
    depth = 0
    inside_string = False
    escaped = False
    for position in range(start, len(source)):
        character = source[position]
        if inside_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                inside_string = False
            continue
        if character == '"':
            inside_string = True
        elif character == OPENING:
            depth += 1
        elif character == CLOSING:
            depth -= 1
            if depth == 0:
                return source[start : position + 1]
    return None


def parse_json_object(text: str) -> dict[str, object]:
    candidate = extract_json_object(text)
    if candidate is None:
        raise SummarizationError(f"model answer contains no JSON object: {text[:200]!r}")
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise SummarizationError(f"model answer is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise SummarizationError("model answer must be a JSON object")
    return payload


def as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int | float):
        return str(value)
    return ""


def as_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def as_texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(text for text in (as_text(item) for item in value) if text)


def as_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = value.strip().lstrip("[").rstrip("]")
        if digits.isdigit():
            return int(digits)
    return None
