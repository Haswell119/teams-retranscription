from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from hansard.adapters.summarization.assembly import (
    ensure_non_empty,
    is_empty,
    meeting_title,
    participants_for,
    speaking_time_for,
    topic_from_segment,
)
from hansard.adapters.summarization.chunking import (
    ChunkEntry,
    ChunkOptions,
    ChunkPlan,
    TranscriptChunk,
    plan_chunks,
)
from hansard.adapters.summarization.citations import SentenceUnit, utterance_sentences
from hansard.adapters.summarization.dates import extract_due_date
from hansard.adapters.summarization.extraction import SpeakerDirectory, build_directory
from hansard.adapters.summarization.extractive import (
    ExtractiveMinutesWriter,
    TranscriptAnalysis,
)
from hansard.adapters.summarization.grounding import (
    GroundingOptions,
    GroundingReport,
    GroundingVerifier,
)
from hansard.adapters.summarization.merging import (
    MergeOptions,
    merge_actions,
    merge_decisions,
    merge_questions,
)
from hansard.adapters.summarization.prompts import (
    MAP_SCHEMA,
    REDUCE_SCHEMA,
    PromptPack,
    prompt_pack_for,
)
from hansard.adapters.summarization.ranking import sentences_in_segment
from hansard.adapters.summarization.structured import (
    as_index,
    as_mappings,
    as_text,
    as_texts,
    parse_json_object,
)
from hansard.adapters.summarization.text import (
    fold_for_matching,
    join_sentences,
    truncate,
)
from hansard.adapters.summarization.topics import TopicOptions, TopicSegment
from hansard.domain.errors import SummarizationError
from hansard.domain.meeting import MeetingRequest
from hansard.domain.minutes import ActionItem, Citation, Decision, Minutes, OpenQuestion, Topic
from hansard.domain.speakers import Roster
from hansard.domain.transcript import Transcript
from hansard.ports.summarization import TextGenerator
from hansard.rendering.timecode import TimestampStyle, format_range

ENGINE_NAME = "llm"
QUOTE_MATCH_THRESHOLD = 0.45
CITATION_QUOTE_LIMIT = 240


@dataclass(frozen=True, slots=True)
class MinutesOutcome:
    minutes: Minutes
    report: GroundingReport


@dataclass(frozen=True, slots=True)
class ChunkNotes:
    summary: str
    decisions: tuple[Decision, ...]
    actions: tuple[ActionItem, ...]
    questions: tuple[OpenQuestion, ...]
    entities: tuple[str, ...]


def _folded_index(haystack: str, needle: str) -> int:
    if not needle:
        return -1
    return fold_for_matching(haystack).find(fold_for_matching(needle))


def verbatim_quote(source: str, quoted: str) -> str:
    position = _folded_index(source, quoted)
    if position >= 0:
        return truncate(source[position : position + len(quoted)], CITATION_QUOTE_LIMIT)
    return truncate(source, CITATION_QUOTE_LIMIT)


def _entry_for(chunk: TranscriptChunk, plan: ChunkPlan, reference: int | None) -> ChunkEntry | None:
    if reference is None:
        return None
    entry = plan.entry(reference)
    if entry is not None and entry.reference in chunk.references:
        return entry
    return None


def _entry_by_quote(chunk: TranscriptChunk, quoted: str) -> ChunkEntry | None:
    if not quoted:
        return None
    for entry in chunk.entries:
        if _folded_index(entry.utterance.text, quoted) >= 0:
            return entry
    return None


def _unit_at(text: str, units: Sequence[SentenceUnit], position: int) -> SentenceUnit | None:
    folded = fold_for_matching(text)
    cursor = 0
    for unit in units:
        start = folded.find(fold_for_matching(unit.text), cursor)
        if start < 0:
            continue
        cursor = start + len(unit.text)
        if start <= position < cursor:
            return unit
    return None


def resolve_citation(
    chunk: TranscriptChunk,
    plan: ChunkPlan,
    reference: int | None,
    quoted: str,
) -> tuple[Citation, str] | None:
    entry = _entry_for(chunk, plan, reference) or _entry_by_quote(chunk, quoted)
    if entry is None:
        return None
    utterance = entry.utterance
    position = _folded_index(utterance.text, quoted)
    unit = (
        _unit_at(utterance.text, utterance_sentences(utterance, entry.reference), position)
        if position >= 0
        else None
    )
    span = unit.span if unit is not None else utterance.span
    source = unit.text if unit is not None else utterance.text
    return Citation(span=span, speaker=utterance.speaker, quote=verbatim_quote(source, quoted)), source


def resolve_owner(candidate: str, directory: SpeakerDirectory) -> str | None:
    text = candidate.strip()
    if not text:
        return None
    return directory.resolve(text) or directory.mentioned(text)


def resolve_due(
    candidate: str,
    source_text: str,
    language: str,
    reference: date | None,
) -> str | None:
    grounded = extract_due_date(source_text, language, reference)
    if grounded is not None:
        return grounded.value
    if candidate and _folded_index(source_text, candidate) >= 0:
        return candidate.strip()
    return None


def render_topics(segments: Sequence[TopicSegment]) -> str:
    return "\n".join(
        f"{segment.index + 1}. "
        f"{format_range(segment.span.start, segment.span.end, TimestampStyle.CLOCK)} "
        f"— {segment.title} ({', '.join(segment.keywords)})"
        for segment in segments
    )


def render_decisions(decisions: Sequence[Decision]) -> tuple[str, ...]:
    return tuple(decision.statement for decision in decisions)


def render_actions(actions: Sequence[ActionItem]) -> tuple[str, ...]:
    return tuple(
        " — ".join(part for part in (action.description, action.owner or "", action.due_date or "") if part)
        for action in actions
    )


def render_questions(questions: Sequence[OpenQuestion]) -> tuple[str, ...]:
    return tuple(question.question for question in questions)


@dataclass(frozen=True, slots=True)
class LlmMinutesWriter:
    generator: TextGenerator
    fallback: ExtractiveMinutesWriter = field(default_factory=ExtractiveMinutesWriter)
    chunk_options: ChunkOptions = field(default_factory=ChunkOptions)
    topic_options: TopicOptions = field(default_factory=TopicOptions)
    merge_options: MergeOptions = field(default_factory=MergeOptions)
    grounding_options: GroundingOptions = field(default_factory=GroundingOptions)
    language: str | None = None
    abstract_sentences: int = 5
    key_points_per_topic: int = 3
    max_map_tokens: int = 1_024
    max_reduce_tokens: int = 1_536
    include_citations: bool = True
    include_speaking_time: bool = True

    @property
    def name(self) -> str:
        return ENGINE_NAME

    def compose(self, transcript: Transcript, roster: Roster, request: MeetingRequest) -> Minutes:
        return self.compose_with_report(transcript, roster, request).minutes

    def compose_with_report(
        self,
        transcript: Transcript,
        roster: Roster,
        request: MeetingRequest,
    ) -> MinutesOutcome:
        analysis = self.fallback.analyse(transcript, roster, request)
        verifier = GroundingVerifier(language=analysis.language, options=self.grounding_options)
        if not analysis.units:
            return self._verified(
                self.fallback.compose_from(analysis, transcript, roster, request),
                transcript,
                verifier,
                ENGINE_NAME,
                "transcript has no speech",
                (),
            )
        plan = plan_chunks(transcript, self.chunk_options, analysis.language)
        pack = prompt_pack_for(analysis.language)
        directory = build_directory(transcript, roster)
        notes: list[str] = []
        harvested = self._map(plan, pack, request, analysis, directory, notes)
        if harvested is None:
            return self._verified(
                self.fallback.compose_from(analysis, transcript, roster, request),
                transcript,
                verifier,
                self.fallback.name,
                notes[0] if notes else "the model endpoint did not answer",
                notes,
            )
        minutes = self._compose_minutes(harvested, pack, analysis, transcript, roster, request, notes)
        if is_empty(minutes):
            notes.append("model produced no usable content, extractive minutes used instead")
            return self._verified(
                self.fallback.compose_from(analysis, transcript, roster, request),
                transcript,
                verifier,
                self.fallback.name,
                notes[-1],
                notes,
            )
        verified = self._verified(minutes, transcript, verifier, ENGINE_NAME, None, notes)
        if not is_empty(verified.minutes):
            return verified
        notes.append("every generated claim failed grounding, extractive minutes used instead")
        return self._verified(
            self.fallback.compose_from(analysis, transcript, roster, request),
            transcript,
            verifier,
            self.fallback.name,
            notes[-1],
            notes,
        )

    def _verified(
        self,
        minutes: Minutes,
        transcript: Transcript,
        verifier: GroundingVerifier,
        engine: str,
        fallback_reason: str | None,
        notes: Sequence[str],
    ) -> MinutesOutcome:
        checked, report = verifier.verify(minutes, transcript, engine, fallback_reason, notes)
        return MinutesOutcome(minutes=checked, report=report)

    def _map(
        self,
        plan: ChunkPlan,
        pack: PromptPack,
        request: MeetingRequest,
        analysis: TranscriptAnalysis,
        directory: SpeakerDirectory,
        notes: list[str],
    ) -> tuple[ChunkNotes, ...] | None:
        harvested: list[ChunkNotes] = []
        for chunk in plan.chunks:
            try:
                answer = self.generator.complete(
                    pack.map_system,
                    self._map_prompt(pack, chunk, plan, request, directory),
                    self.max_map_tokens,
                    MAP_SCHEMA,
                )
                payload = parse_json_object(answer)
            except SummarizationError as error:
                notes.append(f"excerpt {chunk.index + 1}: {error}")
                continue
            harvested.append(self._chunk_notes(payload, chunk, plan, directory, analysis))
        if not harvested:
            return None
        return tuple(harvested)

    def _map_prompt(
        self,
        pack: PromptPack,
        chunk: TranscriptChunk,
        plan: ChunkPlan,
        request: MeetingRequest,
        directory: SpeakerDirectory,
    ) -> str:
        context = "\n".join(entry.render() for entry in chunk.overlap)
        body = "\n".join(entry.render() for entry in chunk.body)
        return pack.map_user.format(
            title=request.title,
            participants=", ".join(directory.display_names) or pack.nothing,
            position=chunk.index + 1,
            total=len(plan.chunks),
            period=format_range(chunk.body_span.start, chunk.body_span.end, TimestampStyle.CLOCK),
            context=pack.context_block(context),
            excerpt=body,
        )

    def _chunk_notes(
        self,
        payload: Mapping[str, object],
        chunk: TranscriptChunk,
        plan: ChunkPlan,
        directory: SpeakerDirectory,
        analysis: TranscriptAnalysis,
    ) -> ChunkNotes:
        return ChunkNotes(
            summary=as_text(payload.get("summary")),
            decisions=self._decisions(payload.get("decisions"), chunk, plan),
            actions=self._actions(payload.get("actions"), chunk, plan, directory, analysis),
            questions=self._questions(payload.get("questions"), chunk, plan, directory),
            entities=as_texts(payload.get("entities")),
        )

    def _grounded(
        self,
        item: Mapping[str, object],
        chunk: TranscriptChunk,
        plan: ChunkPlan,
    ) -> tuple[Citation, str] | None:
        return resolve_citation(chunk, plan, as_index(item.get("utterance")), as_text(item.get("quote")))

    def _decisions(
        self,
        raw: object,
        chunk: TranscriptChunk,
        plan: ChunkPlan,
    ) -> tuple[Decision, ...]:
        decisions: list[Decision] = []
        for item in as_mappings(raw):
            statement = as_text(item.get("statement"))
            grounded = self._grounded(item, chunk, plan)
            if not statement or (grounded is None and self.include_citations):
                continue
            citations = (grounded[0],) if grounded is not None and self.include_citations else ()
            decisions.append(
                Decision(
                    statement=statement,
                    rationale=as_text(item.get("rationale")) or None,
                    citations=citations,
                )
            )
        return tuple(decisions)

    def _actions(
        self,
        raw: object,
        chunk: TranscriptChunk,
        plan: ChunkPlan,
        directory: SpeakerDirectory,
        analysis: TranscriptAnalysis,
    ) -> tuple[ActionItem, ...]:
        actions: list[ActionItem] = []
        for item in as_mappings(raw):
            description = as_text(item.get("description"))
            grounded = self._grounded(item, chunk, plan)
            if not description or (grounded is None and self.include_citations):
                continue
            citation, source = grounded if grounded is not None else (None, description)
            actions.append(
                ActionItem(
                    description=description,
                    owner=resolve_owner(as_text(item.get("owner")), directory),
                    due_date=resolve_due(
                        as_text(item.get("due")),
                        source,
                        analysis.language,
                        analysis.reference_date,
                    ),
                    citations=(citation,) if citation is not None and self.include_citations else (),
                )
            )
        return tuple(actions)

    def _questions(
        self,
        raw: object,
        chunk: TranscriptChunk,
        plan: ChunkPlan,
        directory: SpeakerDirectory,
    ) -> tuple[OpenQuestion, ...]:
        questions: list[OpenQuestion] = []
        for item in as_mappings(raw):
            question = as_text(item.get("question"))
            grounded = self._grounded(item, chunk, plan)
            if not question or (grounded is None and self.include_citations):
                continue
            citation = grounded[0] if grounded is not None else None
            raised = resolve_owner(as_text(item.get("raised_by")), directory)
            questions.append(
                OpenQuestion(
                    question=question,
                    raised_by=raised or (citation.speaker if citation is not None else None),
                    citations=(citation,) if citation is not None and self.include_citations else (),
                )
            )
        return tuple(questions)

    def _compose_minutes(
        self,
        harvested: Sequence[ChunkNotes],
        pack: PromptPack,
        analysis: TranscriptAnalysis,
        transcript: Transcript,
        roster: Roster,
        request: MeetingRequest,
        notes: list[str],
    ) -> Minutes:
        decisions = merge_decisions(
            [decision for chunk in harvested for decision in chunk.decisions],
            analysis.language,
            self.merge_options,
        )
        actions = merge_actions(
            [action for chunk in harvested for action in chunk.actions],
            analysis.language,
            self.merge_options,
        )
        questions = merge_questions(
            [question for chunk in harvested for question in chunk.questions],
            analysis.language,
            self.merge_options,
        )
        abstract, topics = self._reduce(
            harvested, decisions, actions, questions, pack, analysis, request, notes
        )
        minutes = Minutes(
            title=meeting_title(request.title, analysis.segments),
            abstract=abstract,
            language=analysis.language,
            generated_at=self.fallback.clock(),
            participants=participants_for(transcript, roster),
            topics=topics,
            decisions=decisions,
            actions=actions,
            open_questions=questions,
            speaking_time=speaking_time_for(transcript) if self.include_speaking_time else (),
        )
        return ensure_non_empty(minutes, analysis.units, analysis.segments)

    def _reduce(
        self,
        harvested: Sequence[ChunkNotes],
        decisions: Sequence[Decision],
        actions: Sequence[ActionItem],
        questions: Sequence[OpenQuestion],
        pack: PromptPack,
        analysis: TranscriptAnalysis,
        request: MeetingRequest,
        notes: list[str],
    ) -> tuple[str, tuple[Topic, ...]]:
        prompt = pack.reduce_user.format(
            title=request.title,
            participants=", ".join(participant for participant in request.expected_participants)
            or pack.nothing,
            duration=format_range(
                analysis.units[0].span.start,
                analysis.units[-1].span.end,
                TimestampStyle.CLOCK,
            ),
            summaries=pack.listing(tuple(chunk.summary for chunk in harvested if chunk.summary)),
            decisions=pack.listing(render_decisions(decisions)),
            actions=pack.listing(render_actions(actions)),
            questions=pack.listing(render_questions(questions)),
            topics=render_topics(analysis.segments) or pack.nothing,
            abstract_sentences=self.abstract_sentences,
        )
        try:
            payload = parse_json_object(
                self.generator.complete(pack.reduce_system, prompt, self.max_reduce_tokens, REDUCE_SCHEMA)
            )
        except SummarizationError as error:
            notes.append(f"consolidation fell back to extractive summarisation: {error}")
            return self.fallback.abstract(analysis), self._extractive_topics(analysis)
        abstract = as_text(payload.get("abstract")) or join_sentences([chunk.summary for chunk in harvested])
        return abstract, self._topics(payload.get("topics"), analysis)

    def _extractive_topics(self, analysis: TranscriptAnalysis) -> tuple[Topic, ...]:
        return tuple(
            topic_from_segment(
                segment,
                sentences_in_segment(analysis.sentences, segment),
                self.key_points_per_topic,
            )
            for segment in analysis.segments
        )

    def _topics(self, raw: object, analysis: TranscriptAnalysis) -> tuple[Topic, ...]:
        described: dict[int, Mapping[str, object]] = {}
        for item in as_mappings(raw):
            index = as_index(item.get("index"))
            if index is not None:
                described[index - 1] = item
        topics: list[Topic] = []
        for segment in analysis.segments:
            described_topic = described.get(segment.index)
            sentences = sentences_in_segment(analysis.sentences, segment)
            if described_topic is None:
                topics.append(topic_from_segment(segment, sentences, self.key_points_per_topic))
                continue
            topic = topic_from_segment(
                segment,
                sentences,
                self.key_points_per_topic,
                title=as_text(described_topic.get("title")),
                summary=as_text(described_topic.get("summary")),
            )
            points = as_texts(described_topic.get("key_points"))
            topics.append(replace(topic, key_points=points) if points else topic)
        return tuple(topics)
