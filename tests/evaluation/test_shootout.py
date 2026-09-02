import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hansard.domain.errors import ConfigurationError
from hansard.domain.timespan import TimeSpan
from hansard.evaluation.shootout import (
    EngineSpec,
    ShootoutSegment,
    budgeted,
    preset,
    score_engine,
    shootout_payload,
    summ_re_segments,
)


def segment(meeting, start, end, reference="bonjour", language="fr", audio=Path("m.wav")):
    return ShootoutSegment(
        corpus="summ-re",
        meeting=meeting,
        speaker="017",
        language=language,
        audio=audio,
        span=TimeSpan(start, end),
        reference=reference,
    )


def write_meeting(root, name, tracks, seconds=12.0):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    tone = np.sin(np.linspace(0.0, 400.0, int(seconds * 16_000))).astype(np.float32)
    sf.write(str(directory / "mixed.wav"), tone, 16_000)
    for speaker, records in tracks.items():
        (directory / f"{speaker}.json").write_text(json.dumps(records), encoding="utf-8")
    return directory


def test_a_budget_spreads_across_meetings_instead_of_draining_the_first():
    segments = [segment("a", index, index + 1.0) for index in range(10)]
    segments += [segment("b", index, index + 1.0) for index in range(10)]
    chosen = budgeted(segments, 4.0)
    assert {item.meeting for item in chosen} == {"a", "b"}
    assert sum(item.span.duration for item in chosen) >= 4.0


def test_a_zero_budget_keeps_every_segment():
    segments = [segment("a", index, index + 1.0) for index in range(3)]
    assert len(budgeted(segments, 0.0)) == 3


def test_a_budget_larger_than_the_corpus_keeps_every_segment():
    segments = [segment("a", index, index + 1.0) for index in range(3)]
    assert len(budgeted(segments, 500.0)) == 3


def test_the_same_budget_selects_the_same_segments_twice():
    segments = [segment("a", index, index + 1.0) for index in range(10)]
    segments += [segment("b", index, index + 1.0) for index in range(10)]
    assert budgeted(segments, 6.0) == budgeted(segments, 6.0)


def test_summ_re_segments_come_from_the_reference_boundaries(tmp_path):
    write_meeting(
        tmp_path,
        "020c_EBPZ",
        {"017": [{"start": 0.5, "end": 2.0, "text": "bonjour à tous"}]},
    )
    segments = summ_re_segments(tmp_path)
    assert len(segments) == 1
    assert segments[0].span == TimeSpan(0.5, 2.0)
    assert segments[0].language == "fr"
    assert segments[0].audio.name == "mixed.wav"


def test_short_reference_utterances_are_skipped(tmp_path):
    write_meeting(
        tmp_path,
        "020c_EBPZ",
        {"017": [{"start": 0.5, "end": 0.6, "text": "oui"}]},
    )
    assert summ_re_segments(tmp_path, minimum_seconds=0.4) == ()


def test_a_split_filters_the_meetings_it_reads(tmp_path):
    write_meeting(tmp_path, "020c_EBPZ", {"017": [{"start": 0.0, "end": 2.0, "text": "oui"}]})
    assert summ_re_segments(tmp_path, split="tuning")
    assert summ_re_segments(tmp_path, split="held-out") == ()


def test_missing_corpora_produce_no_segments(tmp_path):
    assert summ_re_segments(tmp_path / "absent") == ()


def test_an_unknown_preset_is_refused():
    with pytest.raises(ConfigurationError):
        preset("no-such-engine")


def test_every_preset_builds_valid_settings():
    from hansard.evaluation.shootout import PRESETS

    for spec in PRESETS.values():
        assert spec.settings(4).intra_op_threads == 4


def test_scoring_separates_the_languages():
    segments = [
        segment("a", 0.0, 1.0, reference="le budget", language="fr"),
        segment("a", 1.0, 2.0, reference="the budget", language="en"),
    ]
    outcome = score_engine(
        EngineSpec(name="stub"), segments, ["le budget", "the budget"], 1.0, 100.0, 0
    )
    assert {item.language for item in outcome.languages} == {"fr", "en"}
    assert outcome.outcome_for("fr").wer == 0.0


def test_a_deleted_proper_noun_shows_up_in_the_decomposition():
    segments = [segment("a", 0.0, 1.0, reference="on appelle Bloomberg demain")]
    outcome = score_engine(EngineSpec(name="stub"), segments, ["on appelle demain"], 1.0, 100.0, 0)
    french = outcome.outcome_for("fr")
    assert french.decomposition.counts_for("proper_noun").deletions == 1


def test_empty_hypotheses_are_counted():
    segments = [segment("a", 0.0, 1.0), segment("a", 1.0, 2.0)]
    outcome = score_engine(EngineSpec(name="stub"), segments, ["bonjour", "  "], 1.0, 100.0, 0)
    assert outcome.empty_segments == 1


def test_the_payload_records_what_was_scored():
    segments = [segment("a", 0.0, 4.0)]
    outcome = score_engine(EngineSpec(name="stub"), segments, ["bonjour"], 2.0, 100.0, 0)
    payload = shootout_payload([outcome], segments, "summ-re")
    assert payload["segments"] == 1
    assert payload["meetings"] == ["a"]
    assert payload["audio_seconds"] == 4.0
    assert payload["engines"][0]["engine"]["name"] == "stub"


def test_the_real_time_factor_uses_the_audio_that_was_decoded():
    segments = [segment("a", 0.0, 10.0)]
    outcome = score_engine(EngineSpec(name="stub"), segments, ["bonjour"], 5.0, 100.0, 0)
    assert outcome.real_time_factor == 0.5


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
    return path


def test_a_saved_run_can_be_scored_again_without_the_recogniser(tmp_path):
    from hansard.evaluation.shootout import rescore

    path = write_jsonl(
        tmp_path / "engine.jsonl",
        [
            {
                "meeting": "a",
                "speaker": "017",
                "start": 0.0,
                "end": 2.0,
                "language": "fr",
                "reference": "le budget",
                "hypothesis": "le budget",
            }
        ],
    )
    _, hypotheses, outcome = rescore(path)
    assert hypotheses == ("le budget",)
    assert outcome.outcome_for("fr").wer == 0.0


def test_rescoring_can_substitute_a_corrected_reference(tmp_path):
    from hansard.evaluation.shootout import rescore

    path = write_jsonl(
        tmp_path / "engine.jsonl",
        [
            {
                "meeting": "a",
                "speaker": "017",
                "start": 0.0,
                "end": 2.0,
                "language": "fr",
                "reference": "le plus budget",
                "hypothesis": "le budget",
            }
        ],
    )
    assert rescore(path)[2].outcome_for("fr").deletions == 1
    corrected = {("a", 0.0, 2.0): "le budget"}
    assert rescore(path, references=corrected)[2].outcome_for("fr").deletions == 0


def test_the_reference_index_keys_on_meeting_and_span():
    from hansard.evaluation.shootout import reference_index

    index = reference_index([segment("a", 0.0, 2.0, reference="bonjour")])
    assert index == {("a", 0.0, 2.0): "bonjour"}
