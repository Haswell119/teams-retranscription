from __future__ import annotations

from datetime import date

import pytest
from meetings import MEETING_DATE

from hansard.adapters.summarization.citations import sentence_units
from hansard.adapters.summarization.dates import extract_due_date
from hansard.adapters.summarization.extraction import (
    CandidateExtractor,
    ExtractionOptions,
    build_directory,
)
from hansard.domain.speakers import Participant, Roster
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance

REFERENCE = date(2026, 6, 3)


def _transcript(turns: tuple[tuple[str, str], ...], language: str) -> Transcript:
    utterances = []
    cursor = 0.0
    for speaker, text in turns:
        duration = max(4.0, len(text.split()) * 0.4)
        utterances.append(
            Utterance(
                span=TimeSpan(cursor, cursor + duration),
                text=text,
                speaker=speaker,
                language=language,
            )
        )
        cursor += duration + 1.0
    return Transcript(utterances=tuple(utterances), language=language, audio_duration=cursor)


def _roster(*names: str) -> Roster:
    return Roster(
        participants=tuple(
            Participant(identifier=name.split()[0].lower(), display_name=name) for name in names
        )
    )


def _extract(turns, language, names, options=None):
    transcript = _transcript(turns, language)
    extractor = CandidateExtractor(
        language=language,
        directory=build_directory(transcript, _roster(*names)),
        options=options or ExtractionOptions(),
        reference_date=REFERENCE,
    )
    return extractor.extract(sentence_units(transcript))


FRENCH_DECISION_TURNS = (
    ("Léa Fontaine", "On part sur la version 4.2 pour le 12 juin."),
    ("Amara Okafor", "Il est décidé que la locale allemande est désactivée."),
    ("Jonas Weber", "On valide le budget de deux nœuds supplémentaires."),
    ("Léa Fontaine", "On retient l'option du fournisseur local."),
)

ENGLISH_DECISION_TURNS = (
    ("Amara Okafor", "We agreed to ship release four two on the twelfth."),
    ("Lea Fontaine", "Let's go with the local supplier for the extra nodes."),
    ("Jonas Weber", "The decision is to keep the weekly release train."),
    ("Amara Okafor", "It is decided that the German locale is disabled."),
)

FRENCH_HYPOTHETICAL_TURNS = (
    ("Léa Fontaine", "Si on décale la livraison, on pourrait valider la locale allemande."),
    ("Amara Okafor", "Je propose qu'on parte sur le 19 juin, mais c'est à confirmer."),
    ("Jonas Weber", "Il faudrait peut-être qu'on valide un budget plus large."),
    ("Léa Fontaine", "On valide le périmètre aujourd'hui ?"),
)

ENGLISH_HYPOTHETICAL_TURNS = (
    ("Amara Okafor", "If we slip the date, we could ship the German locale as well."),
    ("Lea Fontaine", "I suggest we go with the local supplier, but that is to be confirmed."),
    ("Jonas Weber", "Maybe we should approve a larger budget."),
    ("Amara Okafor", "Do we agree on the scope today?"),
)


def test_french_decisions_are_detected():
    candidates = _extract(FRENCH_DECISION_TURNS, "fr", ("Léa Fontaine", "Amara Okafor", "Jonas Weber"))
    assert len(candidates.decisions) == 4
    assert all(decision.is_strong for decision in candidates.decisions)


def test_english_decisions_are_detected():
    candidates = _extract(ENGLISH_DECISION_TURNS, "en", ("Amara Okafor", "Lea Fontaine", "Jonas Weber"))
    assert len(candidates.decisions) == 4


def test_french_hypotheticals_are_not_decisions():
    candidates = _extract(FRENCH_HYPOTHETICAL_TURNS, "fr", ("Léa Fontaine", "Amara Okafor", "Jonas Weber"))
    assert candidates.decisions == ()


def test_english_hypotheticals_are_not_decisions():
    candidates = _extract(ENGLISH_HYPOTHETICAL_TURNS, "en", ("Amara Okafor", "Lea Fontaine", "Jonas Weber"))
    assert candidates.decisions == ()


def test_decision_rationale_is_split_from_the_statement():
    turns = (
        ("Léa Fontaine", "On valide le passage à quatre nœuds pour absorber la charge."),
    )
    candidates = _extract(turns, "fr", ("Léa Fontaine",))
    decision = candidates.decisions[0]
    assert decision.statement == "On valide le passage à quatre nœuds"
    assert decision.rationale == "pour absorber la charge"


FRENCH_ACTION_TURNS = (
    ("Léa Fontaine", "Je m'en occupe et je relance l'agence demain."),
    ("Amara Okafor", "Jonas, peux-tu préparer le budget pour vendredi prochain ?"),
    ("Jonas Weber", "Oui."),
    ("Amara Okafor", "Il faut aussi relire la documentation d'ici la fin du mois."),
)

ENGLISH_ACTION_TURNS = (
    ("Lea Fontaine", "I'll take the release notes and send them tomorrow."),
    ("Amara Okafor", "Jonas, can you prepare the budget by next Tuesday?"),
    ("Jonas Weber", "Sure."),
    ("Amara Okafor", "We need to review the documentation by the end of the month."),
)


def test_french_actions_owners_and_dates():
    candidates = _extract(FRENCH_ACTION_TURNS, "fr", ("Léa Fontaine", "Amara Okafor", "Jonas Weber"))
    owners = [action.owner for action in candidates.actions]
    dates = [action.due.value if action.due else None for action in candidates.actions]
    assert "Léa Fontaine" in owners
    assert "Jonas Weber" in owners
    assert "2026-06-04" in dates
    assert "2026-06-12" in dates
    assert "2026-06-30" in dates


def test_english_actions_owners_and_dates():
    candidates = _extract(ENGLISH_ACTION_TURNS, "en", ("Lea Fontaine", "Amara Okafor", "Jonas Weber"))
    owners = [action.owner for action in candidates.actions]
    dates = [action.due.value if action.due else None for action in candidates.actions]
    assert "Lea Fontaine" in owners
    assert "Jonas Weber" in owners
    assert "2026-06-04" in dates
    assert "2026-06-09" in dates
    assert "2026-06-30" in dates


def test_owner_is_left_empty_rather_than_guessed():
    turns = (
        ("Léa Fontaine", "Il faut relire les chaînes de facturation avant la livraison."),
        ("Amara Okafor", "C'est un vrai sujet, on en reparle."),
        ("Jonas Weber", "Effectivement."),
    )
    candidates = _extract(turns, "fr", ("Léa Fontaine", "Amara Okafor", "Jonas Weber"))
    assert [action.owner for action in candidates.actions] == [None]


def test_mention_wins_over_every_other_owner_signal():
    turns = (("Léa Fontaine", "Peux-tu ouvrir le ticket de traduction @jonas.weber ?"),)
    candidates = _extract(turns, "fr", ("Léa Fontaine", "Amara Okafor", "Jonas Weber"))
    assert candidates.actions[0].owner == "Jonas Weber"


def test_request_and_acceptance_become_one_action():
    turns = (
        ("Amara Okafor", "Léa, peux-tu envoyer le communiqué pour le 10 juin ?"),
        ("Léa Fontaine", "Oui, je m'en occupe, je le prépare cette semaine."),
    )
    candidates = _extract(turns, "fr", ("Léa Fontaine", "Amara Okafor"))
    assert len(candidates.actions) == 1
    action = candidates.actions[0]
    assert action.owner == "Léa Fontaine"
    assert action.due is not None
    assert action.due.value == "2026-06-10"
    assert len(action.support) == 1


def test_distinct_tasks_are_not_merged():
    turns = (
        ("Amara Okafor", "Tom, can you send the customer notice by Friday?"),
        ("Tom Becker", "Yes. I will also rerun the migration dry run with the index rebuild disabled."),
    )
    candidates = _extract(turns, "en", ("Amara Okafor", "Tom Becker"))
    assert len(candidates.actions) == 2


def test_unanswered_question_is_open_and_answered_one_is_not():
    turns = (
        ("Léa Fontaine", "Qui prend en charge la communication client sur cet incident ?"),
        ("Amara Okafor", "Bonne question, on en reparle plus tard."),
        ("Léa Fontaine", "Est-ce que la locale allemande est prête pour la livraison ?"),
        ("Amara Okafor", "Oui, la locale allemande est prête depuis hier."),
    )
    candidates = _extract(turns, "fr", ("Léa Fontaine", "Amara Okafor"))
    questions = [question.unit.text for question in candidates.questions]
    assert len(questions) == 1
    assert "communication client" in questions[0]


def test_english_unanswered_question_is_open():
    turns = (
        ("Priya Raman", "Who owns the postmortem for the Friday escalation?"),
        ("Elena Costa", "We can settle that offline, I would rather not guess in the meeting."),
    )
    candidates = _extract(turns, "en", ("Priya Raman", "Elena Costa"))
    assert len(candidates.questions) == 1


@pytest.mark.parametrize(
    ("phrase", "language", "expected"),
    [
        ("vendredi prochain", "fr", "2026-06-12"),
        ("d'ici la fin du mois", "fr", "2026-06-30"),
        ("le 12 mars", "fr", "2027-03-12"),
        ("demain", "fr", "2026-06-04"),
        ("dans deux semaines", "fr", None),
        ("next Tuesday", "en", "2026-06-09"),
        ("by EOW", "en", "2026-06-05"),
        ("on March 12", "en", "2027-03-12"),
        ("in 2 weeks", "en", "2026-06-17"),
    ],
)
def test_date_normalisation(phrase, language, expected):
    found = extract_due_date(f"On fait ça {phrase}.", language, REFERENCE)
    if expected is None:
        assert found is None or found.resolved is None
    else:
        assert found is not None
        assert found.value == expected


def test_date_stays_raw_without_a_meeting_date():
    found = extract_due_date("Can you send it by next Tuesday?", "en", None)
    assert found is not None
    assert found.resolved is None
    assert found.value == "next Tuesday"


def test_meeting_fixture_dates_are_resolved(fr_transcript, fr_roster, meeting_date):
    extractor = CandidateExtractor(
        language="fr",
        directory=build_directory(fr_transcript, fr_roster),
        reference_date=meeting_date,
    )
    candidates = extractor.extract(sentence_units(fr_transcript))
    assert meeting_date == MEETING_DATE
    assert [action.due.value for action in candidates.actions if action.due] == [
        "2026-06-04",
        "2026-06-05",
        "2026-06-10",
    ]
