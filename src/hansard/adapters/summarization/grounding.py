from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from hansard.adapters.asr.phonetics import similarity, sound_keys
from hansard.adapters.summarization.text import (
    capitalised_runs,
    content_terms,
    fold_for_matching,
    numbers_in,
    split_sentences,
    tokenise,
)
from hansard.domain.minutes import ActionItem, Citation, Decision, Minutes, OpenQuestion, Topic
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript


class Verdict(StrEnum):
    SUPPORTED = "supported"
    WEAK = "weak"
    UNSUPPORTED = "unsupported"


class ClaimKind(StrEnum):
    ABSTRACT = "abstract"
    TOPIC = "topic"
    KEY_POINT = "key_point"
    DECISION = "decision"
    ACTION = "action"
    QUESTION = "question"


@dataclass(frozen=True, slots=True)
class GroundingOptions:
    cited_threshold: float = 0.6
    global_threshold: float = 0.5
    window_padding_seconds: float = 20.0
    fuzzy_threshold: float = 0.86
    minimum_terms: int = 2
    drop_unsupported: bool = True


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    kind: ClaimKind
    text: str
    verdict: Verdict
    cited_support: float
    global_support: float
    missing_terms: tuple[str, ...] = ()
    unsupported_numbers: tuple[str, ...] = ()
    span: TimeSpan | None = None

    @property
    def is_kept(self) -> bool:
        return self.verdict is not Verdict.UNSUPPORTED


@dataclass(frozen=True, slots=True)
class GroundingReport:
    engine: str
    checks: tuple[ClaimCheck, ...] = ()
    dropped: tuple[ClaimCheck, ...] = ()
    unsupported_numbers: tuple[str, ...] = ()
    unsupported_entities: tuple[str, ...] = ()
    fallback_reason: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def claim_count(self) -> int:
        return len(self.checks) + len(self.dropped)

    @property
    def supported_ratio(self) -> float:
        if not self.claim_count:
            return 1.0
        supported = sum(1 for check in self.checks if check.verdict is Verdict.SUPPORTED)
        return supported / self.claim_count

    @property
    def is_clean(self) -> bool:
        return (
            not self.dropped
            and not self.unsupported_numbers
            and not self.unsupported_entities
            and all(check.verdict is Verdict.SUPPORTED for check in self.checks)
        )


@dataclass(frozen=True, slots=True)
class TranscriptIndex:
    language: str
    utterance_spans: tuple[TimeSpan, ...]
    utterance_terms: tuple[frozenset[str], ...]
    global_terms: frozenset[str]
    global_keys: frozenset[str]
    surface_tokens: frozenset[str]
    numbers: frozenset[str]

    def terms_in(self, span: TimeSpan | None) -> frozenset[str]:
        if span is None:
            return self.global_terms
        selected: set[str] = set()
        for utterance_span, terms in zip(self.utterance_spans, self.utterance_terms, strict=True):
            if utterance_span.intersects(span) or span.contains(utterance_span.start):
                selected |= terms
        return frozenset(selected)

    def keys_of(self, terms: frozenset[str]) -> frozenset[str]:
        if terms is self.global_terms:
            return self.global_keys
        return frozenset(key for term in terms for key in sound_keys(term, self.language))


def _normalised_number(value: str) -> str:
    return value.replace(",", "").replace(".", "").lstrip("0") or "0"


def build_index(
    transcript: Transcript,
    language: str,
    extra_vocabulary: Sequence[str] = (),
) -> TranscriptIndex:
    spans: list[TimeSpan] = []
    per_utterance: list[frozenset[str]] = []
    surface: set[str] = set()
    numbers: set[str] = set()
    for utterance in transcript.utterances:
        spans.append(utterance.span)
        per_utterance.append(frozenset(content_terms(utterance.text, language)))
        surface.update(tokenise(utterance.text))
        surface.update(tokenise(utterance.speaker))
        numbers.update(_normalised_number(number) for number in numbers_in(utterance.text))
    for entry in extra_vocabulary:
        surface.update(tokenise(entry))
    global_terms = frozenset().union(*per_utterance) if per_utterance else frozenset()
    return TranscriptIndex(
        language=language,
        utterance_spans=tuple(spans),
        utterance_terms=tuple(per_utterance),
        global_terms=global_terms,
        global_keys=frozenset(key for term in global_terms for key in sound_keys(term, language)),
        surface_tokens=frozenset(surface),
        numbers=frozenset(numbers),
    )


def citation_window(citations: Sequence[Citation], padding: float) -> TimeSpan | None:
    if not citations:
        return None
    start = min(citation.span.start for citation in citations)
    end = max(citation.span.end for citation in citations)
    return TimeSpan(max(0.0, start - padding), end + padding)


def _is_supported_term(
    term: str,
    available: frozenset[str],
    keys: frozenset[str],
    language: str,
    fuzzy_threshold: float,
) -> bool:
    if term in available:
        return True
    variants = sound_keys(term, language)
    if any(key in keys for key in variants):
        return True
    return any(similarity(key, candidate) >= fuzzy_threshold for key in variants for candidate in keys)


def support_ratio(
    terms: Sequence[str],
    available: frozenset[str],
    keys: frozenset[str],
    language: str,
    fuzzy_threshold: float,
) -> tuple[float, tuple[str, ...]]:
    if not terms:
        return 1.0, ()
    missing = tuple(
        term for term in terms if not _is_supported_term(term, available, keys, language, fuzzy_threshold)
    )
    return (len(terms) - len(missing)) / len(terms), missing


def unsupported_numbers_in(text: str, index: TranscriptIndex) -> tuple[str, ...]:
    return tuple(number for number in numbers_in(text) if _normalised_number(number) not in index.numbers)


def unsupported_entities_in(text: str, index: TranscriptIndex) -> tuple[str, ...]:
    flagged: list[str] = []
    for run in capitalised_runs(text):
        tokens = tokenise(run)
        if tokens and not all(token in index.surface_tokens for token in tokens):
            flagged.append(fold_for_matching(run).strip())
    return tuple(flagged)


@dataclass(frozen=True, slots=True)
class GroundingVerifier:
    language: str = "en"
    options: GroundingOptions = field(default_factory=GroundingOptions)

    def check(
        self,
        kind: ClaimKind,
        text: str,
        citations: Sequence[Citation],
        index: TranscriptIndex,
    ) -> ClaimCheck:
        terms = content_terms(text, self.language)
        window = citation_window(citations, self.options.window_padding_seconds)
        cited_terms = index.terms_in(window)
        cited, missing = support_ratio(
            terms,
            cited_terms,
            index.keys_of(cited_terms),
            self.language,
            self.options.fuzzy_threshold,
        )
        overall, _ = support_ratio(
            terms,
            index.global_terms,
            index.global_keys,
            self.language,
            self.options.fuzzy_threshold,
        )
        numbers = unsupported_numbers_in(text, index)
        return ClaimCheck(
            kind=kind,
            text=text,
            verdict=self._verdict(terms, cited, overall, numbers),
            cited_support=cited,
            global_support=overall,
            missing_terms=missing,
            unsupported_numbers=numbers,
            span=window,
        )

    def _verdict(
        self,
        terms: Sequence[str],
        cited: float,
        overall: float,
        numbers: Sequence[str],
    ) -> Verdict:
        if len(terms) < self.options.minimum_terms:
            return Verdict.SUPPORTED if overall >= self.options.global_threshold else Verdict.WEAK
        if overall < self.options.global_threshold:
            return Verdict.UNSUPPORTED
        if cited < self.options.cited_threshold or numbers:
            return Verdict.WEAK
        return Verdict.SUPPORTED

    def verify(
        self,
        minutes: Minutes,
        transcript: Transcript,
        engine: str,
        fallback_reason: str | None = None,
        notes: Sequence[str] = (),
    ) -> tuple[Minutes, GroundingReport]:
        index = build_index(
            transcript,
            self.language,
            [participant.display_name for participant in minutes.participants],
        )
        kept: list[ClaimCheck] = []
        dropped: list[ClaimCheck] = []
        abstract = self._filter_prose(minutes.abstract, ClaimKind.ABSTRACT, (), index, kept, dropped)
        topics = tuple(self._verify_topic(topic, index, kept, dropped) for topic in minutes.topics)
        decisions = tuple(self._verify_decisions(minutes.decisions, index, kept, dropped))
        actions = tuple(self._verify_actions(minutes.actions, index, kept, dropped))
        questions = tuple(self._verify_questions(minutes.open_questions, index, kept, dropped))
        verified = replace(
            minutes,
            abstract=abstract,
            topics=topics,
            decisions=decisions,
            actions=actions,
            open_questions=questions,
        )
        return verified, GroundingReport(
            engine=engine,
            checks=tuple(kept),
            dropped=tuple(dropped),
            unsupported_numbers=self._collected_numbers(kept, dropped),
            unsupported_entities=self._collected_entities(minutes, index),
            fallback_reason=fallback_reason,
            notes=tuple(notes),
        )

    def _record(
        self,
        check: ClaimCheck,
        kept: list[ClaimCheck],
        dropped: list[ClaimCheck],
    ) -> bool:
        if check.is_kept or not self.options.drop_unsupported:
            kept.append(check)
            return True
        dropped.append(check)
        return False

    def _filter_prose(
        self,
        prose: str,
        kind: ClaimKind,
        citations: Sequence[Citation],
        index: TranscriptIndex,
        kept: list[ClaimCheck],
        dropped: list[ClaimCheck],
    ) -> str:
        sentences = split_sentences(prose)
        surviving = [
            sentence
            for sentence in sentences
            if self._record(self.check(kind, sentence, citations, index), kept, dropped)
        ]
        return " ".join(surviving)

    def _verify_topic(
        self,
        topic: Topic,
        index: TranscriptIndex,
        kept: list[ClaimCheck],
        dropped: list[ClaimCheck],
    ) -> Topic:
        citations = (Citation(span=topic.span, speaker="", quote=""),)
        summary = self._filter_prose(topic.summary, ClaimKind.TOPIC, citations, index, kept, dropped)
        points = tuple(
            point
            for point in topic.key_points
            if self._record(self.check(ClaimKind.KEY_POINT, point, citations, index), kept, dropped)
        )
        return replace(topic, summary=summary, key_points=points)

    def _verify_decisions(
        self,
        decisions: Sequence[Decision],
        index: TranscriptIndex,
        kept: list[ClaimCheck],
        dropped: list[ClaimCheck],
    ) -> list[Decision]:
        surviving: list[Decision] = []
        for decision in decisions:
            statement = self.check(ClaimKind.DECISION, decision.statement, decision.citations, index)
            if not self._record(statement, kept, dropped):
                continue
            rationale = decision.rationale
            if rationale:
                check = self.check(ClaimKind.DECISION, rationale, decision.citations, index)
                if not self._record(check, kept, dropped):
                    rationale = None
            surviving.append(replace(decision, rationale=rationale))
        return surviving

    def _verify_actions(
        self,
        actions: Sequence[ActionItem],
        index: TranscriptIndex,
        kept: list[ClaimCheck],
        dropped: list[ClaimCheck],
    ) -> list[ActionItem]:
        surviving: list[ActionItem] = []
        for action in actions:
            check = self.check(ClaimKind.ACTION, action.description, action.citations, index)
            if self._record(check, kept, dropped):
                surviving.append(replace(action, owner=self._verified_owner(action.owner, index)))
        return surviving

    def _verified_owner(self, owner: str | None, index: TranscriptIndex) -> str | None:
        if owner is None:
            return None
        tokens = tokenise(owner)
        if tokens and all(token in index.surface_tokens for token in tokens):
            return owner
        return None

    def _verify_questions(
        self,
        questions: Sequence[OpenQuestion],
        index: TranscriptIndex,
        kept: list[ClaimCheck],
        dropped: list[ClaimCheck],
    ) -> list[OpenQuestion]:
        surviving: list[OpenQuestion] = []
        for question in questions:
            check = self.check(ClaimKind.QUESTION, question.question, question.citations, index)
            if self._record(check, kept, dropped):
                surviving.append(question)
        return surviving

    def _collected_numbers(
        self,
        kept: Sequence[ClaimCheck],
        dropped: Sequence[ClaimCheck],
    ) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for check in (*kept, *dropped):
            for number in check.unsupported_numbers:
                seen.setdefault(number, None)
        return tuple(seen)

    def _collected_entities(self, minutes: Minutes, index: TranscriptIndex) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for text in minutes_claims(minutes):
            for entity in unsupported_entities_in(text, index):
                seen.setdefault(entity, None)
        return tuple(seen)


def minutes_claims(minutes: Minutes) -> tuple[str, ...]:
    claims: list[str] = list(split_sentences(minutes.abstract))
    for topic in minutes.topics:
        claims.extend(split_sentences(topic.summary))
        claims.extend(topic.key_points)
    for decision in minutes.decisions:
        claims.append(decision.statement)
        if decision.rationale:
            claims.append(decision.rationale)
    claims.extend(action.description for action in minutes.actions)
    claims.extend(question.question for question in minutes.open_questions)
    return tuple(claim for claim in claims if claim.strip())
