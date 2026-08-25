from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from hansard.adapters.summarization.text import fold_for_matching

Resolver = Callable[[re.Match[str], date], date | None]

FRENCH_MONTHS: Mapping[str, int] = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}

ENGLISH_MONTHS: Mapping[str, int] = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

FRENCH_WEEKDAYS: Mapping[str, int] = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
}

ENGLISH_WEEKDAYS: Mapping[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}

FRIDAY = 4


@dataclass(frozen=True, slots=True)
class DueDate:
    raw: str
    resolved: date | None = None

    @property
    def value(self) -> str:
        return self.resolved.isoformat() if self.resolved is not None else self.raw


@dataclass(frozen=True, slots=True)
class DatePattern:
    pattern: re.Pattern[str]
    resolve: Resolver


def _weekday_after(reference: date, weekday: int, following_week: bool) -> date:
    if following_week:
        next_monday = reference + timedelta(days=7 - reference.weekday())
        return next_monday + timedelta(days=weekday)
    ahead = (weekday - reference.weekday()) % 7
    return reference + timedelta(days=ahead or 7)


def _end_of_week(reference: date, weeks_ahead: int = 0) -> date:
    ahead = (FRIDAY - reference.weekday()) % 7
    return reference + timedelta(days=ahead + 7 * weeks_ahead)


def _end_of_month(reference: date, months_ahead: int = 0) -> date:
    month = reference.month + months_ahead
    year = reference.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _calendar_date(reference: date, day: int, month: int, year: int | None) -> date | None:
    try:
        if year is not None:
            return date(year, month, day)
        candidate = date(reference.year, month, day)
    except ValueError:
        return None
    if candidate < reference:
        try:
            return date(reference.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _day_of_month(reference: date, day: int) -> date | None:
    try:
        candidate = date(reference.year, reference.month, day)
    except ValueError:
        return None
    if candidate >= reference:
        return candidate
    following = _end_of_month(reference) + timedelta(days=1)
    try:
        return date(following.year, following.month, day)
    except ValueError:
        return None


def _full_year(fragment: str | None) -> int | None:
    if not fragment:
        return None
    digits = fragment.strip()
    if len(digits) == 2:
        return 2000 + int(digits)
    return int(digits)


def _named_month(match: re.Match[str], reference: date, months: Mapping[str, int]) -> date | None:
    month = months.get(match.group("month"))
    if month is None:
        return None
    return _calendar_date(
        reference,
        int(match.group("day")),
        month,
        _full_year(match.groupdict().get("year")),
    )


def _french_named_month(match: re.Match[str], reference: date) -> date | None:
    return _named_month(match, reference, FRENCH_MONTHS)


def _english_named_month(match: re.Match[str], reference: date) -> date | None:
    return _named_month(match, reference, ENGLISH_MONTHS)


def _iso(match: re.Match[str], _reference: date) -> date | None:
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _french_numeric(match: re.Match[str], reference: date) -> date | None:
    return _calendar_date(
        reference,
        int(match.group("day")),
        int(match.group("month")),
        _full_year(match.groupdict().get("year")),
    )


def _english_numeric(match: re.Match[str], reference: date) -> date | None:
    return _calendar_date(
        reference,
        int(match.group("day")),
        int(match.group("month")),
        _full_year(match.groupdict().get("year")),
    )


def _french_weekday(match: re.Match[str], reference: date) -> date | None:
    weekday = FRENCH_WEEKDAYS.get(match.group("weekday"))
    if weekday is None:
        return None
    return _weekday_after(reference, weekday, bool(match.groupdict().get("next")))


def _english_weekday(match: re.Match[str], reference: date) -> date | None:
    weekday = ENGLISH_WEEKDAYS.get(match.group("weekday"))
    if weekday is None:
        return None
    return _weekday_after(reference, weekday, bool(match.groupdict().get("next")))


def _offset(match: re.Match[str], reference: date, days: int, weeks: int, months: int) -> date | None:
    amount = int(match.group("amount"))
    unit = match.group("unit")
    if unit.startswith(("jour", "day")):
        return reference + timedelta(days=amount * days)
    if unit.startswith(("semaine", "week")):
        return reference + timedelta(weeks=amount * weeks)
    return _end_of_month(reference, amount * months)


def _french_offset(match: re.Match[str], reference: date) -> date | None:
    return _offset(match, reference, 1, 1, 1)


def _english_offset(match: re.Match[str], reference: date) -> date | None:
    return _offset(match, reference, 1, 1, 1)


def _tomorrow(_match: re.Match[str], reference: date) -> date | None:
    return reference + timedelta(days=1)


def _day_after_tomorrow(_match: re.Match[str], reference: date) -> date | None:
    return reference + timedelta(days=2)


def _same_day(_match: re.Match[str], reference: date) -> date | None:
    return reference


def _this_week_end(_match: re.Match[str], reference: date) -> date | None:
    return _end_of_week(reference)


def _next_week_end(_match: re.Match[str], reference: date) -> date | None:
    return _end_of_week(reference, 1)


def _this_month_end(_match: re.Match[str], reference: date) -> date | None:
    return _end_of_month(reference)


def _next_month_end(_match: re.Match[str], reference: date) -> date | None:
    return _end_of_month(reference, 1)


def _bare_day(match: re.Match[str], reference: date) -> date | None:
    return _day_of_month(reference, int(match.group("day")))


FRENCH_MONTH_NAMES = "|".join(FRENCH_MONTHS)
ENGLISH_MONTH_NAMES = "|".join(sorted(ENGLISH_MONTHS, key=len, reverse=True))
FRENCH_WEEKDAY_NAMES = "|".join(FRENCH_WEEKDAYS)
ENGLISH_WEEKDAY_NAMES = "|".join(ENGLISH_WEEKDAYS)

FRENCH_DATE_PATTERNS: tuple[DatePattern, ...] = (
    DatePattern(re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b"), _iso),
    DatePattern(
        re.compile(
            rf"\b(?:le\s+)?(?P<day>\d{{1,2}})(?:er)?\s+(?P<month>{FRENCH_MONTH_NAMES})"
            rf"(?:\s+(?P<year>\d{{4}}))?\b"
        ),
        _french_named_month,
    ),
    DatePattern(
        re.compile(r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})(?:/(?P<year>\d{2,4}))?\b"),
        _french_numeric,
    ),
    DatePattern(re.compile(r"\bapres-demain\b"), _day_after_tomorrow),
    DatePattern(re.compile(r"\bdemain\b"), _tomorrow),
    DatePattern(re.compile(r"\b(?:aujourd'hui|ce soir|en fin de journee)\b"), _same_day),
    DatePattern(
        re.compile(rf"\b(?:d'ici\s+|avant\s+|pour\s+)?(?P<weekday>{FRENCH_WEEKDAY_NAMES})(?P<next>\s+prochain)?\b"),
        _french_weekday,
    ),
    DatePattern(re.compile(r"\b(?:la\s+)?semaine\s+prochaine\b"), _next_week_end),
    DatePattern(
        re.compile(r"\b(?:d'ici\s+)?(?:la\s+)?fin\s+(?:de\s+)?(?:la\s+)?semaine\b"),
        _this_week_end,
    ),
    DatePattern(re.compile(r"\b(?:d'ici\s+)?cette semaine\b"), _this_week_end),
    DatePattern(re.compile(r"\b(?:d'ici\s+)?(?:la\s+)?fin\s+du\s+mois\b"), _this_month_end),
    DatePattern(re.compile(r"\ble\s+mois\s+prochain\b"), _next_month_end),
    DatePattern(
        re.compile(r"\bdans\s+(?P<amount>\d+)\s+(?P<unit>jours?|semaines?|mois)\b"),
        _french_offset,
    ),
    DatePattern(
        re.compile(r"\b(?:le|avant le|d'ici le|pour le)\s+(?P<day>\d{1,2})\b(?!\s*[hm:])"),
        _bare_day,
    ),
)

ENGLISH_DATE_PATTERNS: tuple[DatePattern, ...] = (
    DatePattern(re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b"), _iso),
    DatePattern(
        re.compile(
            rf"\b(?P<month>{ENGLISH_MONTH_NAMES})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
            rf"(?:,?\s+(?P<year>\d{{4}}))?\b"
        ),
        _english_named_month,
    ),
    DatePattern(
        re.compile(
            rf"\b(?:the\s+)?(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+of\s+(?P<month>{ENGLISH_MONTH_NAMES})"
            rf"(?:,?\s+(?P<year>\d{{4}}))?\b"
        ),
        _english_named_month,
    ),
    DatePattern(
        re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{2,4}))?\b"),
        _english_numeric,
    ),
    DatePattern(re.compile(r"\bthe day after tomorrow\b"), _day_after_tomorrow),
    DatePattern(re.compile(r"\btomorrow\b"), _tomorrow),
    DatePattern(re.compile(r"\b(?:today|by eod|end of (?:the )?day|tonight)\b"), _same_day),
    DatePattern(
        re.compile(
            rf"\b(?:(?P<next>next)\s+|by\s+|on\s+|before\s+)?(?P<weekday>{ENGLISH_WEEKDAY_NAMES})\b"
        ),
        _english_weekday,
    ),
    DatePattern(re.compile(r"\bnext week\b"), _next_week_end),
    DatePattern(
        re.compile(r"\b(?:by\s+)?(?:eow|end of (?:the )?week|this week)\b"),
        _this_week_end,
    ),
    DatePattern(
        re.compile(r"\b(?:by\s+)?(?:eom|end of (?:the )?month|month end)\b"),
        _this_month_end,
    ),
    DatePattern(re.compile(r"\bnext month\b"), _next_month_end),
    DatePattern(
        re.compile(r"\bin\s+(?P<amount>\d+)\s+(?P<unit>days?|weeks?|months?)\b"),
        _english_offset,
    ),
    DatePattern(re.compile(r"\b(?:by|on|before) the\s+(?P<day>\d{1,2})(?:st|nd|rd|th)\b"), _bare_day),
)

DATE_PATTERNS_BY_LANGUAGE: Mapping[str, tuple[DatePattern, ...]] = {
    "fr": FRENCH_DATE_PATTERNS,
    "en": ENGLISH_DATE_PATTERNS,
}


def date_patterns_for(language: str) -> tuple[DatePattern, ...]:
    known = DATE_PATTERNS_BY_LANGUAGE.get(language)
    if known is not None:
        return known
    return FRENCH_DATE_PATTERNS + ENGLISH_DATE_PATTERNS


def _candidates(text: str, patterns: Sequence[DatePattern]) -> list[tuple[int, int, re.Match[str], Resolver]]:
    found: list[tuple[int, int, re.Match[str], Resolver]] = []
    for entry in patterns:
        for match in entry.pattern.finditer(text):
            found.append((match.start(), -(match.end() - match.start()), match, entry.resolve))
    return sorted(found, key=lambda item: (item[0], item[1]))


def _widest_overlapping(
    candidates: Sequence[tuple[int, int, re.Match[str], Resolver]],
) -> tuple[int, int, re.Match[str], Resolver]:
    earliest = candidates[0]
    earliest_end = earliest[0] - earliest[1]
    overlapping = [item for item in candidates if item[0] <= earliest_end]
    return max(overlapping, key=lambda item: (item[0] - item[1], -item[0]))


def extract_due_date(text: str, language: str, reference: date | None = None) -> DueDate | None:
    candidates = _candidates(fold_for_matching(text), date_patterns_for(language))
    if not candidates:
        return None
    start, negative_length, match, resolve = _widest_overlapping(candidates)
    return DueDate(
        raw=text[start : start - negative_length].strip(),
        resolved=resolve(match, reference) if reference is not None else None,
    )
