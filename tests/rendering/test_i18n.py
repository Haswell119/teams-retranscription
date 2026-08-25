from __future__ import annotations

import pytest

from hansard.rendering.i18n import (
    ENGLISH,
    ENGLISH_PHRASES,
    FRENCH,
    FRENCH_PHRASES,
    Phrase,
    available_languages,
    normalise_language,
    translations_for,
)


def test_every_phrase_is_translated_in_every_catalogue():
    assert set(ENGLISH_PHRASES) == set(Phrase)
    assert set(FRENCH_PHRASES) == set(Phrase)


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("en", "en"), ("fr", "fr"), ("fr-FR", "fr"), ("FR_ca", "fr"), (" fr ", "fr")],
)
def test_known_languages_resolve(requested, expected):
    assert translations_for(requested).language == expected


@pytest.mark.parametrize("requested", [None, "", "de", "de-AT", "xx", "klingon"])
def test_unknown_languages_fall_back_to_english(requested):
    assert translations_for(requested) is ENGLISH


def test_available_languages_include_english_and_french():
    assert available_languages() == ("en", "fr")


def test_normalise_language_strips_region():
    assert normalise_language("pt-BR") == "pt"


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        (Phrase.KEY_DECISIONS, "Relevé de décisions"),
        (Phrase.ACTION_ITEMS, "Actions à mener"),
        (Phrase.OPEN_QUESTIONS, "Points ouverts"),
        (Phrase.SPEAKING_TIME, "Temps de parole"),
        (Phrase.EXECUTIVE_SUMMARY, "Synthèse"),
        (Phrase.DISCUSSION_BY_TOPIC, "Déroulé par sujet"),
        (Phrase.OWNER, "Responsable"),
        (Phrase.DUE, "Échéance"),
    ],
)
def test_french_wording(phrase, expected):
    assert FRENCH.text(phrase) == expected


def test_format_substitutes_values():
    assert FRENCH.format(Phrase.RAISED_BY, speaker="Léa") == "soulevé par Léa"


def test_month_names_are_localised():
    assert ENGLISH.month_name(6) == "June"
    assert FRENCH.month_name(6) == "juin"


def test_language_names_are_localised():
    assert ENGLISH.language_name("fr") == "French"
    assert FRENCH.language_name("en") == "anglais"
    assert FRENCH.language_name("zz") == "zz"


def test_partial_catalogue_falls_back_per_phrase():
    from hansard.rendering.i18n import Translations

    sparse = Translations(language="xx", phrases={}, months=ENGLISH.months, language_names={})
    assert sparse.text(Phrase.ACTION_ITEMS) == "Action items"
