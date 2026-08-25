from __future__ import annotations

from dataclasses import dataclass, replace

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

    @property
    def word_count(self) -> int:
        return len(self.words) if self.words else len(self.text.split())


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
            if utterance.speaker == previous.speaker and contiguous:
                merged[-1] = replace(
                    previous,
                    span=TimeSpan(previous.span.start, utterance.span.end),
                    text=f"{previous.text.rstrip()} {utterance.text.lstrip()}".strip(),
                    words=previous.words + utterance.words,
                    confidence=min(previous.confidence, utterance.confidence),
                )
            else:
                merged.append(utterance)
        return replace(self, utterances=tuple(merged))
