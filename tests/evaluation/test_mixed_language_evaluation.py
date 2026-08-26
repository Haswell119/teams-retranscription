from __future__ import annotations

import json

import pytest

from hansard.domain.language import MIXED
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.evaluation.check import Observation, gates_for
from hansard.evaluation.comparison import (
    compare,
    comparison_markdown,
    comparison_payload,
    load_transcript,
)
from hansard.evaluation.metrics.language import language_identification
from hansard.evaluation.normalizers import MixedNormalizer, normalizer_for

REFERENCE_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Alice", "fr", "Bonjour à tous, on commence par le point sur le déploiement."),
    ("Bob", "en", "Sure, the staging cluster is green since Monday morning."),
    ("Alice", "fr", "Il faut valider le périmètre avant vendredi prochain."),
    ("Chloe", "en", "I'll take the release notes and circulate them before Friday."),
)


def _reference() -> Transcript:
    utterances = tuple(
        Utterance(
            span=TimeSpan(index * 10.0, index * 10.0 + 8.0),
            text=text,
            speaker=speaker,
            language=language,
        )
        for index, (speaker, language, text) in enumerate(REFERENCE_ROWS)
    )
    return Transcript(utterances=utterances, language=MIXED, audio_duration=40.0)


def _perfect() -> Transcript:
    return _reference()


def _english_locked() -> Transcript:
    replacements = {
        0: "Bonjour at all, on commence par the point sur the deployment.",
        2: "Ill valid the perimeter before Friday next.",
    }
    utterances = tuple(
        Utterance(
            span=utterance.span,
            text=replacements.get(index, utterance.text),
            speaker=utterance.speaker,
        )
        for index, utterance in enumerate(_reference().utterances)
    )
    return Transcript(utterances=utterances, audio_duration=40.0)


def test_the_mixed_normalizer_applies_each_language_to_its_own_run():
    normalised = MixedNormalizer().normalize(
        "On valide le budget de vingt-cinq mille euros. I'll send the deck tomorrow."
    )
    assert "vingt cinq mille euros" in normalised
    assert "i will send the deck tomorrow" in normalised


def test_normalizer_for_resolves_the_mixed_tag():
    assert isinstance(normalizer_for(MIXED), MixedNormalizer)
    assert isinstance(normalizer_for("multilingual"), MixedNormalizer)


def test_language_accuracy_is_perfect_when_every_utterance_is_tagged_correctly():
    result = language_identification(_reference(), _reference())
    assert result.accuracy == pytest.approx(1.0)
    assert result.confusions == ()


def test_language_accuracy_falls_when_french_is_transcribed_as_english():
    reference = _reference()
    observed = reference.with_languages(["en", "en", "en", "en"])
    result = language_identification(observed, reference)
    assert result.accuracy < 0.6
    assert result.confusions[0][0] == "fr"
    assert result.confusions[0][1] == "en"


def test_a_mixed_observation_is_graded_against_the_mixed_gates():
    languages = {gate.language for gate in gates_for(Observation("f", "m", MIXED, "meeting", {}))}
    assert languages == {MIXED, "all"}
    metrics = {gate.metric for gate in gates_for(Observation("f", "m", MIXED, "meeting", {}))}
    assert "language_accuracy" in metrics


def test_comparison_localises_the_damage_to_the_language_that_was_lost():
    reference = _reference()
    result = compare("demo", reference, [("hansard", _perfect()), ("teams", _english_locked())])
    assert result.reference_languages == ("en", "fr") or result.reference_languages == ("fr", "en")
    hansard = result.score_for("hansard")
    teams = result.score_for("teams")
    assert hansard is not None and teams is not None
    assert hansard.wer == pytest.approx(0.0, abs=1e-9)
    assert teams.wer > hansard.wer
    assert teams.slice_for("fr").wer > teams.slice_for("en").wer
    assert teams.slice_for("en").wer == pytest.approx(0.0, abs=1e-9)


def test_the_comparison_report_renders_a_per_language_breakdown():
    result = compare("demo", _reference(), [("hansard", _perfect()), ("teams", _english_locked())])
    markdown = comparison_markdown(result)
    assert "Word error rate by language spoken" in markdown
    assert "hansard" in markdown and "teams" in markdown
    payload = comparison_payload(result)
    assert payload["benchmark"] == "comparison"
    assert {entry["system"] for entry in payload["systems"]} == {"hansard", "teams"}


def test_a_teams_webvtt_export_is_ingestible(tmp_path):
    path = tmp_path / "copilot.vtt"
    path.write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:08.000\n<v Alice>Bonjour à tous.\n\n"
        "2\n00:00:10.000 --> 00:00:18.000\n<v Bob>Sure, the cluster is green.\n",
        encoding="utf-8",
    )
    transcript = load_transcript(path)
    assert [utterance.speaker for utterance in transcript.utterances] == ["Alice", "Bob"]


def test_a_hansard_json_export_is_ingestible(tmp_path):
    path = tmp_path / "hansard.json"
    path.write_text(
        json.dumps(
            {
                "transcript": {
                    "language": MIXED,
                    "audio_duration_seconds": 20.0,
                    "utterances": [
                        {"speaker": "Alice", "language": "fr", "text": "Bonjour.", "start": 0, "end": 8},
                        {"speaker": "Bob", "language": "en", "text": "Hello.", "start": 10, "end": 18},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    transcript = load_transcript(path)
    assert [utterance.language for utterance in transcript.utterances] == ["fr", "en"]


def test_an_unknown_transcript_format_is_refused(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported transcript format"):
        load_transcript(path)
