from __future__ import annotations

import re
from dataclasses import replace

import pytest

from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.rendering.html import HtmlRenderer

RENDERER = HtmlRenderer()
EXTERNAL_REFERENCE = re.compile(r"(https?:)?//|<script|<link|@import|src=|url\(")


@pytest.fixture
def minutes_html(minutes, context):
    return RENDERER.render_minutes(minutes, context)


@pytest.fixture
def transcript_html(transcript, context):
    return RENDERER.render_transcript(transcript, context)


def test_renderer_identity():
    assert RENDERER.name == "html"
    assert RENDERER.media_type == "text/html; charset=utf-8"
    assert RENDERER.file_extension == ".html"


def test_documents_are_complete_html(minutes_html, transcript_html):
    for document in (minutes_html, transcript_html):
        assert document.startswith("<!DOCTYPE html>")
        assert document.rstrip().endswith("</html>")
        assert '<meta charset="utf-8">' in document
        assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in document


def test_documents_are_self_contained(minutes_html, transcript_html):
    for document in (minutes_html, transcript_html):
        assert not EXTERNAL_REFERENCE.search(document)


def test_documents_support_light_and_dark(minutes_html):
    assert "@media (prefers-color-scheme: dark)" in minutes_html
    assert '<meta name="color-scheme" content="light dark">' in minutes_html


def test_documents_have_print_styles(minutes_html):
    assert "@media print" in minutes_html


def test_documents_are_responsive(minutes_html):
    assert "@media (max-width: 30rem)" in minutes_html
    assert "grid-template-columns: repeat(auto-fit" in minutes_html


def test_semantic_structure(minutes_html):
    for fragment in (
        '<header class="masthead">',
        '<nav class="toc"',
        '<main id="content">',
        '<section aria-labelledby="decisions">',
        '<footer class="colophon">',
        '<th scope="col">Owner</th>',
        '<th scope="row">Léa Fontaine</th>',
        '<time datetime="2026-06-03T09:30:00+00:00">',
    ):
        assert fragment in minutes_html


def test_skip_link_targets_the_main_landmark(minutes_html):
    assert '<a class="skip-link" href="#content">Skip to content</a>' in minutes_html


def test_table_of_contents_matches_section_anchors(minutes_html):
    anchors = re.findall(r'<li><a href="#([a-z]+)">', minutes_html)
    assert anchors == ["summary", "decisions", "actions", "topics", "questions", "speaking"]
    for anchor in anchors:
        assert f'<h2 id="{anchor}">' in minutes_html


def test_speaking_time_bars_are_decorative(minutes_html):
    assert '<span class="bar-track" aria-hidden="true">' in minutes_html
    assert re.search(r'<span class="bar" style="width: \d+(\.\d+)?%">', minutes_html)


def test_language_attribute_follows_the_context(minutes, fr_context):
    assert '<html lang="fr">' in RENDERER.render_minutes(minutes, fr_context)


def test_french_headings(minutes, fr_context):
    document = RENDERER.render_minutes(minutes, fr_context)
    assert '<h2 id="decisions">Relevé de décisions</h2>' in document
    assert '<h2 id="speaking">Temps de parole</h2>' in document
    assert "Aller au contenu" in document


def test_content_is_escaped(context, minutes):
    hostile = replace(minutes, title="<script>alert('x')</script>")
    document = RENDERER.render_minutes(hostile, context)
    assert "<script>" not in document
    assert "&lt;script&gt;" in document


def test_transcript_turns_are_articles(transcript_html):
    assert transcript_html.count('<article class="turn">') == 10
    assert '<span class="speaker">Amara Okafor</span><span class="timecode">00:00:08</span>' in (
        transcript_html
    )
    assert "Unidentified speaker" in transcript_html


def test_empty_states_are_rendered(context):
    document = RENDERER.render_transcript(Transcript(), context)
    assert '<p class="empty">No speech was transcribed.</p>' in document


def test_long_text_is_not_truncated(context):
    text = "word " * 200
    transcript = Transcript(utterances=(Utterance(span=TimeSpan(0.0, 60.0), text=text),))
    document = RENDERER.render_transcript(transcript, context)
    assert text.strip() in document
