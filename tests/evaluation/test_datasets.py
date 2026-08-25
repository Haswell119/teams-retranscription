import json
from pathlib import Path

import pytest

from hansard.domain.speakers import UNKNOWN_SPEAKER, Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.evaluation.datasets import load_manifest, sample_from_subtitles
from hansard.evaluation.formats.rttm import load_rttm, parse_rttm, render_rttm, write_rttm
from hansard.evaluation.formats.subtitles import load_subtitles, parse_srt, parse_webvtt

LIBRISPEECH_MANIFEST = Path("/home/user/eval_data/librispeech_dummy.jsonl")

TEAMS_VTT = """WEBVTT

NOTE recorded by Microsoft Teams

1
00:00:01.000 --> 00:00:04.000
<v Marie Dupont>Bonjour à tous, on commence.</v>

2
00:00:04.500 --> 00:00:07.250
<v Paul Martin>Merci Marie, j'ai deux points.</v>
"""

SRT = """1
00:00:01,000 --> 00:00:04,000
Marie Dupont: Bonjour à tous.

2
00:00:04,500 --> 00:00:07,250
Nothing to report here.
"""


def test_load_manifest_reads_simple_records(tmp_path):
    path = tmp_path / "manifest.jsonl"
    path.write_text(
        json.dumps({"audio": "/data/a.wav", "text": "HELLO WORLD", "seconds": 2.5, "language": "en"}) + "\n",
        encoding="utf-8",
    )
    samples = load_manifest(path)
    assert len(samples) == 1
    assert samples[0].identifier == "a"
    assert samples[0].reference.text == "HELLO WORLD"
    assert samples[0].audio_seconds == pytest.approx(2.5)
    assert samples[0].audio_path == Path("/data/a.wav")
    assert samples[0].reference_diarization is None


def test_load_manifest_reads_speaker_segments(tmp_path):
    path = tmp_path / "meeting.jsonl"
    record = {
        "id": "meeting-1",
        "audio": "/data/meeting.wav",
        "language": "fr",
        "utterances": [
            {"start": 0.0, "end": 2.0, "speaker": "Marie", "text": "bonjour"},
            {"start": 2.0, "end": 5.0, "speaker": "Paul", "text": "salut"},
        ],
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    sample = load_manifest(path)[0]
    assert sample.identifier == "meeting-1"
    assert sample.reference.speakers == ("Marie", "Paul")
    assert sample.audio_seconds == pytest.approx(5.0)
    assert sample.reference_diarization is not None
    assert sample.reference_diarization.speaker_count == 2


@pytest.mark.skipif(not LIBRISPEECH_MANIFEST.exists(), reason="local evaluation corpus is absent")
def test_load_manifest_reads_the_librispeech_fixture():
    samples = load_manifest(LIBRISPEECH_MANIFEST)
    assert len(samples) == 73
    assert samples[0].language == "en"
    assert samples[0].reference.text.startswith("MISTER QUILTER")
    assert all(sample.audio_path is not None for sample in samples)
    assert all(sample.audio_seconds > 0.0 for sample in samples)


def test_rttm_round_trip(tmp_path):
    diarizations = {
        "meeting": Diarization(
            turns=(
                SpeakerTurn(TimeSpan(0.0, 2.5), "Marie"),
                SpeakerTurn(TimeSpan(2.5, 6.0), "Paul"),
            ),
            labels=("Marie", "Paul"),
        )
    }
    path = tmp_path / "reference.rttm"
    write_rttm(path, diarizations)
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "SPEAKER meeting 1 0.000 2.500 <NA> <NA> Marie <NA> <NA>"
    restored = load_rttm(path)
    assert restored["meeting"].turns == diarizations["meeting"].turns
    assert render_rttm(restored) == text


def test_rttm_parser_ignores_foreign_records():
    text = (
        "SPKR-INFO meeting 1 <NA> <NA> <NA> unknown Marie <NA>\n"
        "SPEAKER meeting 1 1.000 2.000 <NA> <NA> Paul <NA> <NA>\n"
    )
    parsed = parse_rttm(text)
    assert parsed["meeting"].speaker_count == 1
    assert parsed["meeting"].turns[0].span == TimeSpan(1.0, 3.0)


def test_teams_webvtt_speaker_names(tmp_path):
    transcript = parse_webvtt(TEAMS_VTT, language="fr")
    assert transcript.speakers == ("Marie Dupont", "Paul Martin")
    assert transcript.utterances[0].text == "Bonjour à tous, on commence."
    assert transcript.utterances[0].span == TimeSpan(1.0, 4.0)
    assert transcript.audio_duration == pytest.approx(7.25)
    path = tmp_path / "teams.vtt"
    path.write_text(TEAMS_VTT, encoding="utf-8")
    assert load_subtitles(path, "fr").utterances == transcript.utterances


def test_srt_name_prefix_and_plain_cues():
    transcript = parse_srt(SRT)
    assert transcript.utterances[0].speaker == "Marie Dupont"
    assert transcript.utterances[0].text == "Bonjour à tous."
    assert transcript.utterances[1].speaker == UNKNOWN_SPEAKER
    assert transcript.utterances[1].span == TimeSpan(4.5, 7.25)


def test_sample_from_subtitles_builds_reference_diarization(tmp_path):
    path = tmp_path / "teams.vtt"
    path.write_text(TEAMS_VTT, encoding="utf-8")
    sample = sample_from_subtitles(path, language="fr", source="teams")
    assert sample.identifier == "teams"
    assert sample.source == "teams"
    assert sample.reference_diarization is not None
    assert sample.reference_diarization.labels == ("Marie Dupont", "Paul Martin")
