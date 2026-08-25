from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, cast, runtime_checkable

from hansard.evaluation.english_numbers import normalize_digit_groups, words_to_digits
from hansard.evaluation.french_numbers import expand_numbers

_BRACKETED = re.compile(r"[<\[][^>\]]*[>\]]")
_PARENTHESISED = re.compile(r"\(([^)]+?)\)")
_WHITESPACE = re.compile(r"\s+")
_APOSTROPHES = re.compile("[\u2018\u2019\u02bc\u00b4`\u201b]")
_ENGLISH_FILLERS = re.compile(r"\b(hmm|mm|mhm|mmm|uh|um)\b")
_FRENCH_FILLERS = re.compile(r"\b(euh+|heu|hein|ben|bah|hum+|hm+|mmh)\b")
_FRENCH_ELISIONS = re.compile(r"\b(l|d|j|n|s|t|c|m|qu|jusqu|lorsqu|puisqu|quoiqu|aujourd)'")
_FRENCH_NUMBER_PLURALS = re.compile(r"\b(vingt|cent)s\b")
_FRENCH_ISSUE_NUMBER = re.compile(r"n\s*[°ºo]\s*(?=\d)")
_SPACE_BEFORE_APOSTROPHE = re.compile(r"\s+'")
_TRAILING_SYMBOL = re.compile(r"[.$¢€£]([^0-9])")
_PERCENT_AFTER_WORD = re.compile(r"([^0-9])%")

_ENGLISH_REPLACERS: tuple[tuple[str, str], ...] = (
    (r"\bwon't\b", "will not"),
    (r"\bcan't\b", "can not"),
    (r"\blet's\b", "let us"),
    (r"\bain't\b", "aint"),
    (r"\by'all\b", "you all"),
    (r"\bwanna\b", "want to"),
    (r"\bkinda\b", "kind of"),
    (r"\bsorta\b", "sort of"),
    (r"\bdunno\b", "do not know"),
    (r"\bgotta\b", "got to"),
    (r"\bgonna\b", "going to"),
    (r"\bi'ma\b", "i am going to"),
    (r"\bimma\b", "i am going to"),
    (r"\bwoulda\b", "would have"),
    (r"\bcoulda\b", "could have"),
    (r"\bshoulda\b", "should have"),
    (r"\bcause\b", "because"),
    (r"\bma'am\b", "madam"),
    (r"\bmr\b", "mister "),
    (r"\bmrs\b", "missus "),
    (r"\bst\b", "saint "),
    (r"\bdr\b", "doctor "),
    (r"\bprof\b", "professor "),
    (r"\bcapt\b", "captain "),
    (r"\bgov\b", "governor "),
    (r"\bgen\b", "general "),
    (r"\bsen\b", "senator "),
    (r"\brep\b", "representative "),
    (r"\bpres\b", "president "),
    (r"\brev\b", "reverend "),
    (r"\bhon\b", "honorable "),
    (r"\basst\b", "assistant "),
    (r"\bassoc\b", "associate "),
    (r"\blt\b", "lieutenant "),
    (r"\bcol\b", "colonel "),
    (r"\bjr\b", "junior "),
    (r"\bsr\b", "senior "),
    (r"\besq\b", "esquire "),
    (r"'d been\b", " had been"),
    (r"'s been\b", " has been"),
    (r"'d gone\b", " had gone"),
    (r"'s gone\b", " has gone"),
    (r"'d done\b", " had done"),
    (r"'s got\b", " has got"),
    (r"n't\b", " not"),
    (r"'re\b", " are"),
    (r"'s\b", " is"),
    (r"'d\b", " would"),
    (r"'ll\b", " will"),
    (r"'t\b", " not"),
    (r"'ve\b", " have"),
    (r"'m\b", " am"),
)

_BRITISH_TO_AMERICAN: dict[str, str] = {
    "aluminium": "aluminum",
    "analyse": "analyze",
    "analysed": "analyzed",
    "apologise": "apologize",
    "behaviour": "behavior",
    "cancelled": "canceled",
    "catalogue": "catalog",
    "centre": "center",
    "centres": "centers",
    "cheque": "check",
    "colour": "color",
    "colours": "colors",
    "defence": "defense",
    "dialogue": "dialog",
    "favourite": "favorite",
    "fulfil": "fulfill",
    "grey": "gray",
    "honour": "honor",
    "humour": "humor",
    "judgement": "judgment",
    "labour": "labor",
    "licence": "license",
    "litre": "liter",
    "litres": "liters",
    "metre": "meter",
    "metres": "meters",
    "neighbour": "neighbor",
    "organisation": "organization",
    "organise": "organize",
    "organised": "organized",
    "practise": "practice",
    "programme": "program",
    "programmes": "programs",
    "realise": "realize",
    "realised": "realized",
    "recognise": "recognize",
    "recognised": "recognized",
    "sceptical": "skeptical",
    "storey": "story",
    "travelled": "traveled",
    "travelling": "traveling",
    "tyre": "tire",
    "whilst": "while",
    "amongst": "among",
    "learnt": "learned",
    "spelt": "spelled",
    "burnt": "burned",
    "dreamt": "dreamed",
}

_FRENCH_TITLES: tuple[tuple[str, str], ...] = (
    (r"\bMM\.", "messieurs"),
    (r"\bM\.", "monsieur"),
    (r"\bMmes\.?", "mesdames"),
    (r"\bMme\.?", "madame"),
    (r"\bMlles\.?", "mesdemoiselles"),
    (r"\bMlle\.?", "mademoiselle"),
    (r"\bDr\.?", "docteur"),
    (r"\bPr\.?", "professeur"),
    (r"\bSte\.?", "sainte"),
    (r"\bSt\.?", "saint"),
)

_FRENCH_SYMBOLS: tuple[tuple[str, str], ...] = (
    (r"%", " pour cent "),
    (r"€", " euros "),
    (r"\$", " dollars "),
    (r"£", " livres "),
    (r"&", " et "),
    (r"\+", " plus "),
    (r"=", " égale "),
    (r"\betc\b\.?", " et cetera "),
)


@runtime_checkable
class TextNormalizer(Protocol):
    def normalize(self, text: str) -> str: ...


@dataclass(frozen=True, slots=True)
class BasicNormalizer:
    strip_accents: bool = False

    def normalize(self, text: str) -> str:
        result = unicodedata.normalize("NFKC", text)
        result = _BRACKETED.sub(" ", result)
        result = _PARENTHESISED.sub(" ", result)
        result = result.lower()
        if self.strip_accents:
            result = remove_diacritics(result)
        result = replace_punctuation(result)
        return collapse_whitespace(result)


@dataclass(frozen=True, slots=True)
class EnglishNormalizer:
    prefer_installed_whisper: bool = True
    british_to_american: bool = True

    def normalize(self, text: str) -> str:
        if self.prefer_installed_whisper and self.british_to_american:
            reference_implementation = load_whisper_english_normalizer()
            if reference_implementation is not None:
                return collapse_whitespace(reference_implementation(text))
        return self._normalize_locally(text)

    def _normalize_locally(self, text: str) -> str:
        result = unicodedata.normalize("NFKC", text).lower()
        result = _BRACKETED.sub("", result)
        result = _PARENTHESISED.sub("", result)
        result = _APOSTROPHES.sub("'", result)
        result = _ENGLISH_FILLERS.sub("", result)
        result = _SPACE_BEFORE_APOSTROPHE.sub("'", result)
        for pattern, replacement in _ENGLISH_REPLACERS:
            result = re.sub(pattern, replacement, result)
        result = normalize_digit_groups(result)
        result = re.sub(r"\.([^0-9]|$)", r" \1", result)
        result = replace_punctuation(result, keep=".%$¢€£")
        result = words_to_digits(collapse_whitespace(result))
        if self.british_to_american:
            result = _apply_word_map(result, _BRITISH_TO_AMERICAN)
        result = _TRAILING_SYMBOL.sub(r" \1", result)
        result = _PERCENT_AFTER_WORD.sub(r"\1 ", result)
        return collapse_whitespace(result)


@dataclass(frozen=True, slots=True)
class FrenchNormalizer:
    strip_accents: bool = False
    expand_numbers: bool = True
    remove_fillers: bool = True

    def normalize(self, text: str) -> str:
        result = unicodedata.normalize("NFKC", text)
        result = _BRACKETED.sub(" ", result)
        result = _PARENTHESISED.sub(" ", result)
        result = _APOSTROPHES.sub("'", result)
        for pattern, replacement in _FRENCH_TITLES:
            result = re.sub(pattern, replacement, result)
        result = result.lower()
        result = _FRENCH_ISSUE_NUMBER.sub("numéro ", result)
        for pattern, replacement in _FRENCH_SYMBOLS:
            result = re.sub(pattern, replacement, result)
        result = result.replace("œ", "oe").replace("æ", "ae")
        result = _FRENCH_ELISIONS.sub(r"\1 ", result)
        result = result.replace("'", " ")
        if self.expand_numbers:
            result = expand_numbers(result)
        if self.strip_accents:
            result = remove_diacritics(result)
        result = replace_punctuation(result)
        result = _FRENCH_NUMBER_PLURALS.sub(r"\1", result)
        if self.remove_fillers:
            result = _FRENCH_FILLERS.sub(" ", result)
        return collapse_whitespace(result)


def normalizer_for(language: str | None) -> TextNormalizer:
    code = (language or "").split("-")[0].split("_")[0].strip().lower()
    if code in {"fr", "fra", "fre", "french", "français"}:
        return FrenchNormalizer()
    if code in {"en", "eng", "english"}:
        return EnglishNormalizer()
    return BasicNormalizer()


def replace_punctuation(text: str, keep: str = "") -> str:
    return "".join(
        character if character.isalnum() or character.isspace() or character in keep else " "
        for character in text
    )


def remove_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(character for character in decomposed if unicodedata.category(character) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


@lru_cache(maxsize=1)
def load_whisper_english_normalizer() -> Callable[[str], str] | None:
    try:
        from whisper_normalizer.english import EnglishTextNormalizer
    except ImportError:
        return None
    return cast(Callable[[str], str], EnglishTextNormalizer())


def _apply_word_map(text: str, mapping: dict[str, str]) -> str:
    return " ".join(mapping.get(token, token) for token in text.split())
