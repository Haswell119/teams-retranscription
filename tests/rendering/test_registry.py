from __future__ import annotations

import pytest

from hansard.domain.errors import ConfigurationError
from hansard.rendering.ports import MinutesRenderer, TranscriptRenderer
from hansard.rendering.registry import (
    NamedRegistry,
    available_formats,
    minutes_formats,
    minutes_renderer_for,
    register_renderer,
    renderer_for,
    transcript_formats,
    transcript_renderer_for,
)


def test_default_formats_are_registered():
    assert available_formats() == ("html", "json", "markdown", "srt", "text", "vtt")


def test_transcript_and_minutes_capabilities_are_separate():
    assert transcript_formats() == ("html", "json", "markdown", "srt", "text", "vtt")
    assert minutes_formats() == ("html", "json", "markdown")


@pytest.mark.parametrize("name", available_formats())
def test_every_renderer_exposes_its_identity(name):
    renderer = renderer_for(name)
    assert renderer.name == name
    assert renderer.media_type
    assert renderer.file_extension.startswith(".")


@pytest.mark.parametrize("name", transcript_formats())
def test_transcript_renderers_satisfy_the_protocol(name):
    assert isinstance(transcript_renderer_for(name), TranscriptRenderer)


@pytest.mark.parametrize("name", minutes_formats())
def test_minutes_renderers_satisfy_the_protocol(name):
    assert isinstance(minutes_renderer_for(name), MinutesRenderer)


def test_unknown_format_is_a_configuration_error():
    with pytest.raises(ConfigurationError) as failure:
        renderer_for("pdf")
    assert "unknown output format 'pdf'" in str(failure.value)
    assert "markdown" in str(failure.value)


def test_subtitle_formats_reject_minutes():
    with pytest.raises(ConfigurationError) as failure:
        minutes_renderer_for("vtt")
    assert "does not render minutes" in str(failure.value)


def test_registration_replaces_a_renderer_under_the_same_name(transcript, context):
    class UpperCaseRenderer:
        name = "text"
        media_type = "text/plain"
        file_extension = ".txt"

        def render_transcript(self, transcript, context):
            return transcript.text.upper()

    original = renderer_for("text")
    register_renderer(UpperCaseRenderer())
    try:
        rendered = transcript_renderer_for("text").render_transcript(transcript, context)
        assert rendered.startswith("GOOD MORNING")
        assert available_formats() == ("html", "json", "markdown", "srt", "text", "vtt")
    finally:
        register_renderer(original)
    assert renderer_for("text") is original


def test_named_registry_is_generic():
    registry: NamedRegistry[int] = NamedRegistry("widget")
    registry.register("one", 1)
    assert registry.names() == ("one",)
    assert registry.get("one") == 1
    assert "one" in registry
    assert "two" not in registry
    with pytest.raises(ConfigurationError, match="unknown widget 'two'"):
        registry.get("two")
