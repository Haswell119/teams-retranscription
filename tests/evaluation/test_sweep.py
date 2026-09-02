import json

import pytest

from hansard.config import Settings
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word
from hansard.evaluation.sweep import (
    SweepMeeting,
    SweepPoint,
    _read_transcript,
    _write_transcript,
    grid,
    score_point,
)


def word(text, start, end):
    return Word(text=text, span=TimeSpan(start, end))


def utterance(start, end, text, speaker="A"):
    pieces = text.split()
    step = (end - start) / max(len(pieces), 1)
    words = tuple(
        word(piece, start + index * step, start + (index + 1) * step) for index, piece in enumerate(pieces)
    )
    return Utterance(span=TimeSpan(start, end), text=text, speaker=speaker, words=words)


def diarization(*turns):
    resolved = tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in turns)
    return Diarization(turns=resolved, labels=tuple(dict.fromkeys(t.label for t in resolved)))


def meeting():
    reference = Transcript(
        utterances=(
            utterance(0.0, 4.0, "on parle du budget de cette annee", "A"),
            utterance(5.0, 8.0, "je ne suis pas d accord du tout", "B"),
        ),
        language="fr",
    )
    return SweepMeeting(
        identifier="m1",
        audio=__import__("pathlib").Path("m1.wav"),
        language="fr",
        reference=reference,
        reference_diarization=diarization((0.0, 4.0, "A"), (5.0, 8.0, "B")),
    )


def test_a_point_only_changes_the_settings_it_names():
    settings = Settings()
    applied = SweepPoint("x", {"merge_similarity": 0.5}).applied(settings)
    assert applied.diarization.merge_similarity == 0.5
    assert settings.diarization.merge_similarity != 0.5
    assert applied.asr.model_id == settings.asr.model_id


def test_a_point_cannot_reach_a_setting_outside_the_sweep():
    with pytest.raises(ValueError):
        SweepPoint("x", {"model_id": "something"}).applied(Settings())


def test_a_grid_names_each_point_after_its_value():
    points = grid("merge_similarity", [0.6, 0.7])
    assert [point.label for point in points] == ["merge_similarity=0.6", "merge_similarity=0.7"]
    assert points[1].overrides == {"merge_similarity": 0.7}


def test_a_grid_carries_a_shared_base():
    points = grid("merge_similarity", [0.6], base={"cluster_consolidation": True})
    assert points[0].overrides == {"cluster_consolidation": True, "merge_similarity": 0.6}


def test_a_perfect_diarization_scores_zero_confusion():
    row = score_point(
        meeting(),
        Transcript(
            utterances=(
                utterance(0.0, 4.0, "on parle du budget de cette annee"),
                utterance(5.0, 8.0, "je ne suis pas d accord du tout"),
            ),
            language="fr",
        ),
        diarization((0.0, 4.0, "c0"), (5.0, 8.0, "c1")),
        refine=False,
    )
    assert row["detected_speakers"] == 2
    assert row["reference_speakers"] == 2
    assert row["cpwer_percent"] == 0.0
    assert row["wder_percent"] == 0.0


def test_collapsing_two_speakers_is_charged_to_cpwer_not_to_word_error():
    row = score_point(
        meeting(),
        Transcript(
            utterances=(
                utterance(0.0, 4.0, "on parle du budget de cette annee"),
                utterance(5.0, 8.0, "je ne suis pas d accord du tout"),
            ),
            language="fr",
        ),
        diarization((0.0, 8.0, "c0")),
        refine=False,
    )
    assert row["detected_speakers"] == 1
    assert row["cpwer_percent"] > 0.0
    assert row["quiet_speaker_recall_percent"] == 50.0


def test_the_cache_round_trips_the_transcript_and_the_speech_spans(tmp_path):
    transcript = Transcript(
        utterances=(utterance(0.0, 4.0, "on parle du budget"),), language="fr", audio_duration=9.0
    )
    spans = (TimeSpan(0.0, 4.0), TimeSpan(5.0, 8.0))
    path = tmp_path / "m1.json"
    _write_transcript(path, transcript, spans)
    restored, _, recovered = _read_transcript(path, "fr", 9.0, object())
    assert restored.text == transcript.text
    assert restored.audio_duration == 9.0
    assert recovered == spans
    assert restored.utterances[0].words[0].text == "on"


def test_an_older_cache_without_spans_falls_back_to_the_utterances(tmp_path):
    path = tmp_path / "m1.json"
    path.write_text(
        json.dumps(
            {
                "language": "fr",
                "audio_duration": 9.0,
                "utterances": [{"start": 0.0, "end": 4.0, "text": "bonjour", "words": []}],
            }
        ),
        encoding="utf-8",
    )
    _, _, spans = _read_transcript(path, "fr", 9.0, object())
    assert spans == (TimeSpan(0.0, 4.0),)


def test_points_that_only_change_consolidation_share_a_diarizer_signature():
    from hansard.evaluation.sweep import diarizer_signature

    base = Settings()
    left = SweepPoint("a", {"merge_similarity": 0.6}).applied(base)
    right = SweepPoint("b", {"absorption_similarity": 0.9}).applied(base)
    assert diarizer_signature(left) == diarizer_signature(right)


def test_changing_the_embedding_model_changes_the_signature():
    from hansard.evaluation.sweep import diarizer_signature

    base = Settings()
    other = SweepPoint("b", {"embedding_model": "something_else.onnx"}).applied(base)
    assert diarizer_signature(base) != diarizer_signature(other)


def test_changing_a_segmentation_duration_changes_the_signature():
    from hansard.evaluation.sweep import diarizer_signature

    base = Settings()
    other = SweepPoint("b", {"min_duration_off": 0.0}).applied(base)
    assert diarizer_signature(base) != diarizer_signature(other)
