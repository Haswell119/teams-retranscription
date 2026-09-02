from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from hansard.adapters.asr.phonetics import strip_accents
from hansard.adapters.language.markers import (
    ENGLISH_CONTRACTIONS,
    ENGLISH_DIGRAPHS,
    ENGLISH_ONLY_WORDS,
    ENGLISH_SUFFIX_MARKERS,
    FRENCH_DIACRITICS,
    FRENCH_ELISIONS,
    FRENCH_ONLY_WORDS,
    FRENCH_SUFFIX_MARKERS,
)
from hansard.domain.language import normalise_tag
from hansard.domain.transcript import Transcript, Utterance

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

FUNCTION_WORD_WEIGHT = 1.0
ELISION_WEIGHT = 0.9
DIACRITIC_WEIGHT = 0.7
CONTRACTION_WEIGHT = 0.9
DIGRAPH_WEIGHT = 0.25
SUFFIX_WEIGHT = 0.4


@dataclass(frozen=True, slots=True)
class LanguageVerdict:
    language: str | None
    confidence: float
    french_score: float
    english_score: float

    @property
    def is_decided(self) -> bool:
        return self.language is not None


UNDECIDED = LanguageVerdict(language=None, confidence=0.0, french_score=0.0, english_score=0.0)


def _is_unopposed(french: float, english: float, threshold: float) -> bool:
    return (french >= threshold and english == 0.0) or (english >= threshold and french == 0.0)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(WORD.findall(strip_accents(text).lower()))


def _suffix_score(tokens: Sequence[str], suffixes: Sequence[str]) -> float:
    hits = sum(1 for token in tokens if len(token) > 4 and token.endswith(tuple(suffixes)))
    return SUFFIX_WEIGHT * hits


def _french_score(text: str, tokens: Sequence[str]) -> float:
    words = FUNCTION_WORD_WEIGHT * sum(1 for token in tokens if token in FRENCH_ONLY_WORDS)
    elisions = ELISION_WEIGHT * len(FRENCH_ELISIONS.findall(text))
    diacritics = DIACRITIC_WEIGHT * min(len(FRENCH_DIACRITICS.findall(text)), 4)
    return words + elisions + diacritics + _suffix_score(tokens, FRENCH_SUFFIX_MARKERS)


def _english_score(text: str, tokens: Sequence[str]) -> float:
    words = FUNCTION_WORD_WEIGHT * sum(1 for token in tokens if token in ENGLISH_ONLY_WORDS)
    contractions = CONTRACTION_WEIGHT * len(ENGLISH_CONTRACTIONS.findall(text))
    digraphs = DIGRAPH_WEIGHT * min(len(ENGLISH_DIGRAPHS.findall(text)), 6)
    return words + contractions + digraphs + _suffix_score(tokens, ENGLISH_SUFFIX_MARKERS)


@dataclass(frozen=True, slots=True)
class TextLanguageIdentifier:
    minimum_evidence: float = 1.5
    minimum_margin: float = 0.6
    relative_margin: float = 0.18
    unopposed_evidence: float = 0.9
    unopposed_tokens: int = 3

    @property
    def name(self) -> str:
        return "lexical"

    def identify_text(self, text: str) -> LanguageVerdict:
        stripped = text.strip()
        if not stripped:
            return UNDECIDED
        tokens = _tokens(stripped)
        french = _french_score(stripped, tokens)
        english = _english_score(stripped, tokens)
        total = french + english
        brief = len(tokens) <= self.unopposed_tokens
        if total < self.minimum_evidence and not (
            brief and _is_unopposed(french, english, self.unopposed_evidence)
        ):
            return LanguageVerdict(None, 0.0, french, english)
        margin = abs(french - english)
        if margin < self.minimum_margin or margin / total < self.relative_margin:
            return LanguageVerdict(None, 0.0, french, english)
        language = "fr" if french > english else "en"
        return LanguageVerdict(language, margin / total, french, english)

    def identify(self, utterance: Utterance) -> LanguageVerdict:
        return self.identify_text(utterance.text)


@dataclass(frozen=True, slots=True)
class UtteranceLanguageTagger:
    identifier: TextLanguageIdentifier = TextLanguageIdentifier()
    default_language: str | None = None
    trust_engine_tags: bool = False
    revise_weak_verdicts: bool = False
    weak_confidence: float = 0.55
    weak_evidence: float = 3.0
    context_confidence: float = 0.70

    def _verdicts(self, transcript: Transcript) -> list[LanguageVerdict]:
        return [self.identifier.identify(utterance) for utterance in transcript.utterances]

    def _seed(self, transcript: Transcript, verdicts: Sequence[LanguageVerdict]) -> list[str | None]:
        tags: list[str | None] = []
        for utterance, verdict in zip(transcript.utterances, verdicts, strict=True):
            existing = normalise_tag(utterance.language) if self.trust_engine_tags else None
            tags.append(verdict.language or existing)
        return tags

    def tag(self, transcript: Transcript) -> Transcript:
        if not transcript.utterances:
            return transcript
        verdicts = self._verdicts(transcript)
        seeded = self._seed(transcript, verdicts)
        speakers = tuple(utterance.speaker for utterance in transcript.utterances)
        if self.revise_weak_verdicts:
            seeded = self._revised(seeded, verdicts, speakers)
        fallback = _fallback(tags_of(verdicts), self.default_language)
        return transcript.with_languages(_smooth(seeded, speakers, fallback))

    def _is_weak(self, verdict: LanguageVerdict) -> bool:
        evidence = verdict.french_score + verdict.english_score
        return verdict.confidence < self.weak_confidence or evidence < self.weak_evidence

    def _revised(
        self,
        tags: list[str | None],
        verdicts: Sequence[LanguageVerdict],
        speakers: Sequence[str],
    ) -> list[str | None]:
        strong = [
            tag if verdict.language is not None and not self._is_weak(verdict) else None
            for tag, verdict in zip(tags, verdicts, strict=True)
        ]
        revised = list(tags)
        for index, verdict in enumerate(verdicts):
            if verdict.language is None or not self._is_weak(verdict):
                continue
            context = _agreed_context(strong, speakers, index, self.context_confidence, verdicts)
            if context is not None and context != verdict.language:
                revised[index] = context
        return revised


def tags_of(verdicts: Sequence[LanguageVerdict]) -> tuple[str, ...]:
    return tuple(verdict.language for verdict in verdicts if verdict.language is not None)


def _fallback(decided: Sequence[str], default_language: str | None) -> str | None:
    resolved = normalise_tag(default_language)
    if resolved is not None and resolved != "mixed":
        return resolved
    if not decided:
        return resolved if resolved != "mixed" else None
    counts: dict[str, int] = {}
    for tag in decided:
        counts[tag] = counts.get(tag, 0) + 1
    return max(sorted(counts), key=lambda tag: counts[tag])


def _smooth(
    tags: Sequence[str | None],
    speakers: Sequence[str],
    fallback: str | None,
) -> list[str | None]:
    filled = [tag if tag is not None else _inherited(tags, speakers, index) for index, tag in enumerate(tags)]
    return [tag if tag is not None else fallback for tag in filled]


def _inherited(tags: Sequence[str | None], speakers: Sequence[str], index: int) -> str | None:
    def same_speaker(position: int) -> bool:
        return speakers[position] == speakers[index]

    own = _nearest(tags, index, same_speaker, forward_first=True)
    return own if own is not None else _nearest(tags, index, lambda _: True, forward_first=False)


def _nearest(
    tags: Sequence[str | None],
    index: int,
    accepts: Callable[[int], bool],
    forward_first: bool,
) -> str | None:
    for distance in range(1, len(tags)):
        ahead, behind = index + distance, index - distance
        ordered = (ahead, behind) if forward_first else (behind, ahead)
        for position in ordered:
            if 0 <= position < len(tags) and tags[position] is not None and accepts(position):
                return tags[position]
    return None


def _agreed_context(
    strong: Sequence[str | None],
    speakers: Sequence[str],
    index: int,
    confidence: float,
    verdicts: Sequence[LanguageVerdict],
) -> str | None:
    before = _scan(strong, speakers, index, -1, confidence, verdicts)
    after = _scan(strong, speakers, index, 1, confidence, verdicts)
    if before is not None and before == after:
        return before
    return None


def _scan(
    strong: Sequence[str | None],
    speakers: Sequence[str],
    index: int,
    step: int,
    confidence: float,
    verdicts: Sequence[LanguageVerdict],
) -> str | None:
    position = index + step
    while 0 <= position < len(strong):
        if speakers[position] == speakers[index] and strong[position] is not None:
            return strong[position] if verdicts[position].confidence >= confidence else None
        position += step
    return None
