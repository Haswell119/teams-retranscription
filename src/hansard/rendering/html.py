from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

from hansard.domain.minutes import Minutes
from hansard.domain.transcript import Transcript
from hansard.rendering.composition import (
    DEFAULT_SPEAKER_GAP,
    TITLE_SEPARATOR,
    MinutesDocument,
    TranscriptDocument,
    compose_minutes_document,
    compose_transcript_document,
)
from hansard.rendering.i18n import Phrase, Translations, translations_for
from hansard.rendering.ports import RenderContext

HTML_MEDIA_TYPE = "text/html; charset=utf-8"
HTML_EXTENSION = ".html"
TEMPLATE_PACKAGE = "hansard.rendering"
TEMPLATE_DIRECTORY = "templates"
TRANSCRIPT_TEMPLATE = "transcript.html.j2"
MINUTES_TEMPLATE = "minutes.html.j2"
SECTION_ORDER = ("summary", "decisions", "actions", "topics", "questions", "speaking")

SECTION_PHRASES: dict[str, Phrase] = {
    "summary": Phrase.EXECUTIVE_SUMMARY,
    "decisions": Phrase.KEY_DECISIONS,
    "actions": Phrase.ACTION_ITEMS,
    "topics": Phrase.DISCUSSION_BY_TOPIC,
    "questions": Phrase.OPEN_QUESTIONS,
    "speaking": Phrase.SPEAKING_TIME,
}

LABEL_PHRASES: dict[str, Phrase] = {
    "owner": Phrase.OWNER,
    "action": Phrase.ACTION,
    "due": Phrase.DUE,
    "source": Phrase.SOURCE,
    "speaker": Phrase.SPEAKER,
    "duration": Phrase.DURATION,
    "share": Phrase.SHARE,
    "rationale": Phrase.RATIONALE,
    "key_points": Phrase.KEY_POINTS,
    "contents": Phrase.CONTENTS,
    "skip_to_content": Phrase.SKIP_TO_CONTENT,
    "transcript": Phrase.TRANSCRIPT,
    "minutes": Phrase.MINUTES,
    "no_decisions": Phrase.NO_DECISIONS,
    "no_actions": Phrase.NO_ACTIONS,
    "no_topics": Phrase.NO_TOPICS,
    "no_questions": Phrase.NO_QUESTIONS,
    "no_speaking_time": Phrase.NO_SPEAKING_TIME,
    "no_speech": Phrase.NO_SPEECH,
}


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=PackageLoader(TEMPLATE_PACKAGE, TEMPLATE_DIRECTORY),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )


def _translated(phrases: dict[str, Phrase], translations: Translations) -> dict[str, str]:
    return {key: translations.text(phrase) for key, phrase in phrases.items()}


def _shared_variables(
    document: TranscriptDocument | MinutesDocument,
    translations: Translations,
    context: RenderContext,
) -> dict[str, Any]:
    return {
        "document": document,
        "language": translations.language,
        "generator": context.generator,
        "labels": _translated(LABEL_PHRASES, translations),
        "document_title": f"{document.title}{TITLE_SEPARATOR}{document.subtitle}",
    }


@dataclass(frozen=True, slots=True)
class HtmlRenderer:
    speaker_gap_seconds: float = DEFAULT_SPEAKER_GAP

    @property
    def name(self) -> str:
        return "html"

    @property
    def media_type(self) -> str:
        return HTML_MEDIA_TYPE

    @property
    def file_extension(self) -> str:
        return HTML_EXTENSION

    def render_transcript(self, transcript: Transcript, context: RenderContext) -> str:
        translations = translations_for(context.language)
        document = compose_transcript_document(transcript, context, translations, self.speaker_gap_seconds)
        template = _environment().get_template(TRANSCRIPT_TEMPLATE)
        return template.render(**_shared_variables(document, translations, context))

    def render_minutes(self, minutes: Minutes, context: RenderContext) -> str:
        translations = translations_for(context.language)
        document = compose_minutes_document(minutes, context, translations)
        headings = _translated(SECTION_PHRASES, translations)
        template = _environment().get_template(MINUTES_TEMPLATE)
        return template.render(
            **_shared_variables(document, translations, context),
            headings=headings,
            sections=[{"anchor": anchor, "label": headings[anchor]} for anchor in SECTION_ORDER],
        )
