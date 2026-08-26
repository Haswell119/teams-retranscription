from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.transcript import Transcript
from hansard.rendering.composition import (
    DEFAULT_SPEAKER_GAP,
    TITLE_SEPARATOR,
    compose_transcript_document,
    labelled,
)
from hansard.rendering.i18n import translations_for
from hansard.rendering.ports import RenderContext

PLAIN_TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"
PLAIN_TEXT_EXTENSION = ".txt"


@dataclass(frozen=True, slots=True)
class PlainTextRenderer:
    speaker_gap_seconds: float = DEFAULT_SPEAKER_GAP
    include_header: bool = False

    @property
    def name(self) -> str:
        return "text"

    @property
    def media_type(self) -> str:
        return PLAIN_TEXT_MEDIA_TYPE

    @property
    def file_extension(self) -> str:
        return PLAIN_TEXT_EXTENSION

    def render_transcript(self, transcript: Transcript, context: RenderContext) -> str:
        translations = translations_for(context.display_language)
        document = compose_transcript_document(transcript, context, translations, self.speaker_gap_seconds)
        lines: list[str] = []
        if self.include_header:
            lines.append(f"{document.title}{TITLE_SEPARATOR}{document.subtitle}")
            lines.extend(
                f"{labelled(entry.label, translations)} {entry.value}" for entry in document.metadata
            )
            lines.append("")
        lines.extend(f"[{block.timecode}] {block.speaker}: {block.text}" for block in document.blocks)
        body = "\n".join(lines).strip()
        return f"{body}\n" if body else ""
