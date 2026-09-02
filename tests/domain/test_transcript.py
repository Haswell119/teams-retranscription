from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word


def utterance(start, end, text, speaker="A", language=None):
    words = tuple(
        Word(token, TimeSpan(start + index * 0.1, start + (index + 1) * 0.1))
        for index, token in enumerate(text.split())
    )
    return Utterance(TimeSpan(start, end), text, speaker=speaker, language=language, words=words)


def test_text_joins_utterances():
    transcript = Transcript(utterances=(utterance(0, 1, "bonjour"), utterance(1, 2, "le monde")))
    assert transcript.text == "bonjour le monde"


def test_merged_by_speaker_joins_contiguous_same_speaker():
    transcript = Transcript(utterances=(utterance(0, 1, "bonjour"), utterance(1.2, 2, "le monde")))
    merged = transcript.merged_by_speaker(max_gap=0.5)
    assert len(merged.utterances) == 1
    assert merged.utterances[0].text == "bonjour le monde"


def test_merged_by_speaker_keeps_different_speakers():
    transcript = Transcript(utterances=(utterance(0, 1, "bonjour", "A"), utterance(1.1, 2, "salut", "B")))
    assert len(transcript.merged_by_speaker().utterances) == 2


def test_merged_by_speaker_keeps_a_speakers_two_languages_apart():
    transcript = Transcript(
        utterances=(
            utterance(0, 1, "the dinner was mediocre", language="en"),
            utterance(1.2, 2, "un matin on remit une lettre", language="fr"),
        )
    )
    merged = transcript.merged_by_speaker(max_gap=0.5)
    assert [item.language for item in merged.utterances] == ["en", "fr"]


def test_merged_by_speaker_adopts_the_language_of_an_untagged_neighbour():
    transcript = Transcript(
        utterances=(
            utterance(0, 1, "bonjour", language=None),
            utterance(1.2, 2, "le monde", language="fr"),
        )
    )
    merged = transcript.merged_by_speaker(max_gap=0.5)
    assert len(merged.utterances) == 1
    assert merged.utterances[0].language == "fr"


def test_merged_by_speaker_joins_when_both_agree_on_the_language():
    transcript = Transcript(
        utterances=(
            utterance(0, 1, "bonjour", language="fr"),
            utterance(1.2, 2, "le monde", language="fr"),
        )
    )
    merged = transcript.merged_by_speaker(max_gap=0.5)
    assert len(merged.utterances) == 1
    assert merged.utterances[0].language == "fr"


def test_merged_by_speaker_respects_gap():
    transcript = Transcript(utterances=(utterance(0, 1, "un"), utterance(9, 10, "deux")))
    assert len(transcript.merged_by_speaker(max_gap=1.0).utterances) == 2


def test_renamed_applies_mapping_to_words():
    transcript = Transcript(utterances=(utterance(0, 1, "bonjour", "speaker_00"),))
    renamed = transcript.renamed({"speaker_00": "Aurélie"})
    assert renamed.utterances[0].speaker == "Aurélie"
    assert all(word.speaker == "Aurélie" for word in renamed.words)


def test_speakers_preserves_first_seen_order():
    transcript = Transcript(
        utterances=(utterance(0, 1, "a", "B"), utterance(1, 2, "b", "A"), utterance(2, 3, "c", "B"))
    )
    assert transcript.speakers == ("B", "A")
