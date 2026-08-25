from __future__ import annotations

import re

_UNITS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_MULTIPLIERS: dict[str, int] = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}
_ORDINAL_WORDS: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
    "fiftieth": 50,
    "sixtieth": 60,
    "seventieth": 70,
    "eightieth": 80,
    "ninetieth": 90,
    "hundredth": 100,
    "thousandth": 1_000,
    "millionth": 1_000_000,
}
_CURRENCY_WORDS: dict[str, str] = {
    "dollar": "$",
    "dollars": "$",
    "pound": "£",
    "pounds": "£",
    "euro": "€",
    "euros": "€",
}
_ORDINAL_MULTIPLIERS: dict[str, int] = {"hundredth": 100, "thousandth": 1_000, "millionth": 1_000_000}
_PERCENT_WORDS = frozenset({"percent", "per cent"})
_CONNECTOR = "and"
_ORDINAL_SUFFIXES: dict[int, str] = {1: "st", 2: "nd", 3: "rd"}


def ordinal_suffix(value: int) -> str:
    if value % 100 in {11, 12, 13}:
        return "th"
    return _ORDINAL_SUFFIXES.get(value % 10, "th")


def words_to_digits(text: str) -> str:
    tokens = text.split()
    output: list[str] = []
    index = 0
    while index < len(tokens):
        consumed, rendered = _consume_number(tokens, index)
        if consumed == 0:
            output.append(tokens[index])
            index += 1
            continue
        output.append(rendered)
        index += consumed
    return " ".join(output)


def _consume_number(tokens: list[str], start: int) -> tuple[int, str]:
    total = 0
    current = 0
    index = start
    seen_value = False
    ordinal = False
    while index < len(tokens):
        token = tokens[index]
        if token in _UNITS:
            current += _UNITS[token]
        elif token in _MULTIPLIERS:
            multiplier = _MULTIPLIERS[token]
            if multiplier == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * multiplier
                current = 0
        elif token in _ORDINAL_MULTIPLIERS:
            scale = _ORDINAL_MULTIPLIERS[token]
            if scale == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * scale
                current = 0
            ordinal = True
            seen_value = True
            index += 1
            break
        elif token in _ORDINAL_WORDS:
            current += _ORDINAL_WORDS[token]
            ordinal = True
            seen_value = True
            index += 1
            break
        elif token == _CONNECTOR and seen_value and _continues_number(tokens, index + 1):
            index += 1
            continue
        else:
            break
        seen_value = True
        index += 1
    if not seen_value:
        return 0, ""
    value = total + current
    consumed = index - start
    if ordinal:
        return consumed, f"{value}{ordinal_suffix(value)}"
    return _apply_suffix_word(tokens, index, consumed, value)


def _apply_suffix_word(tokens: list[str], index: int, consumed: int, value: int) -> tuple[int, str]:
    if index < len(tokens):
        follower = tokens[index]
        if follower in _CURRENCY_WORDS:
            return consumed + 1, f"{_CURRENCY_WORDS[follower]}{value}"
        if follower in _PERCENT_WORDS:
            return consumed + 1, f"{value}%"
    return consumed, str(value)


def _continues_number(tokens: list[str], index: int) -> bool:
    if index >= len(tokens):
        return False
    token = tokens[index]
    return token in _UNITS or token in _MULTIPLIERS or token in _ORDINAL_WORDS


def normalize_digit_groups(text: str) -> str:
    return re.sub(r"(\d),(\d)", r"\1\2", text)
