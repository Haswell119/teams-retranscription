from dataclasses import replace
from pathlib import Path

import pytest

from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.transcript import Transcript
from hansard.evaluation.datasets import load_meetings, load_reference_json
from hansard.evaluation.metrics.speaker import (
    concatenated_minimum_permutation_wer,
    diarization_error_rate,
    jaccard_error_rate,
    speaker_count_error,
    time_constrained_cpwer,
    word_diarization_counts,
    word_diarization_error_rate,
)

SYNTHETIC = Path("/home/user/eval_data/synthetic")
THREE_SPEAKERS = SYNTHETIC / "meeting_3spk.ref.json"

pytestmark = pytest.mark.skipif(not THREE_SPEAKERS.exists(), reason="synthetic meetings are absent")


def relabelled(sample):
    mapping = {name: f"speaker_{index}" for index, name in enumerate(sorted(sample.reference.speakers))}
    turns = tuple(SpeakerTurn(turn.span, mapping[turn.label]) for turn in sample.reference_diarization.turns)
    diarization = Diarization(turns=turns, labels=tuple(sorted(mapping.values())))
    return sample.reference.renamed(mapping), diarization


def test_reference_bundle_is_consistent():
    sample = load_reference_json(THREE_SPEAKERS)
    assert sample.identifier == "meeting_3spk"
    assert sample.audio_path == SYNTHETIC / "meeting_3spk.wav"
    assert len(sample.reference.speakers) == 3
    assert sample.reference_diarization is not None
    assert sample.reference_diarization.speaker_count == 3
    assert len(sample.reference_diarization.turns) == len(sample.reference.utterances)


def test_all_synthetic_meetings_load_with_matching_speaker_counts():
    meetings = load_meetings(SYNTHETIC)
    assert [meeting.identifier for meeting in meetings] == [
        "meeting_3spk",
        "meeting_6spk",
        "meeting_9spk",
    ]
    assert [meeting.reference_diarization.speaker_count for meeting in meetings] == [3, 6, 9]


def test_a_perfect_system_scores_zero_on_every_speaker_metric():
    sample = load_reference_json(THREE_SPEAKERS)
    transcript, diarization = relabelled(sample)
    der = diarization_error_rate(sample.reference_diarization, diarization, collar=0.0)
    assert der.der == pytest.approx(0.0)
    assert jaccard_error_rate(sample.reference_diarization, diarization).jer == pytest.approx(0.0)
    assert concatenated_minimum_permutation_wer(sample.reference, transcript).wer == pytest.approx(0.0)
    assert word_diarization_error_rate(sample.reference, transcript) == pytest.approx(0.0)
    assert speaker_count_error(sample.reference_diarization, diarization) == 0


def test_merging_two_speakers_is_charged_as_confusion():
    sample = load_reference_json(THREE_SPEAKERS)
    _, diarization = relabelled(sample)
    merged = Diarization(
        turns=tuple(
            SpeakerTurn(turn.span, "speaker_0" if turn.label in {"speaker_0", "speaker_1"} else turn.label)
            for turn in diarization.turns
        ),
        labels=("speaker_0", "speaker_2"),
    )
    result = diarization_error_rate(sample.reference_diarization, merged, collar=0.0)
    assert result.missed_speech == pytest.approx(0.0)
    assert result.false_alarm == pytest.approx(0.0)
    assert result.confusion == pytest.approx(43.224, abs=1e-3)
    assert result.total_reference_speech == pytest.approx(139.024, abs=1e-3)
    assert result.der == pytest.approx(43.224 / 139.024, abs=1e-6)
    assert speaker_count_error(sample.reference_diarization, merged) == -1


def test_swapping_two_turns_is_charged_word_by_word():
    sample = load_reference_json(THREE_SPEAKERS)
    transcript, _ = relabelled(sample)
    utterances = list(transcript.utterances)
    first, third = utterances[0], utterances[2]
    utterances[0] = first.attributed_to(third.speaker)
    utterances[2] = third.attributed_to(first.speaker)
    swapped = Transcript(utterances=tuple(utterances))
    wrong, aligned = word_diarization_counts(sample.reference, swapped)
    assert aligned == 394
    assert wrong == len(first.text.split()) + len(third.text.split())
    assert word_diarization_error_rate(sample.reference, swapped) == pytest.approx(52 / 394)


@pytest.mark.slow
def test_time_constrained_cpwer_on_a_full_meeting():
    sample = load_reference_json(THREE_SPEAKERS)
    transcript, _ = relabelled(sample)
    assert time_constrained_cpwer(sample.reference, transcript, collar=5.0).wer == pytest.approx(0.0)
    late = Transcript(
        utterances=tuple(replace(item, span=item.span.shifted(60.0)) for item in transcript.utterances)
    )
    assert time_constrained_cpwer(sample.reference, late, collar=5.0).wer > 0.5
    assert concatenated_minimum_permutation_wer(sample.reference, late).wer == pytest.approx(0.0)
