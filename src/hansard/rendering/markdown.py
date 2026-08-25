from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from hansard.domain.minutes import Minutes
from hansard.domain.transcript import Transcript
from hansard.rendering.composition import (
    DEFAULT_SPEAKER_GAP,
    EMPTY_VALUE,
    TITLE_SEPARATOR,
    LabelledValue,
    MinutesDocument,
    TranscriptDocument,
    compose_minutes_document,
    compose_transcript_document,
    labelled,
)
from hansard.rendering.i18n import Phrase, Translations, translations_for
from hansard.rendering.ports import RenderContext

MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"
MARKDOWN_EXTENSION = ".md"


def _cell(value: str) -> str:
    collapsed = " ".join(value.split()).replace("|", "\\|")
    return collapsed or EMPTY_VALUE


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return lines


def _timecodes(codes: Sequence[str]) -> str:
    return f"[{', '.join(codes)}]" if codes else ""


def _metadata_lines(entries: Sequence[LabelledValue], translations: Translations) -> list[str]:
    return [f"- **{labelled(entry.label, translations)}** {entry.value}" for entry in entries]


def _section(heading: str) -> list[str]:
    return ["", f"## {heading}", ""]


def _paragraph(text: str, fallback: str) -> list[str]:
    return [text if text else f"_{fallback}_"]


def _decision_lines(document: MinutesDocument, translations: Translations) -> list[str]:
    if not document.decisions:
        return [f"_{translations.text(Phrase.NO_DECISIONS)}_"]
    lines: list[str] = []
    for position, decision in enumerate(document.decisions, start=1):
        marker = _timecodes(decision.timecodes)
        suffix = f" {marker}" if marker else ""
        lines.append(f"{position}. **{decision.statement}**{suffix}")
        if decision.rationale:
            lines.append(
                f"   - {labelled(translations.text(Phrase.RATIONALE), translations)} {decision.rationale}"
            )
    return lines


def _action_lines(document: MinutesDocument, translations: Translations) -> list[str]:
    if not document.actions:
        return [f"_{translations.text(Phrase.NO_ACTIONS)}_"]
    headers = (
        translations.text(Phrase.OWNER),
        translations.text(Phrase.ACTION),
        translations.text(Phrase.DUE),
        translations.text(Phrase.SOURCE),
    )
    rows = [
        (action.owner, action.description, action.due, ", ".join(action.timecodes) or EMPTY_VALUE)
        for action in document.actions
    ]
    return _table(headers, rows)


def _topic_lines(document: MinutesDocument, translations: Translations) -> list[str]:
    if not document.topics:
        return [f"_{translations.text(Phrase.NO_TOPICS)}_"]
    lines: list[str] = []
    for topic in document.topics:
        lines.extend(["", f"### {topic.position}. {topic.title} ({topic.period})", "", topic.summary])
        if topic.key_points:
            lines.append("")
            lines.extend(f"- {point}" for point in topic.key_points)
    return lines[1:]


def _question_lines(document: MinutesDocument, translations: Translations) -> list[str]:
    if not document.questions:
        return [f"_{translations.text(Phrase.NO_QUESTIONS)}_"]
    lines: list[str] = []
    for question in document.questions:
        attribution = f" — _{question.attribution}_" if question.attribution else ""
        marker = _timecodes(question.timecodes)
        suffix = f" {marker}" if marker else ""
        lines.append(f"- {question.question}{attribution}{suffix}")
    return lines


def _speaking_lines(document: MinutesDocument, translations: Translations) -> list[str]:
    if not document.speaking:
        return [f"_{translations.text(Phrase.NO_SPEAKING_TIME)}_"]
    headers = (
        translations.text(Phrase.SPEAKER),
        translations.text(Phrase.DURATION),
        translations.text(Phrase.SHARE),
    )
    rows = [(entry.speaker, entry.duration_label, entry.share_label) for entry in document.speaking]
    return _table(headers, rows)


def _transcript_body(document: TranscriptDocument, translations: Translations) -> list[str]:
    if not document.blocks:
        return [f"_{translations.text(Phrase.NO_SPEECH)}_"]
    lines: list[str] = []
    for block in document.blocks:
        lines.extend([f"**{block.speaker}** [{block.timecode}]", "", block.text, ""])
    return lines[:-1]


def _document(lines: Sequence[str]) -> str:
    return "\n".join(lines).strip() + "\n"


@dataclass(frozen=True, slots=True)
class MarkdownRenderer:
    speaker_gap_seconds: float = DEFAULT_SPEAKER_GAP

    @property
    def name(self) -> str:
        return "markdown"

    @property
    def media_type(self) -> str:
        return MARKDOWN_MEDIA_TYPE

    @property
    def file_extension(self) -> str:
        return MARKDOWN_EXTENSION

    def render_transcript(self, transcript: Transcript, context: RenderContext) -> str:
        translations = translations_for(context.language)
        document = compose_transcript_document(transcript, context, translations, self.speaker_gap_seconds)
        lines = [f"# {document.title}{TITLE_SEPARATOR}{document.subtitle}", ""]
        lines.extend(_metadata_lines(document.metadata, translations))
        lines.extend(["", "---", ""])
        lines.extend(_transcript_body(document, translations))
        lines.extend(["", "---", "", f"_{document.footer}_"])
        return _document(lines)

    def render_minutes(self, minutes: Minutes, context: RenderContext) -> str:
        translations = translations_for(context.language)
        document = compose_minutes_document(minutes, context, translations)
        lines = [f"# {document.title}", "", f"_{document.subtitle}_", ""]
        lines.extend(_metadata_lines(document.metadata, translations))
        lines.extend(_section(translations.text(Phrase.EXECUTIVE_SUMMARY)))
        lines.extend(_paragraph(document.summary, translations.text(Phrase.NO_SPEECH)))
        lines.extend(_section(translations.text(Phrase.KEY_DECISIONS)))
        lines.extend(_decision_lines(document, translations))
        lines.extend(_section(translations.text(Phrase.ACTION_ITEMS)))
        lines.extend(_action_lines(document, translations))
        lines.extend(_section(translations.text(Phrase.DISCUSSION_BY_TOPIC)))
        lines.extend(_topic_lines(document, translations))
        lines.extend(_section(translations.text(Phrase.OPEN_QUESTIONS)))
        lines.extend(_question_lines(document, translations))
        lines.extend(_section(translations.text(Phrase.SPEAKING_TIME)))
        lines.extend(_speaking_lines(document, translations))
        lines.extend(["", "---", "", f"_{document.footer}_", "", f"_{document.generated_at}_"])
        return _document(lines)
