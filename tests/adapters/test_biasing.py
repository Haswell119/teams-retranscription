from hansard.adapters.asr.biasing import VocabularyBiaser
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word


def transcript_of(text, language, confidence=0.7):
    tokens = text.split()
    words = tuple(
        Word(token, TimeSpan(index * 0.4, (index + 1) * 0.4), confidence)
        for index, token in enumerate(tokens)
    )
    return Transcript(
        utterances=(Utterance(TimeSpan(0, len(tokens) * 0.4), text, words=words),), language=language
    )


def test_french_names_are_recovered():
    result, report = VocabularyBiaser().apply(
        transcript_of("bonjour reno peux tu voir avec francois", "fr"),
        ("Renaud", "François"),
        "fr",
    )
    assert "Renaud" in result.text
    assert "François" in result.text
    assert report.count == 2


def test_english_jargon_is_recovered():
    result, _ = VocabularyBiaser().apply(
        transcript_of("we deployed graphana next to promethius", "en"), ("Grafana", "Prometheus"), "en"
    )
    assert result.text == "we deployed Grafana next to Prometheus"


def test_unrelated_words_are_left_alone():
    result, report = VocabularyBiaser().apply(
        transcript_of("le chat dort sur le canape", "fr"), ("Renaud", "Kubernetes"), "fr"
    )
    assert report.count == 0
    assert result.text == "le chat dort sur le canape"


def test_high_confidence_words_are_not_rewritten():
    result, report = VocabularyBiaser(confidence_ceiling=0.5).apply(
        transcript_of("bonjour reno", "fr", confidence=0.99), ("Renaud",), "fr"
    )
    assert report.count == 0
    assert result.text == "bonjour reno"


def test_multi_word_phrases_are_matched():
    result, _ = VocabularyBiaser().apply(
        transcript_of("merci a jean luc pour le rapport", "fr"), ("Jean-Luc",), "fr"
    )
    assert "Jean-Luc" in result.text


def test_empty_vocabulary_is_a_no_op():
    original = transcript_of("rien a signaler", "fr")
    result, report = VocabularyBiaser().apply(original, (), "fr")
    assert result is original
    assert report.count == 0
