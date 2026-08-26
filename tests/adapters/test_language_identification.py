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
    assert IDENTIFIER.identify_text("Right.").language is None
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
