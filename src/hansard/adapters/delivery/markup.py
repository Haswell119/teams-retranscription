from __future__ import annotations

import html
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_FENCE = re.compile(r"^\s*```")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_TAG = re.compile(r"<[^>]+>")
_BLOCK_BOUNDARY = re.compile(
    r"</(?:p|div|li|ul|ol|h[1-6]|tr|table|blockquote|pre)>|<br\s*/?>",
    re.IGNORECASE,
)
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")

HTML_FORMATS = frozenset({"html", "text/html"})


def render_inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = _INLINE_CODE.sub(r"<code>\1</code>", escaped)
    escaped = _LINK.sub(r'<a href="\2">\1</a>', escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return _ITALIC.sub(r"<em>\1</em>", escaped)


def _close_open_list(blocks: list[str], open_list: str | None) -> None:
    if open_list is not None:
        blocks.append(f"</{open_list}>")


def markdown_to_html(text: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    open_list: str | None = None
    in_code_block = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{'<br />'.join(paragraph)}</p>")
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if _FENCE.match(line):
            if in_code_block:
                escaped = html.escape("\n".join(code_lines), quote=False)
                blocks.append(f"<pre><code>{escaped}</code></pre>")
                code_lines.clear()
                in_code_block = False
            else:
                flush_paragraph()
                _close_open_list(blocks, open_list)
                open_list = None
                in_code_block = True
            continue
        if in_code_block:
            code_lines.append(raw_line)
            continue
        if not line.strip():
            flush_paragraph()
            _close_open_list(blocks, open_list)
            open_list = None
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            _close_open_list(blocks, open_list)
            open_list = None
            level = min(len(heading.group(1)), 6)
            blocks.append(f"<h{level}>{render_inline(heading.group(2).strip())}</h{level}>")
            continue
        bullet = _BULLET.match(line)
        ordered = _ORDERED.match(line) if bullet is None else None
        matched = bullet if bullet is not None else ordered
        if matched is not None:
            wanted = "ul" if bullet is not None else "ol"
            item = matched.group(1)
            flush_paragraph()
            if open_list != wanted:
                _close_open_list(blocks, open_list)
                blocks.append(f"<{wanted}>")
                open_list = wanted
            blocks.append(f"<li>{render_inline(item.strip())}</li>")
            continue
        quote = _QUOTE.match(line)
        if quote:
            flush_paragraph()
            _close_open_list(blocks, open_list)
            open_list = None
            blocks.append(f"<blockquote>{render_inline(quote.group(1).strip())}</blockquote>")
            continue
        _close_open_list(blocks, open_list)
        open_list = None
        paragraph.append(render_inline(line.strip()))

    if in_code_block and code_lines:
        blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines), quote=False)}</code></pre>")
    flush_paragraph()
    _close_open_list(blocks, open_list)
    return "\n".join(blocks)


def html_to_text(markup: str) -> str:
    spaced = _BLOCK_BOUNDARY.sub("\n", markup)
    stripped = _TAG.sub("", spaced)
    return _EXCESS_BLANK_LINES.sub("\n\n", html.unescape(stripped)).strip()


def to_html(body: str, body_format: str) -> str:
    if body_format.lower() in HTML_FORMATS:
        return body
    return markdown_to_html(body)


def to_plain_text(body: str, body_format: str) -> str:
    if body_format.lower() in HTML_FORMATS:
        return html_to_text(body)
    return body
