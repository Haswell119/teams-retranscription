from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import jiwer

from hansard.adapters.language.markers import (
    ENGLISH_FUNCTION_WORDS,
    ENGLISH_ONLY_WORDS,
    FRENCH_FUNCTION_WORDS,
    FRENCH_ONLY_WORDS,
)

PROPER_NOUN = "proper_noun"
NUMBER = "number"
FILLER = "filler"
CODE_SWITCHED = "code_switched"
FUNCTION_WORD = "function_word"
CONTENT_WORD = "content_word"

CATEGORIES: tuple[str, ...] = (
    PROPER_NOUN,
    NUMBER,
    CODE_SWITCHED,
    FILLER,
    FUNCTION_WORD,
    CONTENT_WORD,
)

_DIGIT = re.compile(r"\d")
_SENTENCE_START = re.compile(r"(?:^|[.!?…:;]\s+|\n)\s*$")
_TOKEN = re.compile(r"[^\W\d_]+(?:[\u0027\u2019-][^\W\d_]+)*|\d+(?:[.,]\d+)*", re.UNICODE)

_FILLERS: frozenset[str] = frozenset(
    (
        "euh",
        "euhm",
        "heu",
        "hein",
        "ben",
        "bah",
        "hum",
        "hm",
        "hmm",
        "mmh",
        "mm",
        "mhm",
        "uh",
        "um",
        "erm",
        "ah",
        "oh",
        "bon",
        "voila",
        "quoi",
    )
)

_NUMBER_WORDS: frozenset[str] = frozenset(
    (
        "zero",
        "un",
        "une",
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
        "vingt",
        "trente",
        "quarante",
        "cinquante",
        "soixante",
        "cent",
        "cents",
        "mille",
        "million",
        "millions",
        "milliard",
        "milliards",
        "one",
        "two",
        "three",
        "four",
        "five",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "billion",
    )
)


@dataclass(frozen=True, slots=True)
class CategoryCounts:
    category: str
    reference_words: int = 0
    hits: int = 0
    substitutions: int = 0
    deletions: int = 0

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions

    @property
    def error_rate(self) -> float:
        return self.errors / self.reference_words if self.reference_words else 0.0

    @property
    def recall(self) -> float:
        return self.hits / self.reference_words if self.reference_words else 0.0

    def __add__(self, other: CategoryCounts) -> CategoryCounts:
        return CategoryCounts(
            category=self.category,
            reference_words=self.reference_words + other.reference_words,
            hits=self.hits + other.hits,
            substitutions=self.substitutions + other.substitutions,
            deletions=self.deletions + other.deletions,
        )


@dataclass(frozen=True, slots=True)
class Decomposition:
    categories: tuple[CategoryCounts, ...]
    insertions: int = 0
    reference_words: int = 0

    def counts_for(self, category: str) -> CategoryCounts:
        for item in self.categories:
            if item.category == category:
                return item
        return CategoryCounts(category=category)

    @property
    def substitutions(self) -> int:
        return sum(item.substitutions for item in self.categories)

    @property
    def deletions(self) -> int:
        return sum(item.deletions for item in self.categories)

    @property
    def error_rate(self) -> float:
        errors = self.substitutions + self.deletions + self.insertions
        return errors / self.reference_words if self.reference_words else 0.0

    def __add__(self, other: Decomposition) -> Decomposition:
        merged = {item.category: item for item in self.categories}
        for item in other.categories:
            merged[item.category] = merged.get(item.category, CategoryCounts(item.category)) + item
        ordered = tuple(merged[name] for name in CATEGORIES if name in merged)
        return Decomposition(
            categories=ordered,
            insertions=self.insertions + other.insertions,
            reference_words=self.reference_words + other.reference_words,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "reference_words": self.reference_words,
            "insertions": self.insertions,
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "categories": {
                item.category: {
                    "reference_words": item.reference_words,
                    "hits": item.hits,
                    "substitutions": item.substitutions,
                    "deletions": item.deletions,
                    "error_rate_percent": round(item.error_rate * 100, 2),
                    "recall_percent": round(item.recall * 100, 2),
                }
                for item in self.categories
            },
        }


def fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in stripped if not unicodedata.combining(character))


def proper_nouns(raw: str) -> frozenset[str]:
    found: set[str] = set()
    for match in _TOKEN.finditer(raw):
        token = match.group(0)
        if not token[:1].isupper():
            continue
        prefix = raw[: match.start()]
        if _SENTENCE_START.search(prefix) or not prefix.strip():
            continue
        found.add(fold(token))
    return frozenset(found)


def classify(token: str, language: str, names: frozenset[str], glossary: frozenset[str]) -> str:
    folded = fold(token)
    if folded in names or folded in glossary:
        return PROPER_NOUN
    if _DIGIT.search(token) or folded in _NUMBER_WORDS:
        return NUMBER
    if folded in _FILLERS:
        return FILLER
    foreign = ENGLISH_ONLY_WORDS if language == "fr" else FRENCH_ONLY_WORDS
    if folded in foreign:
        return CODE_SWITCHED
    native = FRENCH_FUNCTION_WORDS if language == "fr" else ENGLISH_FUNCTION_WORDS
    if folded in native:
        return FUNCTION_WORD
    return CONTENT_WORD


def categorise(
    tokens: Sequence[str], language: str, names: frozenset[str], glossary: frozenset[str]
) -> tuple[str, ...]:
    return tuple(classify(token, language, names, glossary) for token in tokens)


def decompose(
    reference: str,
    hypothesis: str,
    language: str,
    raw_reference: str | None = None,
    glossary: Iterable[str] = (),
) -> Decomposition:
    reference_tokens = reference.split()
    hypothesis_tokens = hypothesis.split()
    names = proper_nouns(raw_reference if raw_reference is not None else reference)
    terms = frozenset(fold(term) for term in glossary)
    labels = categorise(reference_tokens, language, names, terms)
    tallies: dict[str, dict[str, int]] = {
        name: {"reference_words": 0, "hits": 0, "substitutions": 0, "deletions": 0} for name in CATEGORIES
    }
    for label in labels:
        tallies[label]["reference_words"] += 1
    insertions = 0
    if not reference_tokens:
        insertions = len(hypothesis_tokens)
    elif not hypothesis_tokens:
        for label in labels:
            tallies[label]["deletions"] += 1
    else:
        output = jiwer.process_words(reference, hypothesis)
        for chunk in output.alignments[0]:
            if chunk.type == "insert":
                insertions += int(chunk.hyp_end_idx) - int(chunk.hyp_start_idx)
                continue
            outcome = _OUTCOMES.get(chunk.type)
            if outcome is None:
                continue
            for index in range(int(chunk.ref_start_idx), int(chunk.ref_end_idx)):
                if index < len(labels):
                    tallies[labels[index]][outcome] += 1
    categories = tuple(
        CategoryCounts(category=name, **tallies[name])
        for name in CATEGORIES
        if tallies[name]["reference_words"]
    )
    return Decomposition(
        categories=categories,
        insertions=insertions,
        reference_words=len(reference_tokens),
    )


def decompose_many(
    pairs: Sequence[tuple[str, str]],
    language: str,
    raw_references: Sequence[str] | None = None,
    glossary: Iterable[str] = (),
) -> Decomposition:
    total = Decomposition(categories=())
    terms = tuple(glossary)
    for index, (reference, hypothesis) in enumerate(pairs):
        raw = raw_references[index] if raw_references is not None and index < len(raw_references) else None
        total = total + decompose(reference, hypothesis, language, raw, terms)
    return total


def proper_noun_recall(
    reference: str, hypothesis: str, raw_reference: str | None = None, glossary: Iterable[str] = ()
) -> tuple[int, int]:
    counts = decompose(reference, hypothesis, "fr", raw_reference, glossary).counts_for(PROPER_NOUN)
    return counts.hits, counts.reference_words


def merge(decompositions: Mapping[str, Decomposition]) -> Decomposition:
    total = Decomposition(categories=())
    for item in decompositions.values():
        total = total + item
    return total


_OUTCOMES: dict[str, str] = {
    "equal": "hits",
    "substitute": "substitutions",
    "delete": "deletions",
}
