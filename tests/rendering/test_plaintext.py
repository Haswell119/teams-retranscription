from __future__ import annotations

from hansard.domain.transcript import Transcript
from hansard.rendering.plaintext import PlainTextRenderer

RENDERER = PlainTextRenderer()


def test_renderer_identity():
    assert RENDERER.name == "text"
    assert RENDERER.media_type == "text/plain; charset=utf-8"
    assert RENDERER.file_extension == ".txt"


def test_transcript_golden(transcript, context, assert_golden):
    assert_golden("transcript.en.txt", RENDERER.render_transcript(transcript, context))


def test_every_line_follows_the_timecode_speaker_pattern(transcript, context):
    rendered = RENDERER.render_transcript(transcript, context)
    for line in rendered.splitlines():
        assert line[0] == "["
        assert line[9] == "]"
        assert ": " in line


def test_header_is_optional(transcript, context):
    rendered = PlainTextRenderer(include_header=True).render_transcript(transcript, context)
    assert rendered.startswith("Weekly platform sync — Transcript")
    assert "Participants: Amara Okafor, Léa Fontaine, Jonas Weber" in rendered


def test_empty_transcript_renders_nothing(context):
    assert PlainTextRenderer().render_transcript(Transcript(), context) == ""
