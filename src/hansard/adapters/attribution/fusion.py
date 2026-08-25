from __future__ import annotations

import math
from dataclasses import dataclass, replace

from hansard.domain.speakers import UNKNOWN_SPEAKER, Diarization
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word

NEGATIVE_INFINITY = float("-inf")


@dataclass(frozen=True, slots=True)
class WordLevelAttributor:
    boundary_dilation: float = 0.20
    dominance_margin: float = 1.5
    switch_probability: float = 0.05
    nearest_turn_horizon: float = 2.0

    @property
    def name(self) -> str:
        return "word-level"

    def _candidate_scores(self, span: TimeSpan, diarization: Diarization) -> dict[str, float]:
        dilated = TimeSpan(span.start - self.boundary_dilation, span.end + self.boundary_dilation)
        scores: dict[str, float] = {}
        for turn in diarization.turns:
            overlap = dilated.overlap(turn.span)
            if overlap > 0.0:
                scores[turn.label] = scores.get(turn.label, 0.0) + overlap * turn.confidence
        return scores

    def _nearest_label(self, span: TimeSpan, diarization: Diarization) -> str:
        best_label = UNKNOWN_SPEAKER
        best_distance = self.nearest_turn_horizon
        for turn in diarization.turns:
            distance = max(turn.span.start - span.end, span.start - turn.span.end, 0.0)
            if distance < best_distance:
                best_distance = distance
                best_label = turn.label
        return best_label

    def _emissions(
        self, words: tuple[Word, ...], diarization: Diarization, labels: tuple[str, ...]
    ) -> list[dict[str, float]]:
        emissions: list[dict[str, float]] = []
        for word in words:
            scores = self._candidate_scores(word.span, diarization)
            if not scores:
                fallback = self._nearest_label(word.span, diarization)
                scores = {fallback: 1.0} if fallback != UNKNOWN_SPEAKER else dict.fromkeys(labels, 1.0)
            total = sum(scores.values()) or 1.0
            floor = 1e-6
            emissions.append(
                {label: math.log(max(scores.get(label, 0.0) / total, floor)) for label in labels}
            )
        return emissions

    def _viterbi(self, emissions: list[dict[str, float]], labels: tuple[str, ...]) -> list[str]:
        if not emissions:
            return []
        stay = math.log(1.0 - self.switch_probability)
        switch = math.log(self.switch_probability / max(len(labels) - 1, 1))
        scores = dict(emissions[0])
        backpointers: list[dict[str, str]] = []
        for emission in emissions[1:]:
            updated: dict[str, float] = {}
            pointer: dict[str, str] = {}
            for label in labels:
                best_label = labels[0]
                best_score = NEGATIVE_INFINITY
                for previous in labels:
                    transition = stay if previous == label else switch
                    candidate = scores[previous] + transition
                    if candidate > best_score:
                        best_score = candidate
                        best_label = previous
                updated[label] = best_score + emission[label]
                pointer[label] = best_label
            scores = updated
            backpointers.append(pointer)
        final = max(labels, key=lambda label: scores[label])
        path = [final]
        for pointer in reversed(backpointers):
            path.append(pointer[path[-1]])
        path.reverse()
        return path

    def _dominant(self, scores: dict[str, float]) -> str | None:
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) == 1:
            return ranked[0][0]
        best, runner_up = ranked[0][1], ranked[1][1]
        return ranked[0][0] if runner_up <= 0.0 or best >= self.dominance_margin * runner_up else None

    def attribute(self, transcript: Transcript, diarization: Diarization) -> Transcript:
        labels = diarization.labels or tuple(dict.fromkeys(turn.label for turn in diarization.turns))
        if not labels:
            return transcript
        if len(labels) == 1:
            return transcript.renamed(dict.fromkeys(transcript.speakers, labels[0]))
        words = transcript.words
        if not words:
            return self._attribute_by_utterance(transcript, diarization, labels)
        smoothed = self._viterbi(self._emissions(words, diarization, labels), labels)
        resolved: list[str] = []
        for word, fallback in zip(words, smoothed, strict=True):
            dominant = self._dominant(self._candidate_scores(word.span, diarization))
            resolved.append(dominant or fallback)
        return self._rebuild(transcript, dict(zip(words, resolved, strict=True)))

    def _attribute_by_utterance(
        self, transcript: Transcript, diarization: Diarization, labels: tuple[str, ...]
    ) -> Transcript:
        spans = tuple(utterance.span for utterance in transcript.utterances)
        pseudo_words = tuple(Word(text="", span=span) for span in spans)
        smoothed = self._viterbi(self._emissions(pseudo_words, diarization, labels), labels)
        return replace(
            transcript,
            utterances=tuple(
                utterance.attributed_to(label)
                for utterance, label in zip(transcript.utterances, smoothed, strict=True)
            ),
        ).merged_by_speaker()

    def _rebuild(self, transcript: Transcript, assignment: dict[Word, str]) -> Transcript:
        rebuilt: list[Utterance] = []
        for utterance in transcript.utterances:
            if not utterance.words:
                rebuilt.append(utterance)
                continue
            current: list[Word] = []
            current_label = assignment[utterance.words[0]]
            for word in utterance.words:
                label = assignment[word]
                if label != current_label and current:
                    rebuilt.append(_utterance_from(current, current_label, utterance.language))
                    current = []
                    current_label = label
                current.append(word.attributed_to(label))
            if current:
                rebuilt.append(_utterance_from(current, current_label, utterance.language))
        rebuilt.sort(key=lambda item: item.span.start)
        return replace(transcript, utterances=tuple(rebuilt)).merged_by_speaker()


def _utterance_from(words: list[Word], label: str, language: str | None) -> Utterance:
    span = TimeSpan(words[0].span.start, words[-1].span.end)
    confidence = sum(word.confidence for word in words) / len(words)
    return Utterance(
        span=span,
        text=" ".join(word.text for word in words).strip(),
        speaker=label,
        language=language,
        confidence=confidence,
        words=tuple(words),
    )
