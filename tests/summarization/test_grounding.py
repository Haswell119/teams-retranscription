from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from meetings import MEETING_DATE

from hansard.adapters.summarization.extractive import ExtractiveMinutesWriter
from hansard.adapters.summarization.grounding import (
    ClaimKind,
    GroundingOptions,
    GroundingVerifier,
    Verdict,
    build_index,
    unsupported_entities_in,
    unsupported_numbers_in,
)
from hansard.domain.minutes import ActionItem, Citation, Decision, Minutes, OpenQuestion, Topic
from hansard.domain.timespan import TimeSpan

GENERATED_AT = datetime(2026, 6, 3, 11, 0, tzinfo=UTC)


@pytest.fixture
def writer():
    return ExtractiveMinutesWriter(reference_date=MEETING_DATE, clock=lambda: GENERATED_AT)


@pytest.mark.parametrize("language", ["fr", "en"])
def test_extractive_minutes_are_fully_grounded(
    writer, language, fr_transcript, en_transcript, fr_roster, en_roster, fr_request, en_request
):
    transcript = fr_transcript if language == "fr" else en_transcript
    roster = fr_roster if language == "fr" else en_roster
    request = fr_request if language == "fr" else en_request
    minutes = writer.compose(transcript, roster, request)
    verified, report = GroundingVerifier(language=language).verify(minutes, transcript, "extractive")
    assert report.dropped == ()
    assert report.supported_ratio == 1.0
    assert report.is_clean
    assert verified.decisions == minutes.decisions
    assert verified.actions == minutes.actions


def test_hallucinated_decision_is_dropped(fr_transcript):
    minutes = Minutes(
        title="Comité",
        abstract="",
        language="fr",
        generated_at=GENERATED_AT,
        decisions=(
            Decision(
                statement="Le rachat de la société Zenith pour 250 000 euros est validé.",
                citations=(Citation(span=TimeSpan(4.0, 20.0), speaker="Camille Dubois", quote="Bonjour"),),
            ),
        ),
    )
    verified, report = GroundingVerifier(language="fr").verify(minutes, fr_transcript, "llm")
    assert verified.decisions == ()
    assert len(report.dropped) == 1
    assert report.dropped[0].kind is ClaimKind.DECISION
    assert report.dropped[0].verdict is Verdict.UNSUPPORTED
    assert "250" in report.unsupported_numbers
    assert any("zenith" in entity for entity in report.unsupported_entities)
    assert not report.is_clean


def test_english_hallucinated_action_is_dropped(en_transcript):
    minutes = Minutes(
        title="Sync",
        abstract="",
        language="en",
        generated_at=GENERATED_AT,
        actions=(
            ActionItem(
                description="Negotiate the Helsinki datacentre lease with the landlord.",
                owner="Tom Becker",
                citations=(Citation(span=TimeSpan(4.0, 20.0), speaker="Tom Becker", quote="Morning"),),
            ),
        ),
    )
    verified, report = GroundingVerifier(language="en").verify(minutes, en_transcript, "llm")
    assert verified.actions == ()
    assert len(report.dropped) == 1


def test_claim_cited_in_the_wrong_place_is_flagged_but_kept(fr_transcript):
    minutes = Minutes(
        title="Comité",
        abstract="",
        language="fr",
        generated_at=GENERATED_AT,
        decisions=(
            Decision(
                statement="On valide le passage à quatre nœuds de transcription.",
                citations=(Citation(span=TimeSpan(4.0, 12.0), speaker="Camille Dubois", quote="Bonjour"),),
            ),
        ),
    )
    verified, report = GroundingVerifier(language="fr").verify(minutes, fr_transcript, "llm")
    assert len(verified.decisions) == 1
    assert report.checks[0].verdict is Verdict.WEAK
    assert report.checks[0].global_support > report.checks[0].cited_support
    assert not report.is_clean


def test_unsupported_owner_is_cleared(en_transcript):
    minutes = Minutes(
        title="Sync",
        abstract="",
        language="en",
        generated_at=GENERATED_AT,
        actions=(
            ActionItem(
                description="Send the customer notice about the maintenance window.",
                owner="Jonathan Meier",
                citations=(
                    Citation(span=TimeSpan(99.0, 120.0), speaker="Elena Costa", quote="Can you send"),
                ),
            ),
        ),
    )
    verified, _ = GroundingVerifier(language="en").verify(minutes, en_transcript, "llm")
    assert verified.actions[0].owner is None


def test_unsupported_abstract_sentence_is_removed_and_the_rest_kept(
    fr_transcript, writer, fr_roster, fr_request
):
    grounded = writer.compose(fr_transcript, fr_roster, fr_request)
    polluted = replace(
        grounded,
        abstract=grounded.abstract + " Le conseil d'administration a nommé un nouveau directeur financier.",
    )
    verified, report = GroundingVerifier(language="fr").verify(polluted, fr_transcript, "llm")
    assert "directeur financier" not in verified.abstract
    assert verified.abstract.strip()
    assert len(report.dropped) == 1


def test_topic_key_points_are_verified(en_transcript):
    minutes = Minutes(
        title="Sync",
        abstract="",
        language="en",
        generated_at=GENERATED_AT,
        topics=(
            Topic(
                title="Migration",
                span=TimeSpan(4.0, 80.0),
                summary="The migration dry run took four hours end to end.",
                key_points=(
                    "The search index rebuild dominated the elapsed time.",
                    "The vendor offered a discount on the storage array.",
                ),
            ),
        ),
    )
    verified, report = GroundingVerifier(language="en").verify(minutes, en_transcript, "llm")
    assert verified.topics[0].summary
    assert verified.topics[0].key_points == ("The search index rebuild dominated the elapsed time.",)
    assert len(report.dropped) == 1


def test_open_question_without_support_is_dropped(fr_transcript):
    minutes = Minutes(
        title="Comité",
        abstract="",
        language="fr",
        generated_at=GENERATED_AT,
        open_questions=(
            OpenQuestion(
                question="Faut-il déménager le siège social à Bordeaux avant l'automne ?",
                raised_by="Camille Dubois",
                citations=(Citation(span=TimeSpan(4.0, 20.0), speaker="Camille Dubois", quote="Bonjour"),),
            ),
        ),
    )
    verified, report = GroundingVerifier(language="fr").verify(minutes, fr_transcript, "llm")
    assert verified.open_questions == ()
    assert report.dropped[0].kind is ClaimKind.QUESTION


def test_numbers_and_entities_are_checked_against_the_transcript(fr_transcript):
    index = build_index(fr_transcript, "fr")
    assert unsupported_numbers_in("La version 4.2 sort le 12 juin.", index) == ()
    assert unsupported_numbers_in("Le budget est de 250 000 euros.", index) == ("250", "000")
    assert unsupported_entities_in("Marc Lefèvre valide la version.", index) == ()
    assert unsupported_entities_in("La société Zenith valide la version.", index) == ("zenith",)


def test_drop_can_be_disabled_for_review_workflows(fr_transcript):
    minutes = Minutes(
        title="Comité",
        abstract="Le conseil a nommé un nouveau directeur financier à Bordeaux.",
        language="fr",
        generated_at=GENERATED_AT,
    )
    options = GroundingOptions(drop_unsupported=False)
    verified, report = GroundingVerifier(language="fr", options=options).verify(minutes, fr_transcript, "llm")
    assert verified.abstract == minutes.abstract
    assert report.dropped == ()
    assert report.checks[0].verdict is Verdict.UNSUPPORTED
