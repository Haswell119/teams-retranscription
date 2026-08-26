from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hansard.domain.language import MIXED, normalise_tag
from hansard.domain.minutes import Citation, Minutes
from hansard.domain.speakers import UNKNOWN_SPEAKER
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.rendering.i18n import Phrase, Translations
from hansard.rendering.ports import RenderContext
from hansard.rendering.timecode import TimestampStyle, format_range, format_timestamp

DEFAULT_SPEAKER_GAP = 1.5
EMPTY_VALUE = "—"
TITLE_SEPARATOR = " — "


@dataclass(frozen=True, slots=True)
class SpeechBlock:
    speaker: str
    span: TimeSpan
    text: str
    timecode: str


@dataclass(frozen=True, slots=True)
class LabelledValue:
    label: str
    value: str
    machine_value: str = ""


@dataclass(frozen=True, slots=True)
class SpeakingShare:
    speaker: str
    seconds: float
    share: float


@dataclass(frozen=True, slots=True)
class SpeakingEntry:
    speaker: str
    seconds: float
    share: float
    duration_label: str
    share_label: str

    @property
    def percentage(self) -> float:
        return round(self.share * 100.0, 1)


@dataclass(frozen=True, slots=True)
class DecisionEntry:
    statement: str
    rationale: str
    timecodes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionEntry:
    owner: str
    description: str
    due: str
    timecodes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TopicEntry:
    position: int
    title: str
    period: str
    summary: str
    key_points: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuestionEntry:
    question: str
    attribution: str
    timecodes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranscriptDocument:
    title: str
    subtitle: str
    metadata: tuple[LabelledValue, ...]
    blocks: tuple[SpeechBlock, ...]
    footer: str
    language: str


@dataclass(frozen=True, slots=True)
class MinutesDocument:
    title: str
    subtitle: str
    metadata: tuple[LabelledValue, ...]
    summary: str
    decisions: tuple[DecisionEntry, ...]
    actions: tuple[ActionEntry, ...]
    topics: tuple[TopicEntry, ...]
    questions: tuple[QuestionEntry, ...]
    speaking: tuple[SpeakingEntry, ...]
    footer: str
    generated_at: str
    language: str


@dataclass(frozen=True, slots=True)
class CueLayout:
    max_lines: int = 2
    max_characters_per_line: int = 42
    minimum_duration: float = 1.0
    maximum_duration: float = 7.0


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    index: int
    span: TimeSpan
    speaker: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def display_speaker(speaker: str, translations: Translations) -> str:
    if not speaker.strip() or speaker == UNKNOWN_SPEAKER:
        return translations.text(Phrase.UNKNOWN_SPEAKER)
    return speaker


def speaker_blocks(
    transcript: Transcript,
    translations: Translations,
    max_gap: float = DEFAULT_SPEAKER_GAP,
) -> tuple[SpeechBlock, ...]:
    merged = transcript.merged_by_speaker(max_gap)
    return tuple(
        SpeechBlock(
            speaker=display_speaker(utterance.speaker, translations),
            span=utterance.span,
            text=collapse_whitespace(utterance.text),
            timecode=format_timestamp(utterance.span.start, TimestampStyle.CLOCK),
        )
        for utterance in merged.utterances
        if utterance.text.strip()
    )


def speaking_seconds(transcript: Transcript) -> tuple[tuple[str, float], ...]:
    totals: dict[str, float] = {}
    for utterance in transcript.utterances:
        totals[utterance.speaker] = totals.get(utterance.speaker, 0.0) + utterance.span.duration
    return tuple(totals.items())


def speaking_shares(entries: Sequence[tuple[str, float]]) -> tuple[SpeakingShare, ...]:
    measured = [(speaker, max(0.0, seconds)) for speaker, seconds in entries]
    total = sum(seconds for _, seconds in measured)
    ordered = sorted(measured, key=lambda entry: (-entry[1], entry[0]))
    return tuple(
        SpeakingShare(speaker=speaker, seconds=seconds, share=seconds / total if total > 0.0 else 0.0)
        for speaker, seconds in ordered
    )


def format_human_duration(seconds: float, translations: Translations) -> str:
    whole_seconds = int(max(0.0, seconds))
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} {translations.text(Phrase.UNIT_HOUR)}")
    if minutes:
        parts.append(f"{minutes} {translations.text(Phrase.UNIT_MINUTE)}")
    if remaining_seconds or not parts:
        parts.append(f"{remaining_seconds} {translations.text(Phrase.UNIT_SECOND)}")
    return " ".join(parts)


def format_percentage(share: float, translations: Translations) -> str:
    rendered = f"{share * 100.0:.1f}".replace(".", translations.text(Phrase.DECIMAL_SEPARATOR))
    return translations.format(Phrase.PERCENT_PATTERN, value=rendered)


def resolve_zone(timezone: str) -> tzinfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def localised(moment: datetime, timezone: str) -> datetime:
    zone = resolve_zone(timezone)
    return moment.astimezone(zone) if moment.tzinfo else moment.replace(tzinfo=zone)


def format_moment(moment: datetime | None, timezone: str, translations: Translations) -> str:
    if moment is None:
        return EMPTY_VALUE
    local = localised(moment, timezone)
    return translations.format(
        Phrase.DATE_PATTERN,
        day=local.day,
        month=translations.month_name(local.month),
        year=local.year,
        time=f"{local.hour:02d}:{local.minute:02d}",
        timezone=timezone,
    )


def format_iso_moment(moment: datetime | None, timezone: str) -> str:
    return "" if moment is None else localised(moment, timezone).isoformat()


def provenance_summary(context: RenderContext) -> str:
    labels = tuple(entry.label for entry in context.provenance)
    return ", ".join(labels) if labels else EMPTY_VALUE


def sovereignty_statement(context: RenderContext, translations: Translations) -> str:
    return translations.format(
        Phrase.SOVEREIGNTY,
        generator=context.generator,
        models=provenance_summary(context),
    )


def transcript_sovereignty_statement(context: RenderContext, translations: Translations) -> str:
    return translations.format(
        Phrase.SOVEREIGNTY_TRANSCRIPT,
        generator=context.generator,
        models=provenance_summary(context),
    )


def short_sovereignty_statement(context: RenderContext, translations: Translations) -> str:
    return translations.format(Phrase.SOVEREIGNTY_SHORT, generator=context.generator)


def citation_timecodes(citations: Sequence[Citation]) -> tuple[str, ...]:
    return tuple(format_timestamp(citation.span.start, TimestampStyle.CLOCK) for citation in citations)


def labelled(label: str, translations: Translations) -> str:
    return translations.format(Phrase.LABEL_PATTERN, label=label)


def join_or_empty(values: Sequence[str], separator: str = ", ") -> str:
    return separator.join(values) if values else EMPTY_VALUE


def transcript_speaker_names(transcript: Transcript, translations: Translations) -> tuple[str, ...]:
    return tuple(display_speaker(speaker, translations) for speaker in transcript.speakers)


def _metadata(
    translations: Translations,
    moment: datetime | None,
    timezone: str,
    duration_seconds: float,
    people_label: Phrase,
    people: Sequence[str],
    language: str,
    context: RenderContext,
) -> tuple[LabelledValue, ...]:
    return (
        LabelledValue(
            translations.text(Phrase.DATE),
            format_moment(moment, timezone, translations),
            format_iso_moment(moment, timezone),
        ),
        LabelledValue(
            translations.text(Phrase.DURATION),
            format_human_duration(duration_seconds, translations),
        ),
        LabelledValue(translations.text(people_label), join_or_empty(people)),
        LabelledValue(translations.text(Phrase.LANGUAGE), _language_value(translations, language, context)),
        LabelledValue(translations.text(Phrase.PRODUCED_WITH), provenance_summary(context)),
    )


def _language_value(translations: Translations, language: str, context: RenderContext) -> str:
    spoken = context.spoken_languages
    if normalise_tag(language) == MIXED and len(spoken) > 1:
        return f"{translations.language_names_of(spoken)} ({', '.join(spoken)})"
    return f"{translations.language_name(language)} ({language})"


def compose_transcript_document(
    transcript: Transcript,
    context: RenderContext,
    translations: Translations,
    max_gap: float = DEFAULT_SPEAKER_GAP,
) -> TranscriptDocument:
    blocks = speaker_blocks(transcript, translations, max_gap)
    people = context.participant_names or transcript_speaker_names(transcript, translations)
    language = transcript.language_profile.tag or transcript.language or context.language
    return TranscriptDocument(
        title=context.title,
        subtitle=translations.text(Phrase.TRANSCRIPT),
        metadata=_metadata(
            translations=translations,
            moment=context.started_at,
            timezone=context.timezone,
            duration_seconds=context.duration_seconds or transcript.audio_duration,
            people_label=Phrase.PARTICIPANTS,
            people=people,
            language=language,
            context=context,
        ),
        blocks=blocks,
        footer=transcript_sovereignty_statement(context, translations),
        language=translations.language,
    )


def _decision_entries(minutes: Minutes) -> tuple[DecisionEntry, ...]:
    return tuple(
        DecisionEntry(
            statement=collapse_whitespace(decision.statement),
            rationale=collapse_whitespace(decision.rationale or ""),
            timecodes=citation_timecodes(decision.citations),
        )
        for decision in minutes.decisions
    )


def _action_entries(minutes: Minutes, translations: Translations) -> tuple[ActionEntry, ...]:
    return tuple(
        ActionEntry(
            owner=action.owner or translations.text(Phrase.UNASSIGNED),
            description=collapse_whitespace(action.description),
            due=action.due_date or EMPTY_VALUE,
            timecodes=citation_timecodes(action.citations),
        )
        for action in minutes.actions
    )


def _topic_entries(minutes: Minutes) -> tuple[TopicEntry, ...]:
    return tuple(
        TopicEntry(
            position=position,
            title=collapse_whitespace(topic.title),
            period=format_range(topic.span.start, topic.span.end, TimestampStyle.CLOCK),
            summary=collapse_whitespace(topic.summary),
            key_points=tuple(collapse_whitespace(point) for point in topic.key_points),
        )
        for position, topic in enumerate(minutes.topics, start=1)
    )


def _question_entries(minutes: Minutes, translations: Translations) -> tuple[QuestionEntry, ...]:
    return tuple(
        QuestionEntry(
            question=collapse_whitespace(question.question),
            attribution=(
                translations.format(Phrase.RAISED_BY, speaker=question.raised_by)
                if question.raised_by
                else ""
            ),
            timecodes=citation_timecodes(question.citations),
        )
        for question in minutes.open_questions
    )


def _speaking_entries(minutes: Minutes, translations: Translations) -> tuple[SpeakingEntry, ...]:
    return tuple(
        SpeakingEntry(
            speaker=display_speaker(share.speaker, translations),
            seconds=share.seconds,
            share=share.share,
            duration_label=format_human_duration(share.seconds, translations),
            share_label=format_percentage(share.share, translations),
        )
        for share in speaking_shares(minutes.speaking_time)
    )


def compose_minutes_document(
    minutes: Minutes,
    context: RenderContext,
    translations: Translations,
) -> MinutesDocument:
    attendees = tuple(participant.display_name for participant in minutes.participants)
    return MinutesDocument(
        title=minutes.title or context.title,
        subtitle=translations.text(Phrase.MINUTES),
        metadata=_metadata(
            translations=translations,
            moment=context.started_at,
            timezone=context.timezone,
            duration_seconds=context.duration_seconds,
            people_label=Phrase.ATTENDEES,
            people=attendees or context.participant_names,
            language=minutes.language or context.language,
            context=context,
        ),
        summary=minutes.abstract.strip(),
        decisions=_decision_entries(minutes),
        actions=_action_entries(minutes, translations),
        topics=_topic_entries(minutes),
        questions=_question_entries(minutes, translations),
        speaking=_speaking_entries(minutes, translations),
        footer=sovereignty_statement(context, translations),
        generated_at=translations.format(
            Phrase.GENERATED_AT,
            moment=format_moment(minutes.generated_at, context.timezone, translations),
        ),
        language=translations.language,
    )


def wrap_caption_lines(text: str, max_characters_per_line: int) -> tuple[str, ...]:
    lines: list[str] = []
    current = ""
    for token in collapse_whitespace(text).split():
        candidate = f"{current} {token}" if current else token
        if current and len(candidate) > max_characters_per_line:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def group_lines_into_cues(lines: Sequence[str], max_lines: int) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(lines[start : start + max_lines]) for start in range(0, len(lines), max_lines))


def _chunk_spans(utterance: Utterance, chunks: Sequence[tuple[str, ...]]) -> tuple[TimeSpan, ...]:
    token_counts = [sum(len(line.split()) for line in chunk) for chunk in chunks]
    words = utterance.words
    if words and len(words) == sum(token_counts):
        spans: list[TimeSpan] = []
        cursor = 0
        for count in token_counts:
            selected = words[cursor : cursor + count]
            start = selected[0].span.start
            end = max(start, selected[-1].span.end)
            spans.append(TimeSpan(start, end))
            cursor += count
        return tuple(spans)
    weights = [max(1, sum(len(line) for line in chunk)) for chunk in chunks]
    total_weight = sum(weights)
    interpolated: list[TimeSpan] = []
    elapsed = 0
    for weight in weights:
        start = utterance.span.start + utterance.span.duration * elapsed / total_weight
        elapsed += weight
        end = utterance.span.start + utterance.span.duration * elapsed / total_weight
        interpolated.append(TimeSpan(start, max(start, end)))
    return tuple(interpolated)


def _sequenced_cues(
    drafts: Sequence[tuple[str, TimeSpan, tuple[str, ...]]],
    layout: CueLayout,
) -> tuple[SubtitleCue, ...]:
    ordered = sorted(drafts, key=lambda draft: (draft[1].start, draft[1].end))
    cues: list[SubtitleCue] = []
    cursor = 0.0
    for position, (speaker, span, lines) in enumerate(ordered):
        start = max(span.start, cursor)
        end = max(span.end, start + layout.minimum_duration)
        end = min(end, start + layout.maximum_duration)
        if position + 1 < len(ordered):
            following_start = ordered[position + 1][1].start
            end = min(end, max(following_start, start + layout.minimum_duration))
        cues.append(SubtitleCue(index=len(cues) + 1, span=TimeSpan(start, end), speaker=speaker, lines=lines))
        cursor = end
    return tuple(cues)


def subtitle_cues(transcript: Transcript, layout: CueLayout = CueLayout()) -> tuple[SubtitleCue, ...]:
    drafts: list[tuple[str, TimeSpan, tuple[str, ...]]] = []
    for utterance in transcript.utterances:
        lines = wrap_caption_lines(utterance.text, layout.max_characters_per_line)
        if not lines:
            continue
        chunks = group_lines_into_cues(lines, layout.max_lines)
        for chunk, span in zip(chunks, _chunk_spans(utterance, chunks), strict=True):
            drafts.append((utterance.speaker, span, chunk))
    return _sequenced_cues(drafts, layout)
