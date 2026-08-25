from hansard.adapters.attribution.fusion import WordLevelAttributor
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word


def build(words):
    items = tuple(Word(text, TimeSpan(start, end)) for text, start, end in words)
    span = TimeSpan(items[0].span.start, items[-1].span.end)
    return Transcript(utterances=(Utterance(span, " ".join(word.text for word in items), words=items),))


def test_words_follow_the_dominant_turn():
    transcript = build([("alpha", 0.0, 1.0), ("beta", 1.0, 2.0), ("gamma", 5.0, 6.0)])
    diarization = Diarization(
        turns=(SpeakerTurn(TimeSpan(0, 2.5), "A"), SpeakerTurn(TimeSpan(4.5, 7), "B")),
        labels=("A", "B"),
    )
    result = WordLevelAttributor().attribute(transcript, diarization)
    assigned = {word.text: word.speaker for word in result.words}
    assert assigned == {"alpha": "A", "beta": "A", "gamma": "B"}


def test_single_speaker_diarization_relabels_everything():
    transcript = build([("alpha", 0.0, 1.0), ("beta", 1.0, 2.0)])
    diarization = Diarization(turns=(SpeakerTurn(TimeSpan(0, 5), "solo"),), labels=("solo",))
    result = WordLevelAttributor().attribute(transcript, diarization)
    assert {utterance.speaker for utterance in result.utterances} == {"solo"}


def test_smoothing_absorbs_an_isolated_flip():
    words = [(f"w{index}", index * 0.5, index * 0.5 + 0.5) for index in range(8)]
    transcript = build(words)
    turns = (
        SpeakerTurn(TimeSpan(0, 1.7), "A"),
        SpeakerTurn(TimeSpan(1.7, 2.1), "B"),
        SpeakerTurn(TimeSpan(2.1, 4.0), "A"),
    )
    result = WordLevelAttributor(switch_probability=0.01).attribute(
        transcript, Diarization(turns=turns, labels=("A", "B"))
    )
    assert result.speakers == ("A",)


def test_empty_diarization_returns_transcript_unchanged():
    transcript = build([("alpha", 0.0, 1.0)])
    assert WordLevelAttributor().attribute(transcript, Diarization()) is transcript


def test_speaker_change_splits_an_utterance():
    transcript = build([("alpha", 0.0, 1.0), ("beta", 3.0, 4.0)])
    diarization = Diarization(
        turns=(SpeakerTurn(TimeSpan(0, 1.5), "A"), SpeakerTurn(TimeSpan(2.5, 4.5), "B")),
        labels=("A", "B"),
    )
    result = WordLevelAttributor().attribute(transcript, diarization)
    assert len(result.utterances) == 2
    assert [utterance.speaker for utterance in result.utterances] == ["A", "B"]
