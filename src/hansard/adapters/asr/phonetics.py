from __future__ import annotations

import unicodedata

from hansard.domain.language import MIXED, normalise_tag

_SHARED_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("ph", "f"),
    ("ck", "k"),
    ("qu", "k"),
    ("q", "k"),
    ("x", "ks"),
    ("y", "i"),
    ("w", "v"),
)

_FRENCH_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("eau", "o"),
    ("au", "o"),
    ("ou", "u"),
    ("oi", "oa"),
    ("ai", "e"),
    ("ei", "e"),
    ("eu", "e"),
    ("gn", "n"),
    ("ill", "i"),
    ("tion", "sion"),
    ("esse", "es"),
    ("ez", "e"),
    ("er", "e"),
    ("et", "e"),
)

_ENGLISH_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("ough", "of"),
    ("augh", "af"),
    ("tion", "shn"),
    ("sion", "shn"),
    ("igh", "i"),
    ("ee", "i"),
    ("ea", "i"),
    ("oo", "u"),
    ("th", "t"),
)

_SILENT_TAIL = "esdtxzpg"
_VOWELS = "aeiou"


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _collapse_repeats(text: str) -> str:
    collapsed: list[str] = []
    for char in text:
        if not collapsed or collapsed[-1] != char:
            collapsed.append(char)
    return "".join(collapsed)


def _soften_c_and_g(text: str) -> str:
    output: list[str] = []
    for index, char in enumerate(text):
        following = text[index + 1] if index + 1 < len(text) else ""
        if char == "c":
            output.append("s" if following in "eiy" else "k")
        elif char == "g":
            output.append("j" if following in "eiy" else "g")
        else:
            output.append(char)
    return "".join(output)


def sound_key(text: str, language: str = "en") -> str:
    return _key_with(text, _replacements_for(language))


def sound_keys(text: str, language: str = "en") -> tuple[str, ...]:
    if normalise_tag(language) != MIXED:
        return (sound_key(text, language),)
    keys = (_key_with(text, _ENGLISH_REPLACEMENTS), _key_with(text, _FRENCH_REPLACEMENTS))
    return keys if keys[0] != keys[1] else keys[:1]


def _replacements_for(language: str) -> tuple[tuple[str, str], ...]:
    return _FRENCH_REPLACEMENTS if language.lower().startswith("fr") else _ENGLISH_REPLACEMENTS


def _key_with(text: str, replacements: tuple[tuple[str, str], ...]) -> str:
    normalised = strip_accents(text).lower()
    normalised = "".join(char if char.isalnum() else " " for char in normalised)
    tokens: list[str] = []
    for token in normalised.split():
        current = token
        for source, target in replacements:
            current = current.replace(source, target)
        for source, target in _SHARED_REPLACEMENTS:
            current = current.replace(source, target)
        current = _soften_c_and_g(current)
        current = current.replace("h", "")
        current = _collapse_repeats(current)
        while len(current) > 2 and current[-1] in _SILENT_TAIL:
            current = current[:-1]
        if len(current) > 1:
            head, tail = current[0], current[1:]
            tail = "".join(char for char in tail if char not in _VOWELS) or tail
            current = head + tail
        if current:
            tokens.append(current)
    return " ".join(tokens)


def similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))
