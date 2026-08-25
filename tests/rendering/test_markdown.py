from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hansard.domain.minutes import Minutes
from hansard.domain.transcript import Transcript
from hansard.rendering.markdown import MarkdownRenderer
from hansard.rendering.ports import RenderContext

RENDERER = MarkdownRenderer()


@pytest.fixture
def empty_minutes():
    return Minutes(
        title="Quiet meeting",
        abstract="",
        language="en",
        generated_at=datetime(2026, 6, 3, 10, 2, tzinfo=UTC),
    )


def test_renderer_identity():
    assert RENDERER.name == "markdown"
    assert RENDERER.media_type == "text/markdown; charset=utf-8"
    assert RENDERER.file_extension == ".md"


def test_transcript_golden(transcript, context, assert_golden):
    assert_golden("transcript.en.md", RENDERER.render_transcript(transcript, context))


def test_minutes_golden(minutes, context, assert_golden):
    assert_golden("minutes.en.md", RENDERER.render_minutes(minutes, context))


def test_french_transcript_golden(fr_transcript, fr_context, assert_golden):
    assert_golden("transcript.fr.md", RENDERER.render_transcript(fr_transcript, fr_context))


def test_french_minutes_golden(fr_minutes, fr_context, assert_golden):
    assert_golden("minutes.fr.md", RENDERER.render_minutes(fr_minutes, fr_context))


def test_transcript_uses_speaker_prefixes(transcript, context):
    rendered = RENDERER.render_transcript(transcript, context)
    assert "**Amara Okafor** [00:00:08]" in rendered
    assert "**Unidentified speaker** [00:00:25]" in rendered


def test_minutes_action_table_is_a_markdown_table(minutes, context):
    rendered = RENDERER.render_minutes(minutes, context)
    assert "| Owner | Action | Due | Source |" in rendered
    assert "| --- | --- | --- | --- |" in rendered


def test_table_cells_escape_pipe_characters(minutes, context):
    rendered = RENDERER.render_minutes(minutes, context)
    assert "on-premises \\| cloud costs" in rendered


def test_sections_appear_in_the_expected_order(minutes, context):
    rendered = RENDERER.render_minutes(minutes, context)
    headings = [line for line in rendered.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Executive summary",
        "## Key decisions",
        "## Action items",
        "## Discussion by topic",
        "## Open questions",
        "## Speaking time",
    ]


def test_french_sections_are_translated(minutes, fr_context):
    rendered = RENDERER.render_minutes(minutes, fr_context)
    headings = [line for line in rendered.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Synthèse",
        "## Relevé de décisions",
        "## Actions à mener",
        "## Déroulé par sujet",
        "## Points ouverts",
        "## Temps de parole",
    ]
    assert "| Responsable | Action | Échéance | Source |" in rendered


def test_empty_minutes_use_placeholders(empty_minutes, context):
    rendered = RENDERER.render_minutes(empty_minutes, context)
    assert "_No decision was recorded._" in rendered
    assert "_No action item was recorded._" in rendered
    assert "_No topic was identified._" in rendered
    assert "_No open question was recorded._" in rendered
    assert "_Speaking time was not measured._" in rendered


def test_empty_minutes_placeholders_are_translated(empty_minutes, fr_context):
    rendered = RENDERER.render_minutes(empty_minutes, fr_context)
    assert "_Aucune décision n'a été consignée._" in rendered
    assert "_Le temps de parole n'a pas été mesuré._" in rendered


def test_empty_transcript_is_reported(context):
    rendered = RENDERER.render_transcript(Transcript(), context)
    assert "_No speech was transcribed._" in rendered


def test_footer_states_local_processing(minutes, context):
    rendered = RENDERER.render_minutes(minutes, context)
    assert "No audio, transcript or minutes left the organisation." in rendered
    assert "parakeet (nemo-parakeet-tdt-0.6b-v3)" in rendered


def test_document_ends_with_single_newline(minutes):
    rendered = RENDERER.render_minutes(minutes, RenderContext())
    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")
