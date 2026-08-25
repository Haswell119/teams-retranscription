from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from hansard.adapters.summarization.assembly import (
    citations_of,
    ensure_non_empty,
    meeting_title,
    participants_for,
    speaking_time_for,
    topic_from_segment,
)
from hansard.adapters.summarization.citations import SentenceUnit, sentence_units
from hansard.adapters.summarization.extraction import (
    ActionCandidate,
    CandidateExtractor,
    CandidateSet,
    DecisionCandidate,
    ExtractionOptions,
    QuestionCandidate,
    build_directory,
)
from hansard.adapters.summarization.merging import (
    MergeOptions,
    merge_actions,
    merge_decisions,
    merge_questions,
)
from hansard.adapters.summarization.ranking import (
    RankedSentence,
    rank_sentences,
    select_summary_sentences,
    sentences_in_segment,
)
from hansard.adapters.summarization.text import join_sentences, resolve_language
from hansard.adapters.summarization.topics import TopicOptions, TopicSegment, segment_topics
from hansard.domain.meeting import MeetingRequest
from hansard.domain.minutes import ActionItem, Decision, Minutes, OpenQuestion, Topic
from hansard.domain.speakers import UNKNOWN_SPEAKER, Roster
from hansard.domain.transcript import Transcript

Clock = Callable[[], datetime]

ENGINE_NAME = "extractive"


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class TranscriptAnalysis:
    language: str
    units: tuple[SentenceUnit, ...]
    segments: tuple[TopicSegment, ...]
    sentences: tuple[RankedSentence, ...]
    candidates: CandidateSet
    reference_date: date


def decisions_from(
    candidates: Sequence[DecisionCandidate],
    language: str,
    include_citations: bool,
    options: MergeOptions,
) -> tuple[Decision, ...]:
    decisions = [
        Decision(
            statement=candidate.statement,
            rationale=candidate.rationale,
            citations=citations_of(
                [candidate.unit, *( [candidate.rationale_unit] if candidate.rationale_unit else [] )],
                include_citations,
            ),
        )
        for candidate in candidates
    ]
    return merge_decisions(decisions, language, options)


def actions_from(
    candidates: Sequence[ActionCandidate],
    language: str,
    include_citations: bool,
    options: MergeOptions,
) -> tuple[ActionItem, ...]:
    actions = [
        ActionItem(
            description=candidate.unit.text,
            owner=candidate.owner,
            due_date=candidate.due.value if candidate.due is not None else None,
            citations=citations_of(candidate.units, include_citations),
        )
        for candidate in candidates
    ]
    return merge_actions(actions, language, options)


def questions_from(
    candidates: Sequence[QuestionCandidate],
    language: str,
    include_citations: bool,
    options: MergeOptions,
) -> tuple[OpenQuestion, ...]:
    questions = [
        OpenQuestion(
            question=candidate.unit.text,
            raised_by=candidate.unit.speaker if candidate.unit.speaker != UNKNOWN_SPEAKER else None,
            citations=citations_of([candidate.unit], include_citations),
        )
        for candidate in candidates
    ]
    return merge_questions(questions, language, options)


@dataclass(frozen=True, slots=True)
class ExtractiveMinutesWriter:
    language: str | None = None
    abstract_sentences: int = 5
    key_points_per_topic: int = 3
    include_citations: bool = True
    include_speaking_time: bool = True
    topic_options: TopicOptions = field(default_factory=TopicOptions)
    extraction_options: ExtractionOptions = field(default_factory=ExtractionOptions)
    merge_options: MergeOptions = field(default_factory=MergeOptions)
    reference_date: date | None = None
    clock: Clock = utc_now

    @property
    def name(self) -> str:
        return ENGINE_NAME

    def analyse(
        self,
        transcript: Transcript,
        roster: Roster,
        request: MeetingRequest,
    ) -> TranscriptAnalysis:
        language = resolve_language(self.language, request.language, transcript.language)
        reference = self.reference_date or self.clock().date()
        units = sentence_units(transcript)
        segments = segment_topics(transcript, language, self.topic_options)
        extractor = CandidateExtractor(
            language=language,
            directory=build_directory(transcript, roster),
            options=self.extraction_options,
            reference_date=reference,
        )
        return TranscriptAnalysis(
            language=language,
            units=units,
            segments=segments,
            sentences=rank_sentences(units, language),
            candidates=extractor.extract(units),
            reference_date=reference,
        )

    def topics(self, analysis: TranscriptAnalysis) -> tuple[Topic, ...]:
        return tuple(
            topic_from_segment(
                segment,
                sentences_in_segment(analysis.sentences, segment),
                self.key_points_per_topic,
            )
            for segment in analysis.segments
        )

    def abstract(self, analysis: TranscriptAnalysis) -> str:
        selected = select_summary_sentences(
            analysis.sentences,
            analysis.segments,
            self.abstract_sentences,
        )
        return join_sentences([sentence.unit.text for sentence in selected])

    def compose_from(
        self,
        analysis: TranscriptAnalysis,
        transcript: Transcript,
        roster: Roster,
        request: MeetingRequest,
    ) -> Minutes:
        minutes = Minutes(
            title=meeting_title(request.title, analysis.segments),
            abstract=self.abstract(analysis),
            language=analysis.language,
            generated_at=self.clock(),
            participants=participants_for(transcript, roster),
            topics=self.topics(analysis),
            decisions=decisions_from(
                analysis.candidates.decisions,
                analysis.language,
                self.include_citations,
                self.merge_options,
            ),
            actions=actions_from(
                analysis.candidates.actions,
                analysis.language,
                self.include_citations,
                self.merge_options,
            ),
            open_questions=questions_from(
                analysis.candidates.questions,
                analysis.language,
                self.include_citations,
                self.merge_options,
            ),
            speaking_time=speaking_time_for(transcript) if self.include_speaking_time else (),
        )
        return ensure_non_empty(minutes, analysis.units, analysis.segments)

    def compose(self, transcript: Transcript, roster: Roster, request: MeetingRequest) -> Minutes:
        analysis = self.analyse(transcript, roster, request)
        return self.compose_from(analysis, transcript, roster, request)
