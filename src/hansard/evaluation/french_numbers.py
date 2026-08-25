from __future__ import annotations

import re

_UNITS: tuple[str, ...] = (
    "zéro",
    "un",
    "deux",
    "trois",
    "quatre",
    "cinq",
    "six",
    "sept",
    "huit",
    "neuf",
    "dix",
    "onze",
    "douze",
    "treize",
    "quatorze",
    "quinze",
    "seize",
)
_TENS: dict[int, str] = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}
_SCALES: tuple[tuple[int, str], ...] = (
    (1_000_000_000, "milliard"),
    (1_000_000, "million"),
    (1_000, "mille"),
)

MAX_SPELLED_DIGITS = 9

_THOUSAND_SEPARATOR = re.compile(r"(?<=\d)[\s.](?=\d{3}(?!\d))")
_CLOCK = re.compile(r"\b(\d{1,2})\s*h\s*(\d{1,2})?\b")
_ORDINAL = re.compile(r"\b(\d+)(ers|ères|res|èmes|emes|er|ère|re|ème|eme|nde|nds|nd|es|e)\b")
_DECIMAL = re.compile(r"\b(\d+),(\d+)\b")
_INTEGER = re.compile(r"(?<![^\W_])\d+(?![^\W_])")
_FEMININE_SUFFIXES = ("ère", "re", "ères", "res", "nde", "ndes")


def spell_cardinal(value: int) -> str:
    if value < 0:
        return f"moins-{spell_cardinal(-value)}"
    if value < 1000:
        return _below_thousand(value)
    for scale, name in _SCALES:
        if value >= scale:
            return _with_scale(value, scale, name)
    return _below_thousand(value)


def spell_cardinal_feminine(value: int) -> str:
    spelled = spell_cardinal(value)
    if spelled == "un" or spelled.endswith("-un"):
        return f"{spelled}e"
    return spelled


def spell_ordinal(value: int, *, feminine: bool = False) -> str:
    if value == 1:
        return "première" if feminine else "premier"
    stem = spell_cardinal(value)
    if stem.endswith(("vingts", "cents")):
        stem = stem[:-1]
    if stem.endswith("e"):
        stem = stem[:-1]
    elif stem.endswith("q"):
        stem = f"{stem}u"
    elif stem.endswith("f"):
        stem = f"{stem[:-1]}v"
    return f"{stem}ième"


def spell_digits(digits: str) -> str:
    return "-".join(_UNITS[int(digit)] for digit in digits)


def expand_numbers(text: str) -> str:
    result = _THOUSAND_SEPARATOR.sub("", text)
    result = _CLOCK.sub(_replace_clock, result)
    result = _ORDINAL.sub(_replace_ordinal, result)
    result = _DECIMAL.sub(_replace_decimal, result)
    return _INTEGER.sub(_replace_integer, result)


def _below_hundred(value: int) -> str:
    if value < 17:
        return _UNITS[value]
    if value < 20:
        return f"dix-{_UNITS[value - 10]}"
    tens = value // 10
    unit = value % 10
    if tens == 7:
        remainder = value - 60
        if remainder == 11:
            return "soixante-et-onze"
        return f"soixante-{_below_hundred(remainder)}"
    if tens == 9:
        return f"quatre-vingt-{_below_hundred(value - 80)}"
    if tens == 8:
        if unit == 0:
            return "quatre-vingts"
        return f"quatre-vingt-{_UNITS[unit]}"
    base = _TENS[tens]
    if unit == 0:
        return base
    if unit == 1:
        return f"{base}-et-un"
    return f"{base}-{_UNITS[unit]}"


def _below_thousand(value: int) -> str:
    if value < 100:
        return _below_hundred(value)
    hundreds = value // 100
    rest = value % 100
    head = "cent" if hundreds == 1 else f"{_UNITS[hundreds]}-cent"
    if rest == 0:
        return head if hundreds == 1 else f"{head}s"
    return f"{head}-{_below_hundred(rest)}"


def _with_scale(value: int, scale: int, name: str) -> str:
    count = value // scale
    rest = value % scale
    if name == "mille":
        head = "mille" if count == 1 else f"{spell_cardinal(count)}-mille"
    else:
        plural = "s" if count > 1 else ""
        head = f"{spell_cardinal(count)}-{name}{plural}"
    if rest == 0:
        return head
    return f"{head}-{spell_cardinal(rest)}"


def _replace_clock(match: re.Match[str]) -> str:
    hours = int(match.group(1))
    minutes = match.group(2)
    unit = "heure" if hours in {0, 1} else "heures"
    spoken = f"{spell_cardinal_feminine(hours)} {unit}"
    if minutes is None:
        return spoken
    return f"{spoken} {spell_cardinal_feminine(int(minutes))}"


def _replace_ordinal(match: re.Match[str]) -> str:
    value = int(match.group(1))
    suffix = match.group(2)
    spelled = spell_ordinal(value, feminine=suffix in _FEMININE_SUFFIXES)
    return f"{spelled}s" if suffix.endswith("s") else spelled


def _replace_decimal(match: re.Match[str]) -> str:
    whole = _replace_integer_text(match.group(1))
    fraction = match.group(2)
    spoken_fraction = spell_digits(fraction) if fraction.startswith("0") else _replace_integer_text(fraction)
    return f"{whole} virgule {spoken_fraction}"


def _replace_integer(match: re.Match[str]) -> str:
    return _replace_integer_text(match.group(0))


def _replace_integer_text(digits: str) -> str:
    if len(digits) > MAX_SPELLED_DIGITS or (len(digits) > 1 and digits.startswith("0")):
        return spell_digits(digits)
    return spell_cardinal(int(digits))
