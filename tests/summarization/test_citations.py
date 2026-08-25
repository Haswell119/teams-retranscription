from __future__ import annotations

from meetings import french_transcript

from hansard.adapters.summarization.citations import (
    citation_for,
    sentence_spans,
    sentence_units,
    units_in_span,
)
from hansard.adapters.summarization.merging import (
    merge_actions,
    merge_decisions,
    text_similarity,
)
from hansard.domain.minutes import ActionItem, Citation, Decision
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word


def _utterance(text: str, start: float, end: float, speaker: str = "A") -> Utterance:
    tokens = text.split()
    step = (end - start) / len(tokens)
    words = tuple(
        Word(text=token, span=TimeSpan(start + index * step, start + (index + 1) * step), speaker=speaker)
        for index, token in enumerate(tokens)
    )
    return Utterance(span=TimeSpan(start, end), text=text, speaker=speaker, words=words)


def test_sentence_spans_follow_word_timings():
    utterance = _utterance("On part sur le 12 juin. La locale allemande attendra.", 100.0, 110.0)
    units = sentence_units(Transcript(utterances=(utterance,)))
    assert len(units) == 2
    assert units[0].span.start == 100.0
    assert units[1].span.end == 110.0
    assert units[0].span.end <= units[1].span.start + 0.001
    spans = sentence_spans(utterance, [unit.text for unit in units])
    assert spans[0].duration < utterance.span.duration


def test_sentence_spans_are_interpolated_without_word_timings():
    utterance = Utterance(
        span=TimeSpan(0.0, 12.0),
        text="Première phrase courte. Deuxième phrase nettement plus longue que la première.",
        speaker="A",
    )
    units = sentence_units(Transcript(utterances=(utterance,)))
    assert units[0].span.start == 0.0
    assert units[-1].span.end == 12.0
    assert units[0].span.duration < units[1].span.duration


def test_citation_quotes_the_sentence_and_names_the_speaker():
    utterance = _utterance("On valide le budget. Merci à tous.", 10.0, 16.0, speaker="Léa Fontaine")
    unit = sentence_units(Transcript(utterances=(utterance,)))[0]
    citation = citation_for(unit)
    assert citation.quote == "On valide le budget."
    assert citation.speaker == "Léa Fontaine"
    assert citation.span == unit.span


def test_units_in_span_selects_the_right_window():
    transcript = french_transcript()
    units = sentence_units(transcript)
    window = TimeSpan(transcript.utterances[4].span.start, transcript.utterances[4].span.end)
    selected = units_in_span(units, window)
    assert selected
    assert all(unit.utterance_index in (3, 4, 5) for unit in selected)


def test_near_duplicate_decisions_are_merged_with_their_citations():
    first = Decision(
        statement="On livre la version 4.2 le 12 juin.",
        citations=(Citation(span=TimeSpan(10.0, 12.0), speaker="A", quote="On livre le 12 juin"),),
    )
    second = Decision(
        statement="On livre la version 4.2 le 12 juin sans la traduction allemande.",
        citations=(Citation(span=TimeSpan(40.0, 42.0), speaker="B", quote="sans la traduction"),),
    )
    merged = merge_decisions((first, second), "fr")
    assert len(merged) == 1
    assert merged[0].statement == second.statement
    assert len(merged[0].citations) == 2


def test_distinct_actions_are_not_merged():
    actions = (
        ActionItem(description="Envoyer le communiqué de presse à l'agence."),
        ActionItem(description="Redémarrer le nœud de transcription en production."),
    )
    assert len(merge_actions(actions, "fr")) == 2


def test_similarity_tolerates_transcription_variants():
    assert text_similarity("On part sur la version 4.2", "On part sur la versionn 4.2", "fr") > 0.85
    assert text_similarity("On part sur la version 4.2", "Le budget cluster est signé", "fr") < 0.4
