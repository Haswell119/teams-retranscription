from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from hansard.domain.speakers import UNKNOWN_SPEAKER
from hansard.domain.transcript import Transcript
from hansard.rendering.composition import (
    CueLayout,
    SubtitleCue,
    collapse_whitespace,
    display_speaker,
    short_sovereignty_statement,
    subtitle_cues,
)
from hansard.rendering.i18n import Translations, translations_for
from hansard.rendering.ports import RenderContext
from hansard.rendering.timecode import TimestampStyle, format_timestamp

WEB_VTT_MEDIA_TYPE = "text/vtt"
WEB_VTT_EXTENSION = ".vtt"
SUB_RIP_MEDIA_TYPE = "application/x-subrip"
SUB_RIP_EXTENSION = ".srt"
CUE_ARROW = " --> "
FORBIDDEN_IN_HEADER = "-->"


def _is_named(speaker: str) -> bool:
    return bool(speaker.strip()) and speaker != UNKNOWN_SPEAKER


def _escaped(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cue_period(cue: SubtitleCue, style: TimestampStyle) -> str:
    start = format_timestamp(cue.span.start, style)
    end = format_timestamp(cue.span.end, style)
    return f"{start}{CUE_ARROW}{end}"


def _header_text(context: RenderContext) -> str:
    return collapse_whitespace(context.title).replace(FORBIDDEN_IN_HEADER, "->")


def _voice_payload(cue: SubtitleCue, translations: Translations) -> str:
    payload = _escaped(cue.text)
    if not _is_named(cue.speaker):
        return payload
    speaker = _escaped(collapse_whitespace(display_speaker(cue.speaker, translations)))
    return f"<v {speaker}>{payload}</v>"


def _sub_rip_payload(cue: SubtitleCue, previous_speaker: str | None, translations: Translations) -> str:
    if not _is_named(cue.speaker) or cue.speaker == previous_speaker:
        return cue.text
    speaker = collapse_whitespace(display_speaker(cue.speaker, translations))
    first, *rest = cue.lines
    return "\n".join((f"{speaker}: {first}", *rest))


def _document(blocks: Sequence[str]) -> str:
    return "\n\n".join(blocks) + "\n"


@dataclass(frozen=True, slots=True)
class WebVttRenderer:
    layout: CueLayout = field(default_factory=CueLayout)
    include_cue_identifiers: bool = True

    @property
    def name(self) -> str:
        return "vtt"

    @property
    def media_type(self) -> str:
        return WEB_VTT_MEDIA_TYPE

    @property
    def file_extension(self) -> str:
        return WEB_VTT_EXTENSION

    def render_transcript(self, transcript: Transcript, context: RenderContext) -> str:
        translations: Translations = translations_for(context.display_language)
        title = _header_text(context)
        blocks = [f"WEBVTT - {title}" if title else "WEBVTT"]
        blocks.append(f"NOTE\n{short_sovereignty_statement(context, translations)}")
        for cue in subtitle_cues(transcript, self.layout):
            heading = f"{cue.index}\n" if self.include_cue_identifiers else ""
            blocks.append(
                f"{heading}{_cue_period(cue, TimestampStyle.WEB_VTT)}\n{_voice_payload(cue, translations)}"
            )
        return _document(blocks)


@dataclass(frozen=True, slots=True)
class SubRipRenderer:
    layout: CueLayout = field(default_factory=CueLayout)

    @property
    def name(self) -> str:
        return "srt"

    @property
    def media_type(self) -> str:
        return SUB_RIP_MEDIA_TYPE

    @property
    def file_extension(self) -> str:
        return SUB_RIP_EXTENSION

    def render_transcript(self, transcript: Transcript, context: RenderContext) -> str:
        translations: Translations = translations_for(context.display_language)
        blocks: list[str] = []
        previous_speaker: str | None = None
        for cue in subtitle_cues(transcript, self.layout):
            payload = _sub_rip_payload(cue, previous_speaker, translations)
            previous_speaker = cue.speaker
            blocks.append(f"{cue.index}\n{_cue_period(cue, TimestampStyle.SUB_RIP)}\n{payload}")
        return _document(blocks) if blocks else ""
