from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from hansard.adapters.asr.phonetics import strip_accents
from hansard.adapters.summarization.stopwords import stopwords_for
from hansard.rendering.i18n import normalise_language

MINIMUM_CONTENT_LENGTH = 3
SENTENCE_TERMINATORS = ".!?…"

WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)*")
SENTENCE_BOUNDARY = re.compile("(?<=[.!?\\u2026])[\\s\\u00a0]+")
CAPITALISED_RUN = re.compile("[A-ZÀ-ÖØ-Þ][\\w\\u2019'-]*(?:\\s+[A-ZÀ-ÖØ-Þ][\\w\\u2019'-]*)*")

ENGLISH_SUFFIXES: tuple[tuple[str, int], ...] = (
    ("sses", 2),
    ("ies", 1),
    ("ing", 4),
    ("edly", 4),
    ("ed", 4),
    ("ly", 4),
    ("s", 3),
)

FRENCH_SUFFIXES: tuple[tuple[str, int], ...] = (
    ("aient", 4),
    ("erait", 4),
    ("erons", 4),
    ("eront", 4),
    ("ement", 5),
    ("ions", 4),
    ("iez", 4),
    ("ons", 4),
    ("ez", 4),
    ("er", 4),
    ("ait", 4),
    ("ais", 4),
    ("ees", 3),
    ("es", 3),
    ("s", 3),
    ("x", 3),
)

SUFFIXES_BY_LANGUAGE: Mapping[str, tuple[tuple[str, int], ...]] = {
    "en": ENGLISH_SUFFIXES,
    "fr": FRENCH_SUFFIXES,
}


def resolve_language(*candidates: str | None) -> str:
    for candidate in candidates:
        if candidate and candidate.strip():
            return normalise_language(candidate)
    return normalise_language(None)


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def fold(text: str) -> str:
    return strip_accents(text).casefold()


APOSTROPHES = "\u2019\u02bc\u00b4`\u201b"


def fold_for_matching(text: str) -> str:
    characters: list[str] = []
    for character in text:
        if character in APOSTROPHES:
            characters.append("'")
            continue
        base = strip_accents(character) or character
        lowered = base.lower()
        characters.append(lowered if len(lowered) == len(character) else base)
    return "".join(characters)


def tokenise(text: str) -> tuple[str, ...]:
    return tuple(WORD_PATTERN.findall(fold(text)))


def lexical_stem(token: str, language: str) -> str:
    if token.isdigit():
        return token
    suffixes = SUFFIXES_BY_LANGUAGE.get(language, ENGLISH_SUFFIXES)
    for suffix, minimum_stem in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= minimum_stem:
            return token[: -len(suffix)]
    return token


def is_content_word(token: str, language: str) -> bool:
    if token in stopwords_for(language):
        return False
    return token.isdigit() or len(token) >= MINIMUM_CONTENT_LENGTH


def content_tokens(text: str, language: str) -> tuple[str, ...]:
    return tuple(token for token in tokenise(text) if is_content_word(token, language))


def content_terms(text: str, language: str) -> tuple[str, ...]:
    return tuple(lexical_stem(token, language) for token in content_tokens(text, language))


def term_set(text: str, language: str) -> frozenset[str]:
    return frozenset(content_terms(text, language))


def term_counts(text: str, language: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for term in content_terms(text, language):
        counts[term] = counts.get(term, 0) + 1
    return counts


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    first = set(left)
    second = set(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def coverage(claim: Iterable[str], support: Iterable[str]) -> float:
    terms = tuple(claim)
    if not terms:
        return 1.0
    available = set(support)
    return sum(1 for term in terms if term in available) / len(terms)


def split_sentences(text: str) -> tuple[str, ...]:
    cleaned = collapse_whitespace(text)
    if not cleaned:
        return ()
    parts = [part.strip() for part in SENTENCE_BOUNDARY.split(cleaned)]
    return tuple(part for part in parts if part)


def truncate(text: str, limit: int) -> str:
    cleaned = collapse_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[: limit - 1].rsplit(" ", 1)[0]
    return f"{cut or cleaned[: limit - 1]}…"


def numbers_in(text: str) -> tuple[str, ...]:
    return tuple(NUMBER_PATTERN.findall(text))


def capitalised_runs(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(0)
        for match in CAPITALISED_RUN.finditer(text)
        if match.start() > 0 or " " in match.group(0)
    )


def join_sentences(sentences: Sequence[str]) -> str:
    return " ".join(sentence.strip() for sentence in sentences if sentence.strip())
