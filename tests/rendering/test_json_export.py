from __future__ import annotations

import json

import pytest

from hansard.domain.transcript import Transcript
from hansard.rendering.json_export import SCHEMA_VERSION, JsonRenderer

RENDERER = JsonRenderer()


def test_renderer_identity():
    assert RENDERER.name == "json"
    assert RENDERER.media_type == "application/json"
    assert RENDERER.file_extension == ".json"


def test_transcript_golden(transcript, context, assert_golden):
    assert_golden("transcript.en.json", RENDERER.render_transcript(transcript, context))


def test_minutes_golden(minutes, context, assert_golden):
    assert_golden("minutes.en.json", RENDERER.render_minutes(minutes, context))


def test_transcript_envelope(transcript, context):
    payload = json.loads(RENDERER.render_transcript(transcript, context))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["kind"] == "transcript"
    assert payload["generator"]["name"] == "Hansard"
    assert payload["meeting"]["title"] == "Weekly platform sync"
    assert payload["meeting"]["timezone"] == "UTC"
    assert payload["meeting"]["participants"][0]["is_organizer"] is True
    assert payload["meeting"]["provenance"][0]["component"] == "asr"


def test_transcript_payload_shape(transcript, context):
    payload = json.loads(RENDERER.render_transcript(transcript, context))["transcript"]
    assert payload["language"] == "en"
    assert payload["audio_duration_seconds"] == 1500.0
    assert payload["word_count"] > 0
    first = payload["utterances"][0]
    assert first["index"] == 0
    assert first["timecode"] == "00:00:08.000"
    assert first["speaker"] == "Amara Okafor"
    assert first["words"][0]["text"] == "Good"
    assert "words" not in payload["utterances"][1]


def test_word_timings_can_be_omitted(transcript, context):
    payload = json.loads(JsonRenderer(include_word_timings=False).render_transcript(transcript, context))
    assert all("words" not in utterance for utterance in payload["transcript"]["utterances"])


def test_minutes_payload_shape(minutes, context):
    payload = json.loads(RENDERER.render_minutes(minutes, context))
    assert payload["kind"] == "minutes"
    body = payload["minutes"]
    assert body["title"] == "Weekly platform sync"
    assert body["generated_at"] == "2026-06-03T10:02:00+00:00"
    assert body["topics"][0]["timecode"] == "00:00:00.000"
    assert body["decisions"][0]["citations"][0]["timecode"] == "00:06:10.500"
    assert body["decisions"][2]["rationale"] is None
    assert body["actions"][2]["owner"] is None
    assert body["open_questions"][1]["raised_by"] is None
    assert sum(entry["share"] for entry in body["speaking_time"]) == pytest.approx(1.0, abs=1e-3)
    assert body["speaking_time"][0]["speaker"] == "Amara Okafor"


def test_output_is_valid_json_for_empty_input(context):
    payload = json.loads(RENDERER.render_transcript(Transcript(), context))
    assert payload["transcript"]["utterances"] == []


def test_unicode_is_preserved(transcript, context):
    assert "Léa Fontaine" in RENDERER.render_transcript(transcript, context)


def test_compact_output_is_supported(transcript, context):
    compact = JsonRenderer(indent=0).render_transcript(transcript, context)
    assert json.loads(compact)["kind"] == "transcript"
