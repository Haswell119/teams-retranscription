from __future__ import annotations

from datetime import date

import pytest

from hansard.adapters.language.identification import UtteranceLanguageTagger
from hansard.adapters.summarization.extractive import ExtractiveMinutesWriter
from hansard.domain.language import MIXED
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance

REFERENCE = date(2026, 6, 3)

CONVERSATION: tuple[tuple[str, str], ...] = (
    ("Aurélie", "Bonjour à tous, on commence par le point sur le déploiement de la plateforme."),
    ("Sofia", "Thanks. The staging cluster has been green since Monday morning, no incident at all."),
    ("Aurélie", "Très bien. On valide le périmètre de la version trois, c'est acté."),
    ("Sofia", "We decided to keep the current database schema for this release."),
    ("Aurélie", "Je m'occupe du communiqué de presse avant vendredi prochain."),
    ("Marc", "I'll take the release notes and circulate them before Friday."),
    ("Aurélie", "Qui prend la migration des données, on n'a pas tranché ?"),
    ("Sofia", "Who is going to own the rollback plan if the migration fails?"),
)


def _tagged_transcript() -> Transcript:
    utterances = tuple(
        Utterance(
            span=TimeSpan(index * 20.0, index * 20.0 + 18.0),
            text=text,
            speaker=speaker,
            words=(),
        )
        for index, (speaker, text) in enumerate(CONVERSATION)
    )
    raw = Transcript(utterances=utterances, audio_duration=len(CONVERSATION) * 20.0)
    return UtteranceLanguageTagger().tag(raw)


@pytest.fixture
def minutes():
    transcript = _tagged_transcript()
    writer = ExtractiveMinutesWriter(reference_date=REFERENCE)
    request = MeetingRequest(audio_path=None, join_url="https://example.invalid/meeting", title="Sync")
    return writer.compose(transcript, Roster(), request)


def test_the_transcript_is_recognised_as_code_switched():
    profile = _tagged_transcript().language_profile
    assert profile.tag == MIXED
    assert set(profile.significant) == {"fr", "en"}


def test_the_minutes_are_stamped_as_mixed(minutes):
    assert minutes.language == MIXED


def test_decisions_are_captured_in_both_languages(minutes):
    statements = " ".join(decision.statement for decision in minutes.decisions).lower()
    assert "périmètre" in statements or "acté" in statements
    assert "database schema" in statements or "we decided" in statements


def test_actions_are_captured_in_both_languages(minutes):
    descriptions = " ".join(action.description for action in minutes.actions).lower()
    assert "communiqué" in descriptions
    assert "release notes" in descriptions


def test_open_questions_are_captured_in_both_languages(minutes):
    questions = " ".join(question.question for question in minutes.open_questions).lower()
    assert "migration des données" in questions
    assert "rollback plan" in questions


def test_a_french_deadline_resolves_even_though_the_meeting_is_mostly_bilingual(minutes):
    french = [action for action in minutes.actions if "communiqué" in action.description.lower()]
    assert french, "the French action was not extracted"
    assert french[0].due_date is not None


def test_an_english_deadline_resolves_in_the_same_meeting(minutes):
    english = [action for action in minutes.actions if "release notes" in action.description.lower()]
    assert english, "the English action was not extracted"
    assert english[0].due_date is not None


def test_nothing_is_translated(minutes):
    body = " ".join(
        [
            *(decision.statement for decision in minutes.decisions),
            *(action.description for action in minutes.actions),
            *(question.question for question in minutes.open_questions),
        ]
    )
    assert "press release" not in body.lower()
    assert "notes de version" not in body.lower()
