from __future__ import annotations

from hansard.adapters.delivery.markup import (
    html_to_text,
    markdown_to_html,
    to_html,
    to_plain_text,
)


def test_headings_lists_and_emphasis() -> None:
    markup = markdown_to_html("## Agenda\n\n1. Budget\n2. Roadmap\n\n- note\n\n**bold** and *thin*")

    assert "<h2>Agenda</h2>" in markup
    assert markup.count("<ol>") == 1
    assert markup.count("<ul>") == 1
    assert "<li>Budget</li>" in markup
    assert "<strong>bold</strong>" in markup
    assert "<em>thin</em>" in markup


def test_links_quotes_and_code() -> None:
    markup = markdown_to_html("> quoted\n\nSee [docs](https://example.org/a?b=1) and `code`.\n")

    assert "<blockquote>quoted</blockquote>" in markup
    assert '<a href="https://example.org/a?b=1">docs</a>' in markup
    assert "<code>code</code>" in markup


def test_fenced_code_blocks_are_escaped() -> None:
    markup = markdown_to_html("```\n<script>alert(1)</script>\n```")

    assert "<pre><code>&lt;script&gt;alert(1)&lt;/script&gt;</code></pre>" in markup


def test_html_injection_in_markdown_is_escaped() -> None:
    markup = markdown_to_html("Hello <img src=x onerror=alert(1)>")

    assert "<img" not in markup
    assert "&lt;img" in markup


def test_html_bodies_are_passed_through() -> None:
    assert to_html("<p>kept</p>", "html") == "<p>kept</p>"


def test_plain_text_extraction_from_html() -> None:
    text = html_to_text("<h1>Title</h1><p>line one<br />line two</p><ul><li>a</li><li>b</li></ul>")

    assert text.splitlines() == ["Title", "line one", "line two", "a", "b"]


def test_plain_text_keeps_markdown_readable() -> None:
    body = "# Title\n\n- one"

    assert to_plain_text(body, "markdown") == body
