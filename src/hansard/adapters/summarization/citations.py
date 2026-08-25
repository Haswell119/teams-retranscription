from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from hansard.adapters.summarization.text import collapse_whitespace, split_sentences, truncate
from hansard.domain.minutes import Citation
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance

QUOTE_CHARACTER_LIMIT = 240


@dataclass(frozen=True, slots=True)
class SentenceUnit:
    index: int
    utterance_index: int
    position: int
    text: str
    span: TimeSpan
    speaker: str

    @property
    def is_question(self) -> bool:
        return self.text.rstrip().endswith("?")


def _word_spans(utterance: Utterance, sentences: Sequence[str]) -> tuple[TimeSpan, ...] | None:
    counts = [len(sentence.split()) for sentence in sentences]
    words = utterance.words
    if not words or len(words) != sum(counts):
        return None
    spans: list[TimeSpan] = []
    cursor = 0
    for count in counts:
        selected = words[cursor : cursor + count]
        if not selected:
            return None
        start = selected[0].span.start
        spans.append(TimeSpan(start, max(start, selected[-1].span.end)))
        cursor += count
    return tuple(spans)


def _interpolated_spans(utterance: Utterance, sentences: Sequence[str]) -> tuple[TimeSpan, ...]:
    weights = [max(1, len(sentence)) for sentence in sentences]
    total = sum(weights)
    spans: list[TimeSpan] = []
    elapsed = 0
    for weight in weights:
        start = utterance.span.start + utterance.span.duration * elapsed / total
        elapsed += weight
        end = utterance.span.start + utterance.span.duration * elapsed / total
        spans.append(TimeSpan(start, max(start, end)))
    return tuple(spans)


def sentence_spans(utterance: Utterance, sentences: Sequence[str]) -> tuple[TimeSpan, ...]:
    if not sentences:
        return ()
    if len(sentences) == 1:
        return (utterance.span,)
    aligned = _word_spans(utterance, sentences)
    return aligned if aligned is not None else _interpolated_spans(utterance, sentences)


def utterance_sentences(
    utterance: Utterance,
    utterance_index: int,
    first_index: int = 0,
) -> tuple[SentenceUnit, ...]:
    sentences = split_sentences(utterance.text)
    spans = sentence_spans(utterance, sentences)
    return tuple(
        SentenceUnit(
            index=first_index + position,
            utterance_index=utterance_index,
            position=position,
            text=sentence,
            span=span,
            speaker=utterance.speaker,
        )
        for position, (sentence, span) in enumerate(zip(sentences, spans, strict=True))
    )


def sentence_units(transcript: Transcript) -> tuple[SentenceUnit, ...]:
    units: list[SentenceUnit] = []
    for utterance_index, utterance in enumerate(transcript.utterances):
        units.extend(utterance_sentences(utterance, utterance_index, len(units)))
    return tuple(units)


def citation_for(unit: SentenceUnit, quote_limit: int = QUOTE_CHARACTER_LIMIT) -> Citation:
    return Citation(span=unit.span, speaker=unit.speaker, quote=truncate(unit.text, quote_limit))


def citations_for(
    units: Sequence[SentenceUnit], quote_limit: int = QUOTE_CHARACTER_LIMIT
) -> tuple[Citation, ...]:
    return tuple(citation_for(unit, quote_limit) for unit in units)


def citation_from_utterance(
    utterance: Utterance,
    quote: str = "",
    quote_limit: int = QUOTE_CHARACTER_LIMIT,
) -> Citation:
    text = collapse_whitespace(quote) or utterance.text
    return Citation(span=utterance.span, speaker=utterance.speaker, quote=truncate(text, quote_limit))


def units_in_span(units: Sequence[SentenceUnit], span: TimeSpan) -> tuple[SentenceUnit, ...]:
    return tuple(unit for unit in units if unit.span.intersects(span) or span.contains(unit.span.start))


def utterances_in_span(transcript: Transcript, span: TimeSpan) -> tuple[Utterance, ...]:
    return tuple(
        utterance
        for utterance in transcript.utterances
        if utterance.span.intersects(span) or span.contains(utterance.span.start)
    )


def enclosing_span(spans: Sequence[TimeSpan]) -> TimeSpan | None:
    if not spans:
        return None
    start = min(span.start for span in spans)
    end = max(span.end for span in spans)
    return TimeSpan(start, end)


def citation_span(citations: Sequence[Citation]) -> TimeSpan | None:
    return enclosing_span([citation.span for citation in citations])
