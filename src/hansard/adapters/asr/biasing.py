from __future__ import annotations

from dataclasses import dataclass, replace

from hansard.adapters.asr.phonetics import similarity, sound_key
from hansard.domain.transcript import Transcript, Utterance, Word


@dataclass(frozen=True, slots=True)
class BoostPhrase:
    surface: str
    key: str
    word_count: int


@dataclass(frozen=True, slots=True)
class BiasingReport:
    replacements: tuple[tuple[str, str], ...] = ()

    @property
    def count(self) -> int:
        return len(self.replacements)


@dataclass(frozen=True, slots=True)
class VocabularyBiaser:
    similarity_threshold: float = 0.82
    exact_bypass: bool = True
    confidence_ceiling: float = 0.995
    max_phrase_words: int = 4

    @property
    def name(self) -> str:
        return "phonetic"

    def compile(self, phrases: tuple[str, ...], language: str) -> tuple[BoostPhrase, ...]:
        compiled: list[BoostPhrase] = []
        for phrase in phrases:
            cleaned = phrase.strip()
            if not cleaned:
                continue
            key = sound_key(cleaned, language)
            if key:
                compiled.append(BoostPhrase(cleaned, key, len(cleaned.split())))
        return tuple(sorted(compiled, key=lambda item: -item.word_count))

    def _best_match(self, window: str, language: str, phrases: tuple[BoostPhrase, ...]) -> BoostPhrase | None:
        key = sound_key(window, language)
        if not key:
            return None
        best: BoostPhrase | None = None
        best_score = self.similarity_threshold
        for phrase in phrases:
            score = similarity(key, phrase.key)
            if score > best_score:
                best_score = score
                best = phrase
        return best

    def apply(
        self, transcript: Transcript, phrases: tuple[str, ...], language: str | None = None
    ) -> tuple[Transcript, BiasingReport]:
        compiled = self.compile(phrases, language or transcript.language or "en")
        if not compiled:
            return transcript, BiasingReport()
        resolved_language = language or transcript.language or "en"
        exact = {phrase.surface.casefold() for phrase in compiled}
        replacements: list[tuple[str, str]] = []
        utterances: list[Utterance] = []
        for utterance in transcript.utterances:
            if not utterance.words:
                utterances.append(utterance)
                continue
            words = list(utterance.words)
            index = 0
            rebuilt: list[Word] = []
            while index < len(words):
                matched = False
                for length in range(min(self.max_phrase_words, len(words) - index), 0, -1):
                    window = words[index : index + length]
                    surface = " ".join(word.text for word in window)
                    if surface.casefold() in exact:
                        break
                    if min(word.confidence for word in window) > self.confidence_ceiling:
                        continue
                    candidate = self._best_match(surface, resolved_language, compiled)
                    if candidate is None or candidate.word_count != length:
                        continue
                    replacements.append((surface, candidate.surface))
                    rebuilt.extend(_retext(window, candidate.surface))
                    index += length
                    matched = True
                    break
                if not matched:
                    rebuilt.append(words[index])
                    index += 1
            utterances.append(
                replace(utterance, words=tuple(rebuilt), text=" ".join(word.text for word in rebuilt))
            )
        return replace(transcript, utterances=tuple(utterances)), BiasingReport(tuple(replacements))


def _retext(window: list[Word], surface: str) -> list[Word]:
    pieces = surface.split()
    if len(pieces) == len(window):
        return [replace(word, text=piece) for word, piece in zip(window, pieces, strict=True)]
    return [replace(window[0], text=surface)]
