import json
from pathlib import Path

import pytest

from hansard.domain.speakers import UNKNOWN_SPEAKER, Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.evaluation.corpora import SUMM_RE_DATASET, SUMM_RE_LANGUAGE, meeting_diarization
from hansard.evaluation.datasets import (
    load_manifest,
    prepare_summ_re,
    sample_from_subtitles,
    summ_re_samples,
)
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


FLEURS_MANIFEST = Path("/home/user/eval_data/fleurs_fr.jsonl")


@pytest.mark.skipif(not FLEURS_MANIFEST.exists(), reason="local evaluation corpus is absent")
def test_load_manifest_reads_the_french_fixture():
    samples = load_manifest(FLEURS_MANIFEST)
    assert len(samples) == 80
    assert {sample.language for sample in samples} == {"fr"}
    assert samples[0].reference.text.startswith("l'accident")
    assert all(sample.audio_seconds > 0.0 for sample in samples)


def summ_re_tree(root):
    meeting = root / "meeting-01"
    meeting.mkdir(parents=True)
    (meeting / "alice.json").write_text(
        json.dumps(
            [
                {"start": 0.0, "end": 2.0, "text": "bonjour à toutes et à tous"},
                {"start": 6.0, "end": 8.5, "text": "on commence par le budget"},
            ]
        ),
        encoding="utf-8",
    )
    (meeting / "bob.json").write_text(
        json.dumps([{"start": 2.5, "end": 5.5, "text": "merci alice"}]),
        encoding="utf-8",
    )
    (meeting / "mixed.wav").write_bytes(b"")
    return root


def test_summ_re_preparation_builds_reference_diarization(tmp_path):
    root = summ_re_tree(tmp_path / "summ-re")
    meetings = prepare_summ_re(root, tmp_path / "rttm")
    assert [meeting.identifier for meeting in meetings] == ["meeting-01"]
    assert meetings[0].speakers == ("alice", "bob")
    assert meetings[0].duration == pytest.approx(8.5)
    diarization = meeting_diarization(meetings[0])
    assert diarization.speaker_count == 2
    assert diarization.turns[0].label == "alice"
    assert diarization.turns[1].label == "bob"
    written = load_rttm(tmp_path / "rttm" / "meeting-01.rttm")
    assert written["meeting-01"].turns == diarization.turns


def test_summ_re_samples_are_french_and_carry_the_mixed_audio(tmp_path):
    root = summ_re_tree(tmp_path / "summ-re")
    samples = summ_re_samples(root)
    assert len(samples) == 1
    assert samples[0].language == "fr"
    assert samples[0].source == "summ-re"
    assert samples[0].audio_path == root / "meeting-01" / "mixed.wav"
    assert samples[0].reference.speakers == ("alice", "bob")
    assert len(samples[0].reference.utterances) == 3
    assert samples[0].reference_diarization is not None


def test_summ_re_download_is_documented_not_automatic():
    assert SUMM_RE_DATASET == "linagora/SUMM-RE"
    assert SUMM_RE_LANGUAGE == "fr"
