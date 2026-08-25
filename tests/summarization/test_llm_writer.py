from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from conftest import ScriptedGenerator, UnreachableGenerator
from llm_answers import ENGLISH_MAP, ENGLISH_REDUCE, FRENCH_MAP, FRENCH_REDUCE
from meetings import MEETING_DATE

from hansard.adapters.summarization.chunking import ChunkOptions
from hansard.adapters.summarization.extractive import ExtractiveMinutesWriter
from hansard.adapters.summarization.llm_writer import LlmMinutesWriter
from hansard.adapters.summarization.text import fold_for_matching
from hansard.ports.summarization import MinutesWriter

GENERATED_AT = datetime(2026, 6, 3, 11, 0, tzinfo=UTC)


def _extractive():
    return ExtractiveMinutesWriter(reference_date=MEETING_DATE, clock=lambda: GENERATED_AT)


def _writer(generator, **kwargs):
    return LlmMinutesWriter(generator=generator, fallback=_extractive(), **kwargs)


def test_writer_satisfies_the_port():
    writer = _writer(ScriptedGenerator([], None))
    assert isinstance(writer, MinutesWriter)
    assert writer.name == "llm"


def test_french_map_reduce_produces_grounded_minutes(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator([FRENCH_MAP], FRENCH_REDUCE)
    outcome = _writer(generator).compose_with_report(fr_transcript, fr_roster, fr_request)
    minutes = outcome.minutes
    assert minutes.language == "fr"
    assert "12 juin" in minutes.abstract
    assert [decision.statement for decision in minutes.decisions] == [
        "La version 4.2 est lancée le 12 juin sans la traduction allemande.",
        "Le passage à quatre nœuds de transcription est validé.",
    ]
    assert [topic.title for topic in minutes.topics] == [
        "Lancement de la version 4.2",
        "Incident de production",
    ]
    assert outcome.report.engine == "llm"
    assert outcome.report.fallback_reason is None


def test_english_map_reduce_produces_grounded_minutes(en_transcript, en_roster, en_request):
    generator = ScriptedGenerator([ENGLISH_MAP], ENGLISH_REDUCE)
    outcome = _writer(generator).compose_with_report(en_transcript, en_roster, en_request)
    minutes = outcome.minutes
    assert minutes.language == "en"
    assert len(minutes.decisions) == 2
    assert "two week cycle" in minutes.abstract
    assert minutes.open_questions[0].raised_by == "Priya Raman"


def test_citations_point_at_the_quoted_utterance(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator([FRENCH_MAP], FRENCH_REDUCE)
    minutes = _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    decision = minutes.decisions[0]
    assert decision.citations
    citation = decision.citations[0]
    assert citation.speaker == "Camille Dubois"
    assert "On part sur un lancement" in citation.quote
    source = fr_transcript.utterances[4]
    assert citation.span.start >= source.span.start
    assert citation.span.end <= source.span.end + 0.001


def test_quotes_are_never_invented(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator([FRENCH_MAP], FRENCH_REDUCE)
    minutes = _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    haystack = fold_for_matching(fr_transcript.text)
    for item in (*minutes.decisions, *minutes.actions, *minutes.open_questions):
        for citation in item.citations:
            assert fold_for_matching(citation.quote.rstrip("…")) in haystack


@pytest.mark.parametrize(
    ("answers", "reduce_answer", "language"),
    [((FRENCH_MAP,), FRENCH_REDUCE, "fr"), ((ENGLISH_MAP,), ENGLISH_REDUCE, "en")],
)
def test_hallucinated_action_is_dropped_and_reported(
    answers,
    reduce_answer,
    language,
    fr_transcript,
    en_transcript,
    fr_roster,
    en_roster,
    fr_request,
    en_request,
):
    transcript = fr_transcript if language == "fr" else en_transcript
    roster = fr_roster if language == "fr" else en_roster
    request = fr_request if language == "fr" else en_request
    generator = ScriptedGenerator(answers, reduce_answer)
    outcome = _writer(generator).compose_with_report(transcript, roster, request)
    descriptions = [action.description for action in outcome.minutes.actions]
    assert len(descriptions) == 2
    assert not any("Zenith" in text or "Helsinki" in text for text in descriptions)
    assert outcome.report.dropped
    assert any(number.startswith("250") for number in outcome.report.unsupported_numbers)
    assert not outcome.report.is_clean


def test_model_owner_is_resolved_against_the_roster(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator([FRENCH_MAP], FRENCH_REDUCE)
    minutes = _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    owners = [action.owner for action in minutes.actions]
    assert owners == ["Marc Lefèvre", "Sofia Ben Ali"]


def test_unknown_owner_is_cleared_rather_than_guessed(fr_transcript, fr_roster, fr_request):
    answer = copy.deepcopy(FRENCH_MAP)
    answer["actions"] = [answer["actions"][0] | {"owner": "Bertrand Dupuis"}]
    generator = ScriptedGenerator([answer], FRENCH_REDUCE)
    minutes = _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    assert minutes.actions[0].owner is None


def test_due_date_is_grounded_in_the_cited_utterance(fr_transcript, fr_roster, fr_request):
    answer = copy.deepcopy(FRENCH_MAP)
    answer["actions"] = [answer["actions"][0] | {"due": "le 30 septembre"}]
    generator = ScriptedGenerator([answer], FRENCH_REDUCE)
    minutes = _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    assert minutes.actions[0].due_date == "2026-06-04"


def test_citation_is_recovered_from_the_quote_when_the_index_is_wrong(fr_transcript, fr_roster, fr_request):
    answer = copy.deepcopy(FRENCH_MAP)
    answer["decisions"] = [answer["decisions"][0] | {"utterance": 999}]
    generator = ScriptedGenerator([answer], FRENCH_REDUCE)
    minutes = _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    assert minutes.decisions[0].citations[0].speaker == "Camille Dubois"


def test_item_without_any_resolvable_citation_is_dropped(fr_transcript, fr_roster, fr_request):
    answer = copy.deepcopy(FRENCH_MAP)
    answer["decisions"] = [
        {"statement": "On double le budget.", "quote": "phrase absente", "utterance": 4321}
    ]
    generator = ScriptedGenerator([answer], FRENCH_REDUCE)
    minutes = _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    assert minutes.decisions == ()


def test_unreachable_endpoint_falls_back_to_extractive(fr_transcript, fr_roster, fr_request):
    outcome = _writer(UnreachableGenerator()).compose_with_report(fr_transcript, fr_roster, fr_request)
    assert outcome.report.engine == "extractive"
    assert outcome.report.fallback_reason is not None
    assert "cannot reach" in outcome.report.fallback_reason
    assert len(outcome.minutes.decisions) == 2
    assert len(outcome.minutes.actions) == 3
    assert outcome.minutes.abstract.strip()


def test_garbage_answer_falls_back_to_extractive(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator(["I am sorry, I cannot help with that."], FRENCH_REDUCE)
    outcome = _writer(generator).compose_with_report(fr_transcript, fr_roster, fr_request)
    assert outcome.report.engine == "extractive"
    assert outcome.minutes.decisions
    assert outcome.report.notes


def test_consolidation_failure_keeps_the_mapped_items(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator([FRENCH_MAP], None)
    outcome = _writer(generator).compose_with_report(fr_transcript, fr_roster, fr_request)
    assert outcome.report.engine == "llm"
    assert len(outcome.minutes.decisions) == 2
    assert outcome.minutes.abstract.strip()
    assert any("consolidation" in note for note in outcome.report.notes)


def test_empty_model_answer_never_yields_empty_minutes(fr_transcript, fr_roster, fr_request):
    empty = {"summary": "", "decisions": [], "actions": [], "questions": [], "entities": []}
    generator = ScriptedGenerator([empty], {"abstract": "", "topics": []})
    outcome = _writer(generator).compose_with_report(fr_transcript, fr_roster, fr_request)
    assert outcome.minutes.abstract.strip()
    assert outcome.minutes.topics


def test_several_chunks_are_mapped_and_deduplicated(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator([FRENCH_MAP, FRENCH_MAP, FRENCH_MAP], FRENCH_REDUCE)
    writer = _writer(generator, chunk_options=ChunkOptions(max_tokens=300))
    outcome = writer.compose_with_report(fr_transcript, fr_roster, fr_request)
    assert len(generator.schemas) > 2
    assert len(outcome.minutes.decisions) == 2
    assert len(outcome.minutes.actions) == 2


def test_prompts_are_written_in_the_meeting_language(
    fr_transcript, fr_roster, fr_request, en_transcript, en_roster, en_request
):
    french = ScriptedGenerator([FRENCH_MAP], FRENCH_REDUCE)
    _writer(french).compose(fr_transcript, fr_roster, fr_request)
    assert "secrétaire de séance" in french.prompts[0][0]
    assert "EXTRAIT DE TRANSCRIPTION" in french.prompts[0][1]
    english = ScriptedGenerator([ENGLISH_MAP], ENGLISH_REDUCE)
    _writer(english).compose(en_transcript, en_roster, en_request)
    assert "meeting clerk" in english.prompts[0][0]
    assert "TRANSCRIPT EXCERPT" in english.prompts[0][1]


def test_chunk_lines_are_numbered_for_citation_anchoring(fr_transcript, fr_roster, fr_request):
    generator = ScriptedGenerator([FRENCH_MAP], FRENCH_REDUCE)
    _writer(generator).compose(fr_transcript, fr_roster, fr_request)
    excerpt = generator.prompts[0][1]
    assert "[0] 00:00:04 Camille Dubois:" in excerpt
    assert "[4] " in excerpt
