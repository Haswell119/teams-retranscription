from __future__ import annotations

import pytest

from hansard.adapters.language.identification import (
    TextLanguageIdentifier,
    UtteranceLanguageTagger,
)
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance

IDENTIFIER = TextLanguageIdentifier()


def _transcript(rows: list[tuple[str, str]]) -> Transcript:
    utterances = tuple(
        Utterance(span=TimeSpan(index * 5.0, index * 5.0 + 4.0), text=text, speaker=speaker)
        for index, (speaker, text) in enumerate(rows)
    )
    return Transcript(utterances=utterances, audio_duration=len(rows) * 5.0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Donc si je résume, il faut valider le périmètre avant demain matin.", "fr"),
        ("So on my side, I'll take the release notes before Friday.", "en"),
        ("On part sur la version trois, je m'occupe du communiqué.", "fr"),
        ("Can you check the deployment requirements please?", "en"),
        ("Oui.", "fr"),
        ("Yes", "en"),
    ],
)
def test_a_sentence_is_attributed_to_the_language_it_was_spoken_in(text, expected):
    assert IDENTIFIER.identify_text(text).language == expected


def test_a_french_sentence_carrying_english_loanwords_stays_french():
    verdict = IDENTIFIER.identify_text("Le kickoff meeting est prévu pour la semaine prochaine.")
    assert verdict.language == "fr"


def test_a_sentence_without_evidence_is_left_undecided():
    assert IDENTIFIER.identify_text("Meridian 42, PostgreSQL.").language is None
    assert IDENTIFIER.identify_text("").language is None


def test_an_undecided_utterance_inherits_the_language_of_its_own_speaker():
    tagged = UtteranceLanguageTagger().tag(
        _transcript(
            [
                ("Alice", "Donc il faut valider le périmètre avant demain matin."),
                ("Bob", "So I'll take the release notes and circulate them before Friday."),
                ("Alice", "Parfait."),
            ]
        )
    )
    assert [utterance.language for utterance in tagged.utterances] == ["fr", "en", "fr"]


def test_a_code_switched_meeting_reports_both_languages():
    tagged = UtteranceLanguageTagger().tag(
        _transcript(
            [
                ("Alice", "Il faut valider le périmètre avant demain matin, c'est important."),
                ("Bob", "So I will take the release notes and circulate them before Friday."),
            ]
        )
    )
    profile = tagged.language_profile
    assert profile.tag == "mixed"
    assert profile.is_mixed
    assert set(profile.significant) == {"fr", "en"}


def test_a_single_language_meeting_is_not_reported_as_mixed():
    tagged = UtteranceLanguageTagger().tag(
        _transcript(
            [
                ("Alice", "Il faut valider le périmètre avant demain matin."),
                ("Alice", "On acte la décision et on passe au point suivant."),
            ]
        )
    )
    assert tagged.language_profile.tag == "fr"
    assert not tagged.language_profile.is_mixed


def test_an_explicit_default_language_fills_utterances_nothing_decided():
    tagged = UtteranceLanguageTagger(default_language="fr").tag(_transcript([("Alice", "Mm.")]))
    assert tagged.utterances[0].language == "fr"


def test_tagging_an_empty_transcript_is_a_no_op():
    empty = Transcript()
    assert UtteranceLanguageTagger().tag(empty) is empty


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sprint review jeudi, go/no-go vendredi.", "fr"),
        ("Kickoff mardi, demo jeudi, no-go vendredi.", "fr"),
        ("The go/no-go is on Thursday, sprint review on Friday.", "en"),
    ],
)
def test_one_borrowed_token_does_not_flip_a_whole_agenda_sentence(text, expected):
    assert IDENTIFIER.identify_text(text).language == expected


@pytest.mark.parametrize(
    ("french", "english"),
    [("Oui.", "Yes."), ("Non.", "Right."), ("Voilà.", "Sure."), ("Merci.", "Agreed.")],
)
def test_backchannels_are_recognised_symmetrically_in_both_languages(french, english):
    assert IDENTIFIER.identify_text(french).language == "fr"
    assert IDENTIFIER.identify_text(english).language == "en"


def test_a_borrowing_shared_by_both_languages_stays_undecided():
    assert IDENTIFIER.identify_text("Ok.").language is None
    assert IDENTIFIER.identify_text("Okay.").language is None


def test_an_acknowledgement_follows_the_language_its_speaker_switches_into():
    tagged = UtteranceLanguageTagger().tag(
        _transcript(
            [
                ("Sofia", "Morning everyone, I have pushed the numbers."),
                ("Aurélie", "Bonjour, on commence par la migration des données."),
                ("Sofia", "Ok."),
                ("Sofia", "We will take the staging instance then."),
            ]
        )
    )
    assert [utterance.language for utterance in tagged.utterances] == ["en", "fr", "en", "en"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Le pipeline CI est down, on rollback le deploy et on debug le staging.", "fr"),
        ("Le kickoff meeting du workshop design est un vrai blocker.", "fr"),
        ("Send the Meridian dossier to Legrand before the Nantes rendez-vous.", "en"),
        ("C'est valide de mon cote, on gele le contrat d'API jusqu'au pilote.", "fr"),
        ("ON VALIDE LE PÉRIMÈTRE AVANT VENDREDI PROCHAIN.", "fr"),
    ],
)
def test_borrowings_accents_and_case_do_not_change_the_matrix_language(text, expected):
    assert IDENTIFIER.identify_text(text).language == expected
