from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from hansard.adapters.summarization.citations import SentenceUnit
from hansard.adapters.summarization.dates import DueDate, extract_due_date
from hansard.adapters.summarization.patterns import (
    MENTION,
    VOCATIVE_HEAD,
    VOCATIVE_TAIL,
    CueSet,
    cues_for,
    first_match,
    matches_any,
)
from hansard.adapters.summarization.text import (
    content_terms,
    fold_for_matching,
    jaccard,
    tokenise,
)
from hansard.domain.language import normalise_tag
from hansard.domain.speakers import UNKNOWN_SPEAKER, Roster
from hansard.domain.transcript import Transcript

MINIMUM_DECISION_TERMS = 2
MINIMUM_ACTION_TERMS = 2


def language_of(unit: SentenceUnit, fallback: str) -> str:
    return normalise_tag(unit.language) or fallback


@dataclass(frozen=True, slots=True)
class ExtractionOptions:
    answer_window_seconds: float = 150.0
    answer_window_utterances: int = 4
    answer_overlap: float = 0.22
    rationale_window: int = 2
    reply_window_seconds: float = 45.0
    reply_window_utterances: int = 2
    pairing_window_units: int = 4
    acknowledgement_terms: int = 4
    max_decisions: int = 20
    max_actions: int = 30
    max_questions: int = 12


@dataclass(frozen=True, slots=True)
class SpeakerDirectory:
    display_names: tuple[str, ...]
    aliases: Mapping[str, str] = field(default_factory=dict)

    def resolve(self, mention: str) -> str | None:
        key = fold_for_matching(mention).strip(" .,:;!?")
        return self.aliases.get(key)

    def mentioned(self, text: str, exclude: str = "") -> str | None:
        folded = fold_for_matching(text)
        best: tuple[int, str] | None = None
        for alias, display in self.aliases.items():
            if display == exclude or len(alias) < 3:
                continue
            found = re.search(rf"\b{re.escape(alias)}\b", folded) is not None
            if found and (best is None or len(alias) > best[0]):
                best = (len(alias), display)
        return best[1] if best is not None else None


def build_directory(transcript: Transcript, roster: Roster) -> SpeakerDirectory:
    display_names: list[str] = []
    for participant in roster.participants:
        if participant.display_name not in display_names:
            display_names.append(participant.display_name)
    for speaker in transcript.speakers:
        if speaker and speaker != UNKNOWN_SPEAKER and speaker not in display_names:
            display_names.append(speaker)
    aliases: dict[str, str] = {}
    for display in display_names:
        folded = fold_for_matching(display)
        aliases.setdefault(folded, display)
        for part in folded.split():
            if len(part) >= 3:
                aliases.setdefault(part, display)
        aliases.setdefault(folded.replace(" ", "."), display)
        aliases.setdefault(folded.replace(" ", ""), display)
    return SpeakerDirectory(display_names=tuple(display_names), aliases=aliases)


@dataclass(frozen=True, slots=True)
class DecisionCandidate:
    unit: SentenceUnit
    cue: str
    is_strong: bool
    statement: str
    rationale: str | None = None
    rationale_unit: SentenceUnit | None = None


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    unit: SentenceUnit
    cue: str
    owner: str | None
    owner_source: str
    due: DueDate | None
    support: tuple[SentenceUnit, ...] = ()

    @property
    def units(self) -> tuple[SentenceUnit, ...]:
        return (self.unit, *self.support)


@dataclass(frozen=True, slots=True)
class QuestionCandidate:
    unit: SentenceUnit
    answered: bool


@dataclass(frozen=True, slots=True)
class CandidateSet:
    decisions: tuple[DecisionCandidate, ...]
    actions: tuple[ActionCandidate, ...]
    questions: tuple[QuestionCandidate, ...]


def _is_question(unit: SentenceUnit, folded: str, cues: CueSet) -> bool:
    return unit.is_question or matches_any(folded, cues.question_openers)


def _decision_of(unit: SentenceUnit, folded: str, cues: CueSet, language: str) -> DecisionCandidate | None:
    if _is_question(unit, folded, cues):
        return None
    if len(content_terms(unit.text, language)) < MINIMUM_DECISION_TERMS:
        return None
    strong = first_match(folded, cues.strong_decisions)
    blocked = matches_any(folded, cues.blockers)
    if strong is not None and not blocked:
        return DecisionCandidate(unit=unit, cue=strong, is_strong=True, statement=unit.text)
    weak = first_match(folded, cues.weak_decisions)
    if weak is not None and not blocked:
        return DecisionCandidate(unit=unit, cue=weak, is_strong=False, statement=unit.text)
    return None


def _causal_position(text: str, cues: CueSet) -> int | None:
    folded = fold_for_matching(text)
    positions = [
        found.start() for pattern in cues.causal for found in [pattern.search(folded)] if found is not None
    ]
    return min(positions) if positions else None


def split_rationale(
    unit: SentenceUnit,
    units: Sequence[SentenceUnit],
    cues: CueSet,
    window: int,
    language: str,
) -> tuple[str, str | None, SentenceUnit | None]:
    position = _causal_position(unit.text, cues)
    if position is not None and position > 0:
        statement = unit.text[:position].rstrip(" ,;:-")
        if len(content_terms(statement, language)) >= MINIMUM_DECISION_TERMS:
            return statement, unit.text[position:].strip(" .,;:"), unit
    for offset in range(1, window + 1):
        following = unit.index + offset
        if following >= len(units):
            break
        candidate = units[following]
        if _causal_position(candidate.text, cues) == 0:
            return unit.text, candidate.text.strip(), candidate
    return unit.text, None, None


def _mention_owner(text: str, directory: SpeakerDirectory) -> str | None:
    for mention in MENTION.findall(text):
        resolved = directory.resolve(mention)
        if resolved is not None:
            return resolved
    return None


def _vocative_owner(text: str, directory: SpeakerDirectory, speaker: str) -> str | None:
    for pattern in (VOCATIVE_HEAD, VOCATIVE_TAIL):
        found = pattern.search(text)
        if found is None:
            continue
        resolved = directory.resolve(found.group(1))
        if resolved is not None and resolved != speaker:
            return resolved
    return None


def _third_person_owner(text: str, directory: SpeakerDirectory, cues: CueSet) -> str | None:
    folded = fold_for_matching(text)
    for alias, display in directory.aliases.items():
        if len(alias) < 3:
            continue
        for verb in cues.third_person_verbs:
            if re.search(rf"\b{re.escape(alias)}\s+{re.escape(verb)}\b", folded) is not None:
                return display
    return None


def _commitment_owner(
    unit: SentenceUnit,
    units: Sequence[SentenceUnit],
    cues: CueSet,
    options: ExtractionOptions,
) -> str | None:
    for offset in range(1, options.reply_window_utterances + 1):
        position = unit.index + offset
        if position >= len(units):
            break
        candidate = units[position]
        if candidate.span.start - unit.span.end > options.reply_window_seconds:
            break
        if matches_any(fold_for_matching(candidate.text), cues.self_actions):
            return candidate.speaker if candidate.speaker != UNKNOWN_SPEAKER else None
    return None


def _reply_owner(
    unit: SentenceUnit,
    units: Sequence[SentenceUnit],
    cues: CueSet,
    options: ExtractionOptions,
) -> str | None:
    for offset in range(1, options.reply_window_utterances + 1):
        position = unit.index + offset
        if position >= len(units):
            break
        candidate = units[position]
        if candidate.speaker == unit.speaker:
            continue
        if candidate.span.start - unit.span.end > options.reply_window_seconds:
            break
        folded = fold_for_matching(candidate.text)
        if matches_any(folded, cues.self_actions) or matches_any(folded, cues.answer_markers):
            return candidate.speaker
    return None


@dataclass(frozen=True, slots=True)
class OwnerAttribution:
    owner: str | None
    source: str


def attribute_owner(
    unit: SentenceUnit,
    units: Sequence[SentenceUnit],
    directory: SpeakerDirectory,
    cues: CueSet,
    options: ExtractionOptions,
) -> OwnerAttribution:
    folded = fold_for_matching(unit.text)
    mention = _mention_owner(unit.text, directory)
    if mention is not None:
        return OwnerAttribution(mention, "mention")
    if matches_any(folded, cues.self_actions):
        return OwnerAttribution(unit.speaker if unit.speaker != UNKNOWN_SPEAKER else None, "first_person")
    vocative = _vocative_owner(unit.text, directory, unit.speaker)
    if vocative is not None:
        return OwnerAttribution(vocative, "vocative")
    third_person = _third_person_owner(unit.text, directory, cues)
    if third_person is not None:
        return OwnerAttribution(third_person, "third_person")
    if matches_any(folded, cues.directed_actions):
        named = directory.mentioned(unit.text, exclude=unit.speaker)
        if named is not None:
            return OwnerAttribution(named, "named")
        others = [name for name in directory.display_names if name != unit.speaker]
        if len(others) == 1:
            return OwnerAttribution(others[0], "sole_counterpart")
        reply = _reply_owner(unit, units, cues, options)
        if reply is not None:
            return OwnerAttribution(reply, "reply")
    commitment = _commitment_owner(unit, units, cues, options)
    if commitment is not None:
        return OwnerAttribution(commitment, "commitment")
    return OwnerAttribution(None, "unassigned")


def _action_of(
    unit: SentenceUnit,
    units: Sequence[SentenceUnit],
    directory: SpeakerDirectory,
    cues: CueSet,
    options: ExtractionOptions,
    language: str,
    reference: date | None,
) -> ActionCandidate | None:
    folded = fold_for_matching(unit.text)
    if len(content_terms(unit.text, language)) < MINIMUM_ACTION_TERMS:
        return None
    cue = (
        first_match(folded, cues.self_actions)
        or first_match(folded, cues.directed_actions)
        or first_match(folded, cues.impersonal_actions)
    )
    if cue is None:
        return None
    if unit.is_question and not matches_any(folded, cues.directed_actions):
        return None
    attribution = attribute_owner(unit, units, directory, cues, options)
    return ActionCandidate(
        unit=unit,
        cue=cue,
        owner=attribution.owner,
        owner_source=attribution.source,
        due=extract_due_date(unit.text, language, reference),
    )


def _is_answered(
    unit: SentenceUnit,
    units: Sequence[SentenceUnit],
    cues: CueSet,
    options: ExtractionOptions,
    language: str,
) -> bool:
    terms = set(content_terms(unit.text, language))
    for offset in range(1, options.answer_window_utterances + 1):
        position = unit.index + offset
        if position >= len(units):
            break
        candidate = units[position]
        if candidate.span.start - unit.span.end > options.answer_window_seconds:
            break
        if candidate.speaker == unit.speaker:
            continue
        folded = fold_for_matching(candidate.text)
        if offset <= 2 and matches_any(folded, cues.answer_markers):
            return True
        if candidate.is_question:
            continue
        if jaccard(terms, content_terms(candidate.text, language)) >= options.answer_overlap:
            return True
    return False


def _question_of(
    unit: SentenceUnit,
    units: Sequence[SentenceUnit],
    cues: CueSet,
    options: ExtractionOptions,
    language: str,
) -> QuestionCandidate | None:
    folded = fold_for_matching(unit.text)
    if not _is_question(unit, folded, cues):
        return None
    if len(tokenise(unit.text)) < 4:
        return None
    if len(content_terms(unit.text, language)) < 2:
        return None
    return QuestionCandidate(unit=unit, answered=_is_answered(unit, units, cues, options, language))


def _richer(left: ActionCandidate, right: ActionCandidate, language: str) -> bool:
    return len(content_terms(left.unit.text, language)) >= len(content_terms(right.unit.text, language))


def _merge_pair(
    request: ActionCandidate,
    acceptance: ActionCandidate,
    language: str,
) -> ActionCandidate:
    primary, secondary = (
        (request, acceptance) if _richer(request, acceptance, language) else (acceptance, request)
    )
    return ActionCandidate(
        unit=primary.unit,
        cue=primary.cue,
        owner=primary.owner or secondary.owner,
        owner_source=primary.owner_source,
        due=primary.due or secondary.due,
        support=(*primary.support, secondary.unit, *secondary.support),
    )


def _is_acceptance_of(
    request: ActionCandidate,
    acceptance: ActionCandidate,
    options: ExtractionOptions,
    language: str,
) -> bool:
    accepted_terms = set(content_terms(acceptance.unit.text, language))
    if len(accepted_terms) <= options.acknowledgement_terms:
        return True
    return bool(accepted_terms & set(content_terms(request.unit.text, language)))


def pair_requests_with_acceptances(
    actions: Sequence[ActionCandidate],
    options: ExtractionOptions,
    language: str,
) -> tuple[ActionCandidate, ...]:
    paired: list[ActionCandidate] = []
    for action in actions:
        if action.owner_source == "first_person" and action.owner is not None:
            match = _pending_request(paired, action, options)
            if match is not None and _is_acceptance_of(paired[match], action, options, language):
                paired[match] = _merge_pair(paired[match], action, language)
                continue
        paired.append(action)
    return tuple(paired)


def _pending_request(
    paired: Sequence[ActionCandidate],
    acceptance: ActionCandidate,
    options: ExtractionOptions,
) -> int | None:
    for position in range(len(paired) - 1, -1, -1):
        candidate = paired[position]
        if candidate.owner_source == "first_person" or candidate.owner != acceptance.owner:
            continue
        if acceptance.unit.index - candidate.unit.index > options.pairing_window_units:
            return None
        if acceptance.unit.span.start - candidate.unit.span.end > options.answer_window_seconds:
            return None
        return position
    return None


@dataclass(frozen=True, slots=True)
class CandidateExtractor:
    language: str
    directory: SpeakerDirectory
    options: ExtractionOptions = field(default_factory=ExtractionOptions)
    reference_date: date | None = None

    @property
    def cues(self) -> CueSet:
        return cues_for(self.language)

    def extract(self, units: Sequence[SentenceUnit]) -> CandidateSet:
        decisions: list[DecisionCandidate] = []
        actions: list[ActionCandidate] = []
        questions: list[QuestionCandidate] = []
        for unit in units:
            spoken = language_of(unit, self.language)
            cues = cues_for(spoken)
            folded = fold_for_matching(unit.text)
            decision = _decision_of(unit, folded, cues, spoken)
            if decision is not None:
                statement, rationale, rationale_unit = split_rationale(
                    unit, units, cues, self.options.rationale_window, spoken
                )
                decisions.append(
                    DecisionCandidate(
                        unit=decision.unit,
                        cue=decision.cue,
                        is_strong=decision.is_strong,
                        statement=statement,
                        rationale=rationale,
                        rationale_unit=rationale_unit,
                    )
                )
                continue
            action = _action_of(unit, units, self.directory, cues, self.options, spoken, self.reference_date)
            if action is not None:
                actions.append(action)
            question = _question_of(unit, units, cues, self.options, spoken)
            if question is not None and not question.answered:
                questions.append(question)
        return CandidateSet(
            decisions=tuple(decisions[: self.options.max_decisions]),
            actions=pair_requests_with_acceptances(actions, self.options, self.language)[
                : self.options.max_actions
            ],
            questions=tuple(questions[: self.options.max_questions]),
        )
