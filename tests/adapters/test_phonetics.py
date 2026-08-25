import pytest

from hansard.adapters.asr.phonetics import similarity, sound_key, strip_accents


def test_strip_accents_preserves_letters():
    assert strip_accents("Aurélie Fontaine") == "Aurelie Fontaine"
    assert strip_accents("çà et là") == "ca et la"


@pytest.mark.parametrize(
    ("spoken", "written"),
    [("reno", "Renaud"), ("francois", "François"), ("aurelie", "Aurélie"), ("jean luc", "Jean-Luc")],
)
def test_french_homophones_share_a_key(spoken, written):
    assert sound_key(spoken, "fr") == sound_key(written, "fr")


@pytest.mark.parametrize(("spoken", "written"), [("graphana", "Grafana"), ("promethius", "Prometheus")])
def test_english_homophones_share_a_key(spoken, written):
    assert sound_key(spoken, "en") == sound_key(written, "en")


def test_unrelated_names_do_not_match():
    assert similarity(sound_key("Aurélie", "fr"), sound_key("Sébastien", "fr")) < 0.4


def test_similarity_is_bounded():
    assert similarity("abc", "abc") == 1.0
    assert similarity("", "abc") == 0.0
    assert 0.0 <= similarity("kubernetes", "kubernets") <= 1.0


def test_sound_key_ignores_punctuation_and_case():
    assert sound_key("Jean-Luc!", "fr") == sound_key("jean luc", "fr")
