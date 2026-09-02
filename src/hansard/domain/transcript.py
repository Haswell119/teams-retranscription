from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from hansard.domain.language import (
    LanguageProfile,
    normalise_tag,
    profile_from_counts,
)
from hansard.domain.speakers import UNKNOWN_SPEAKER
from hansard.domain.timespan import TimeSpan


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    span: TimeSpan
    confidence: float = 1.0
    speaker: str = UNKNOWN_SPEAKER

    def shifted(self, offset: float) -> Word:
        return replace(self, span=self.span.shifted(offset))

    def attributed_to(self, speaker: str) -> Word:
        return replace(self, speaker=speaker)


@dataclass(frozen=True, slots=True)
class Utterance:
    span: TimeSpan
    text: str
    speaker: str = UNKNOWN_SPEAKER
    language: str | None = None
    confidence: float = 1.0
    words: tuple[Word, ...] = ()

    def shifted(self, offset: float) -> Utterance:
        return replace(
            self,
            span=self.span.shifted(offset),
            words=tuple(word.shifted(offset) for word in self.words),
        )

    def attributed_to(self, speaker: str) -> Utterance:
        return replace(self, speaker=speaker, words=tuple(w.attributed_to(speaker) for w in self.words))

    def spoken_in(self, language: str | None) -> Utterance:
        return replace(self, language=normalise_tag(language))

    @property
    def word_count(self) -> int:
        return len(self.words) if self.words else len(self.text.split())


def _languages_agree(previous: Utterance, following: Utterance) -> bool:
    return previous.language is None or following.language is None or previous.language == following.language


@dataclass(frozen=True, slots=True)
class Transcript:
    utterances: tuple[Utterance, ...] = ()
    language: str | None = None
    audio_duration: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(utterance.text.strip() for utterance in self.utterances if utterance.text.strip())

    @property
    def words(self) -> tuple[Word, ...]:
        return tuple(word for utterance in self.utterances for word in utterance.words)

    @property
    def word_count(self) -> int:
        return sum(utterance.word_count for utterance in self.utterances)

    @property
    def speakers(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for utterance in self.utterances:
            seen.setdefault(utterance.speaker, None)
        return tuple(seen)

    @property
    def speech_duration(self) -> float:
        return sum(utterance.span.duration for utterance in self.utterances)

    @property
    def language_profile(self) -> LanguageProfile:
        counts: dict[str, float] = {}
        seconds: dict[str, float] = {}
        for utterance in self.utterances:
            tag = normalise_tag(utterance.language)
            if tag is None:
                continue
            counts[tag] = counts.get(tag, 0.0) + float(utterance.word_count)
            seconds[tag] = seconds.get(tag, 0.0) + utterance.span.duration
        return profile_from_counts(counts, seconds)

    @property
    def is_code_switched(self) -> bool:
        return self.language_profile.is_mixed

    def with_languages(self, tags: Sequence[str | None]) -> Transcript:
        if len(tags) != len(self.utterances):
            raise ValueError("one language tag is required per utterance")
        relabelled = tuple(
            utterance.spoken_in(tag) for utterance, tag in zip(self.utterances, tags, strict=True)
        )
        return replace(self, utterances=relabelled)

    def renamed(self, mapping: dict[str, str]) -> Transcript:
        return replace(
            self,
            utterances=tuple(
                utterance.attributed_to(mapping.get(utterance.speaker, utterance.speaker))
                for utterance in self.utterances
            ),
        )

    def merged_by_speaker(self, max_gap: float = 1.0) -> Transcript:
        if not self.utterances:
            return self
        merged: list[Utterance] = [self.utterances[0]]
        for utterance in self.utterances[1:]:
            previous = merged[-1]
            contiguous = utterance.span.start - previous.span.end <= max_gap
            if utterance.speaker == previous.speaker and contiguous and _languages_agree(previous, utterance):
                merged[-1] = replace(
                    previous,
                    span=TimeSpan(previous.span.start, utterance.span.end),
                    text=f"{previous.text.rstrip()} {utterance.text.lstrip()}".strip(),
                    language=previous.language or utterance.language,
                    words=previous.words + utterance.words,
                    confidence=min(previous.confidence, utterance.confidence),
                )
            else:
                merged.append(utterance)
        return replace(self, utterances=tuple(merged))
