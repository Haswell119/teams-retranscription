from __future__ import annotations

import pytest

from hansard.domain.language import (
    MIXED,
    LanguageProfile,
    languages_of,
    merge_tags,
    normalise_tag,
    profile_from_counts,
    resolve_meeting_language,
)
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("fr-FR", "fr"),
        ("en_US", "en"),
        ("  FR  ", "fr"),
        ("mixed", MIXED),
        ("multilingual", MIXED),
        ("auto", None),
        ("", None),
        (None, None),
    ],
)
def test_language_tags_are_normalised(raw, expected):
    assert normalise_tag(raw) == expected


def test_merging_two_different_tags_yields_mixed():
    assert merge_tags(["fr", "en"]) == MIXED
    assert merge_tags(["fr", "fr", None]) == "fr"
    assert merge_tags([None, None]) is None
    assert merge_tags(["en", MIXED]) == MIXED


def test_a_mixed_tag_expands_to_every_supported_language():
    assert languages_of(MIXED) == ("en", "fr")
    assert languages_of("fr") == ("fr",)
    assert languages_of(None) == ("en", "fr")


def test_the_first_usable_candidate_wins():
    assert resolve_meeting_language(None, "auto", "fr-FR") == "fr"
    assert resolve_meeting_language(None, None) is None


def test_a_marginal_second_language_does_not_make_a_meeting_mixed():
    profile = profile_from_counts({"fr": 990.0, "en": 10.0}, {"fr": 900.0, "en": 4.0})
    assert profile.dominant == "fr"
    assert profile.tag == "fr"
    assert not profile.is_mixed


def test_a_substantial_second_language_makes_a_meeting_mixed():
    profile = profile_from_counts({"fr": 600.0, "en": 400.0}, {"fr": 500.0, "en": 300.0})
    assert profile.tag == MIXED
    assert profile.is_mixed
    assert profile.dominant == "fr"
    assert profile.secondary == ("en",)


def test_a_short_but_long_running_second_language_still_counts():
    profile = profile_from_counts({"fr": 1000.0, "en": 20.0}, {"fr": 900.0, "en": 45.0})
    assert profile.is_mixed


def test_an_empty_profile_has_no_tag():
    empty = LanguageProfile(shares={}, seconds={})
    assert empty.tag is None
    assert empty.dominant is None
    assert not empty.is_mixed


def test_a_transcript_derives_its_profile_from_its_utterances():
    transcript = Transcript(
        utterances=(
            Utterance(span=TimeSpan(0.0, 30.0), text=" ".join(["mot"] * 60), language="fr"),
            Utterance(span=TimeSpan(30.0, 60.0), text=" ".join(["word"] * 40), language="en"),
        ),
        audio_duration=60.0,
    )
    assert transcript.is_code_switched
    assert transcript.language_profile.tag == MIXED
    assert transcript.language_profile.share_of("fr") == pytest.approx(0.6)


def test_relabelling_a_transcript_requires_one_tag_per_utterance():
    transcript = Transcript(utterances=(Utterance(span=TimeSpan(0.0, 1.0), text="hello"),))
    assert transcript.with_languages(["en"]).utterances[0].language == "en"
    with pytest.raises(ValueError, match="one language tag"):
        transcript.with_languages(["en", "fr"])
