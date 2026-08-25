from __future__ import annotations

from datetime import UTC, datetime

import pytest
from meetings import MEETING_DATE, english_transcript, french_transcript

from hansard.adapters.summarization.extractive import ExtractiveMinutesWriter
from hansard.adapters.summarization.text import fold_for_matching
from hansard.domain.meeting import MeetingRequest
from hansard.domain.minutes import Minutes
from hansard.domain.speakers import Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.ports.summarization import MinutesWriter

GENERATED_AT = datetime(2026, 6, 3, 11, 0, tzinfo=UTC)


@pytest.fixture
def writer():
    return ExtractiveMinutesWriter(reference_date=MEETING_DATE, clock=lambda: GENERATED_AT)


def test_writer_satisfies_the_port(writer):
    assert isinstance(writer, MinutesWriter)
    assert writer.name == "extractive"


def test_french_minutes_end_to_end(writer, fr_transcript, fr_roster, fr_request):
    minutes = writer.compose(fr_transcript, fr_roster, fr_request)
    assert minutes.language == "fr"
    assert minutes.title == "Comité de lancement 4.2"
    assert minutes.generated_at == GENERATED_AT
    assert len(minutes.decisions) == 2
    assert len(minutes.actions) == 3
    assert len(minutes.open_questions) == 1
    assert {participant.display_name for participant in minutes.participants} == {
        "Camille Dubois",
        "Marc Lefèvre",
        "Sofia Ben Ali",
    }
    statements = " ".join(decision.statement for decision in minutes.decisions)
    assert "12 juin" in statements
    assert "quatre nœuds" in statements
    owners = {action.owner for action in minutes.actions}
    assert owners == {"Marc Lefèvre", "Sofia Ben Ali"}
    assert "2026-06-10" in {action.due_date for action in minutes.actions}
    assert "communication client" in minutes.open_questions[0].question
    assert minutes.open_questions[0].raised_by == "Sofia Ben Ali"


def test_english_minutes_end_to_end(writer, en_transcript, en_roster, en_request):
    minutes = writer.compose(en_transcript, en_roster, en_request)
    assert minutes.language == "en"
    assert len(minutes.decisions) == 2
    assert len(minutes.actions) == 3
    assert len(minutes.open_questions) == 1
    statements = " ".join(decision.statement for decision in minutes.decisions)
    assert "Saturday cutover" in statements
    assert "two week cycle" in statements
    owners = {action.owner for action in minutes.actions}
    assert owners == {"Tom Becker", "Elena Costa"}
    assert "2026-06-05" in {action.due_date for action in minutes.actions}
    assert minutes.open_questions[0].raised_by == "Priya Raman"


@pytest.mark.parametrize("language", ["fr", "en"])
def test_every_item_is_cited_and_the_quote_is_verbatim(writer, language, fr_roster, en_roster,
                                                       fr_request, en_request):
    transcript = french_transcript() if language == "fr" else english_transcript()
    roster = fr_roster if language == "fr" else en_roster
    request = fr_request if language == "fr" else en_request
    minutes = writer.compose(transcript, roster, request)
    haystack = fold_for_matching(transcript.text)
    cited = [
        *[(item.statement, item.citations) for item in minutes.decisions],
        *[(item.description, item.citations) for item in minutes.actions],
        *[(item.question, item.citations) for item in minutes.open_questions],
    ]
    assert cited
    for _, citations in cited:
        assert citations
        for citation in citations:
            assert fold_for_matching(citation.quote.rstrip("…")) in haystack
            assert citation.speaker in transcript.speakers
            assert citation.span.duration >= 0.0
            assert citation.span.start >= transcript.utterances[0].span.start
            assert citation.span.end <= transcript.utterances[-1].span.end + 0.001


def test_citation_span_matches_the_quoted_utterance(writer, fr_transcript, fr_roster, fr_request):
    minutes = writer.compose(fr_transcript, fr_roster, fr_request)
    citation = minutes.decisions[0].citations[0]
    speaking = [
        utterance
        for utterance in fr_transcript.utterances
        if utterance.span.intersects(citation.span)
    ]
    assert speaking
    assert any(fold_for_matching(citation.quote) in fold_for_matching(u.text) for u in speaking)


def test_topics_cover_the_whole_meeting(writer, en_transcript, en_roster, en_request):
    minutes = writer.compose(en_transcript, en_roster, en_request)
    assert minutes.topics
    assert minutes.topics[0].span.start == en_transcript.utterances[0].span.start
    assert minutes.topics[-1].span.end == en_transcript.utterances[-1].span.end
    for topic in minutes.topics:
        assert topic.title
        assert topic.summary


def test_speaking_time_is_reported(writer, fr_transcript, fr_roster, fr_request):
    minutes = writer.compose(fr_transcript, fr_roster, fr_request)
    assert len(minutes.speaking_time) == 3
    assert sum(seconds for _, seconds in minutes.speaking_time) > 0.0


def test_speaking_time_can_be_switched_off(fr_transcript, fr_roster, fr_request):
    writer = ExtractiveMinutesWriter(include_speaking_time=False, reference_date=MEETING_DATE)
    assert writer.compose(fr_transcript, fr_roster, fr_request).speaking_time == ()


def test_citations_can_be_switched_off(fr_transcript, fr_roster, fr_request):
    writer = ExtractiveMinutesWriter(include_citations=False, reference_date=MEETING_DATE)
    minutes = writer.compose(fr_transcript, fr_roster, fr_request)
    assert all(decision.citations == () for decision in minutes.decisions)


@pytest.mark.parametrize(
    ("language", "turns"),
    [
        (
            "fr",
            (
                ("Léa", "Bonjour, le café de la machine du deuxième étage est vraiment mauvais."),
                ("Amara", "Le mien aussi, il faudra changer de fournisseur un jour."),
                ("Léa", "Le soleil est enfin revenu sur la ville après cette longue semaine."),
                ("Amara", "Oui, la lumière change tout dans les bureaux du deuxième étage."),
            ),
        ),
        (
            "en",
            (
                ("Priya", "Morning, the coffee machine on the second floor is truly terrible."),
                ("Tom", "Mine too, the beans have not been changed in a very long while."),
                ("Priya", "The sun is finally back over the city after this long grey week."),
                ("Tom", "It changes the mood in the whole office on the second floor."),
            ),
        ),
    ],
)
def test_minutes_are_never_empty_when_the_transcript_has_content(writer, language, turns):
    utterances = []
    cursor = 0.0
    for speaker, text in turns:
        utterances.append(
            Utterance(span=TimeSpan(cursor, cursor + 8.0), text=text, speaker=speaker, language=language)
        )
        cursor += 9.0
    transcript = Transcript(utterances=tuple(utterances), language=language, audio_duration=cursor)
    request = MeetingRequest(join_url="https://example.invalid", title="Small talk", language=language)
    minutes = writer.compose(transcript, Roster(), request)
    assert minutes.abstract.strip()
    assert minutes.topics
    assert minutes.topics[0].summary.strip()
    assert minutes.participants


def test_empty_transcript_does_not_crash(writer):
    request = MeetingRequest(join_url="https://example.invalid", title="Nothing", language="fr")
    minutes = writer.compose(Transcript(language="fr"), Roster(), request)
    assert isinstance(minutes, Minutes)
    assert minutes.abstract == ""
    assert minutes.decisions == ()


@pytest.mark.parametrize(
    ("language", "closing"),
    [("fr", "Merci à tous, on se retrouve lundi prochain."), ("en", "Same time next week, thanks everyone.")],
)
def test_greetings_and_closings_stay_out_of_the_summary(writer, language, closing, fr_transcript,
                                                        en_transcript, fr_roster, en_roster,
                                                        fr_request, en_request):
    transcript = fr_transcript if language == "fr" else en_transcript
    roster = fr_roster if language == "fr" else en_roster
    request = fr_request if language == "fr" else en_request
    minutes = writer.compose(transcript, roster, request)
    assert closing not in minutes.abstract
    assert all(closing not in topic.summary for topic in minutes.topics)
