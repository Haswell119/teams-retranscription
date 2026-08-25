import pytest

from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.evaluation.metrics.speaker import (
    concatenated_minimum_permutation_wer,
    cross_check_with_meeteval,
    diarization_error_rate,
    jaccard_error_rate,
    speaker_count_error,
    word_diarization_error_rate,
)


def diarization(*turns):
    return Diarization(
        turns=tuple(SpeakerTurn(TimeSpan(start, end), label) for label, start, end in turns),
        labels=tuple(sorted({label for label, _, _ in turns})),
    )


def transcript(*utterances):
    return Transcript(
        utterances=tuple(
            Utterance(TimeSpan(start, end), text, speaker) for speaker, start, end, text in utterances
        )
    )


def _timed(streams):
    return [
        (speaker, index * 5.0, index * 5.0 + 5.0, text)
        for index, (speaker, text) in enumerate(streams)
    ]


REFERENCE = diarization(("A", 0.0, 10.0), ("B", 10.0, 20.0))


def test_der_counts_missed_speech_only():
    result = diarization_error_rate(REFERENCE, diarization(("X", 0.0, 9.0), ("Y", 11.0, 20.0)), collar=0.0)
    assert result.missed_speech == pytest.approx(2.0)
    assert result.false_alarm == pytest.approx(0.0)
    assert result.confusion == pytest.approx(0.0)
    assert result.total_reference_speech == pytest.approx(20.0)
    assert result.der == pytest.approx(0.1)
    assert result.mapping == (("A", "X"), ("B", "Y"))


def test_der_collar_excludes_reference_boundaries():
    result = diarization_error_rate(REFERENCE, diarization(("X", 0.0, 9.0), ("Y", 11.0, 20.0)), collar=0.25)
    assert result.total_reference_speech == pytest.approx(19.0)
    assert result.missed_speech == pytest.approx(1.5)
    assert result.der == pytest.approx(1.5 / 19.0)


def test_der_counts_confusion_when_speakers_are_merged():
    result = diarization_error_rate(REFERENCE, diarization(("X", 0.0, 20.0)), collar=0.0)
    assert result.confusion == pytest.approx(10.0)
    assert result.der == pytest.approx(0.5)


def test_der_counts_false_alarm():
    result = diarization_error_rate(
        diarization(("A", 0.0, 10.0)),
        diarization(("X", 0.0, 10.0), ("Y", 10.0, 15.0)),
        collar=0.0,
    )
    assert result.false_alarm == pytest.approx(5.0)
    assert result.der == pytest.approx(0.5)


def test_der_handles_overlapping_reference_speech():
    reference = diarization(("A", 0.0, 10.0), ("B", 5.0, 15.0))
    hypothesis = diarization(("X", 0.0, 10.0))
    result = diarization_error_rate(reference, hypothesis, collar=0.0)
    assert result.total_reference_speech == pytest.approx(20.0)
    assert result.missed_speech == pytest.approx(10.0)
    assert result.der == pytest.approx(0.5)
    skipped = diarization_error_rate(reference, hypothesis, collar=0.0, skip_overlap=True)
    assert skipped.total_reference_speech == pytest.approx(10.0)
    assert skipped.missed_speech == pytest.approx(5.0)


def test_jaccard_error_rate_is_one_minus_intersection_over_union():
    result = jaccard_error_rate(REFERENCE, diarization(("X", 0.0, 9.0), ("Y", 11.0, 20.0)))
    assert dict(result.per_speaker)["A"] == pytest.approx(0.1)
    assert dict(result.per_speaker)["B"] == pytest.approx(0.1)
    assert result.jer == pytest.approx(0.1)


def test_jaccard_error_rate_punishes_unmapped_speaker():
    result = jaccard_error_rate(REFERENCE, diarization(("X", 0.0, 20.0)))
    assert result.jer == pytest.approx(0.75)


def test_speaker_count_error_is_signed():
    assert speaker_count_error(REFERENCE, diarization(("X", 0.0, 20.0))) == -1
    oversplit = diarization(("X", 0.0, 5.0), ("Y", 5.0, 10.0), ("Z", 10.0, 20.0))
    assert speaker_count_error(REFERENCE, oversplit) == 1


def test_word_diarization_error_rate_counts_misattributed_words():
    reference = transcript(("A", 0.0, 5.0, "hello world"), ("B", 5.0, 10.0, "good bye now"))
    perfect = transcript(("S1", 0.0, 5.0, "hello world"), ("S2", 5.0, 10.0, "good bye now"))
    shifted = transcript(("S1", 0.0, 5.0, "hello world good"), ("S2", 5.0, 10.0, "bye now"))
    assert word_diarization_error_rate(reference, perfect) == pytest.approx(0.0)
    assert word_diarization_error_rate(reference, shifted) == pytest.approx(0.2)


def test_cpwer_is_invariant_to_speaker_naming():
    reference = transcript(("A", 0.0, 5.0, "hello world how are you"), ("B", 5.0, 10.0, "i am fine thanks"))
    hypothesis = transcript(
        ("spk1", 0.0, 5.0, "i am fine thanks"),
        ("spk2", 5.0, 10.0, "hello world how are you"),
    )
    result = concatenated_minimum_permutation_wer(reference, hypothesis)
    assert result.wer == pytest.approx(0.0)
    assert result.reference_words == 9
    assert result.assignment == (("A", "spk2"), ("B", "spk1"))


def test_cpwer_accumulates_errors_of_the_best_permutation():
    reference = transcript(("A", 0.0, 5.0, "the cat sat on the mat"), ("B", 5.0, 10.0, "dogs bark loudly"))
    hypothesis = transcript(("S1", 0.0, 5.0, "the cat sat on a mat"), ("S2", 5.0, 10.0, "dogs bark"))
    result = concatenated_minimum_permutation_wer(reference, hypothesis)
    assert (result.substitutions, result.deletions, result.insertions) == (1, 1, 0)
    assert result.wer == pytest.approx(2 / 9)


def test_cpwer_charges_extra_hypothesis_speakers_as_insertions():
    reference = transcript(("A", 0.0, 5.0, "one two three"))
    hypothesis = transcript(("S1", 0.0, 5.0, "one two three"), ("S2", 5.0, 10.0, "four five"))
    result = concatenated_minimum_permutation_wer(reference, hypothesis)
    assert result.insertions == 2
    assert result.false_alarm_speakers == 1
    assert result.wer == pytest.approx(2 / 3)


def test_cpwer_charges_missing_hypothesis_speakers_as_deletions():
    reference = transcript(("A", 0.0, 5.0, "one two three"), ("B", 5.0, 10.0, "four five"))
    hypothesis = transcript(("S1", 0.0, 5.0, "one two three"))
    result = concatenated_minimum_permutation_wer(reference, hypothesis)
    assert result.deletions == 2
    assert result.missed_speakers == 1
    assert result.wer == pytest.approx(2 / 5)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("reference_stream", "hypothesis_stream"),
    [
        (
            (("A", "hello world how are you"), ("B", "i am fine thanks")),
            (("spk1", "i am fine thanks"), ("spk2", "hello world how are you")),
        ),
        (
            (("A", "the cat sat on the mat"), ("B", "dogs bark loudly")),
            (("S1", "the cat sat on a mat"), ("S2", "dogs bark")),
        ),
        (
            (("A", "one two three"),),
            (("S1", "one two three"), ("S2", "four five")),
        ),
    ],
)
def test_cpwer_agrees_with_meeteval(reference_stream, hypothesis_stream):
    reference = transcript(*_timed(reference_stream))
    hypothesis = transcript(*_timed(hypothesis_stream))
    expected = cross_check_with_meeteval(reference, hypothesis)
    if expected is None:
        pytest.skip("meeteval is not installed")
    assert concatenated_minimum_permutation_wer(reference, hypothesis).wer == pytest.approx(expected)
