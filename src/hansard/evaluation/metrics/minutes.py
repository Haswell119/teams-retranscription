from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol, runtime_checkable

from hansard.domain.errors import SummarizationError
from hansard.domain.minutes import ActionItem, Decision, Minutes
from hansard.domain.transcript import Transcript
from hansard.evaluation.metrics.assignment import maximum_gain_assignment
from hansard.evaluation.normalizers import BasicNormalizer, TextNormalizer, remove_diacritics
from hansard.ports.summarization import TextGenerator

DEFAULT_MATCH_THRESHOLD = 0.7
DEFAULT_SUPPORT_THRESHOLD = 0.7
MINIMUM_CONTENT_WORD_LENGTH = 3

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_CAPITALISED_RUN = re.compile("[A-ZÀ-ÖØ-Þ][\\w\u2019'-]*(?:\\s+[A-ZÀ-ÖØ-Þ][\\w\u2019'-]*)*")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

_STOPWORDS: frozenset[str] = frozenset(
    (
        "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
        "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "is", "are", "was", "were",
        "be", "been", "being", "it", "its", "his", "her", "their", "our", "your", "my", "we", "you",
        "they", "he", "she", "i", "not", "no", "do", "does", "did", "have", "has", "had", "will",
        "would", "shall", "should", "can", "could", "may", "might", "must", "about", "into", "over",
        "under", "again", "more", "most", "other", "some", "such", "only", "own", "same", "so", "too",
        "very", "le", "la", "les", "un", "une", "des", "du", "de", "la", "au", "aux", "et", "ou",
        "mais", "donc", "or", "ni", "car", "que", "qui", "quoi", "dont", "ou", "pour", "par", "avec",
        "sans", "sous", "sur", "dans", "chez", "vers", "entre", "est", "sont", "etait", "etaient",
        "ete", "etre", "avoir", "a", "ce", "cet", "cette", "ces", "son", "sa", "ses", "leur", "leurs",
        "notre", "nos", "votre", "vos", "mon", "ma", "mes", "ton", "ta", "tes", "il", "elle", "ils",
        "elles", "nous", "vous", "je", "tu", "on", "ne", "pas", "plus", "moins", "tres", "bien", "tout",
        "tous", "toute", "toutes", "meme", "aussi", "comme", "quand", "alors", "ainsi", "cela", "ceci",
    )
)


@runtime_checkable
class ItemMatcher(Protocol):
    @property
    def threshold(self) -> float: ...

    def similarity(self, left: str, right: str) -> float: ...

    def matches(self, left: str, right: str) -> bool: ...


@runtime_checkable
class LlmJudge(Protocol):
    def score(self, minutes: Minutes, transcript: Transcript) -> RubricScores: ...


@dataclass(frozen=True, slots=True)
class TokenSetMatcher:
    threshold: float = DEFAULT_MATCH_THRESHOLD
    normalizer: TextNormalizer = field(default_factory=BasicNormalizer)

    def similarity(self, left: str, right: str) -> float:
        return token_set_similarity(
            self.normalizer.normalize(left),
            self.normalizer.normalize(right),
        )

    def matches(self, left: str, right: str) -> bool:
        return self.similarity(left, right) >= self.threshold


@dataclass(frozen=True, slots=True)
class ActionItemScore:
    precision: float
    recall: float
    f1: float
    matched: int
    reference_count: int
    hypothesis_count: int
    owner_accuracy: float


@dataclass(frozen=True, slots=True)
class RubricScores:
    coverage: float
    faithfulness: float
    actionability: float
    structure: float

    @property
    def overall(self) -> float:
        return (self.coverage + self.faithfulness + self.actionability + self.structure) / 4.0


@dataclass(frozen=True, slots=True)
class RubricJudge:
    generator: TextGenerator
    max_transcript_characters: int = 24_000
    max_tokens: int = 512

    def score(self, minutes: Minutes, transcript: Transcript) -> RubricScores:
        response = self.generator.complete(
            _JUDGE_SYSTEM_PROMPT,
            _judge_user_prompt(minutes, transcript, self.max_transcript_characters),
            self.max_tokens,
            _JUDGE_SCHEMA,
        )
        return _parse_rubric_scores(response)


def token_set_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 1.0 if left_tokens == right_tokens else 0.0
    shared = " ".join(sorted(left_tokens & right_tokens))
    left_only = " ".join(sorted(left_tokens - right_tokens))
    right_only = " ".join(sorted(right_tokens - left_tokens))
    left_combined = f"{shared} {left_only}".strip()
    right_combined = f"{shared} {right_only}".strip()
    return max(
        _ratio(shared, left_combined),
        _ratio(shared, right_combined),
        _ratio(left_combined, right_combined),
    )


def optimal_matches(
    references: Sequence[str],
    hypotheses: Sequence[str],
    matcher: ItemMatcher,
) -> tuple[tuple[int, int], ...]:
    similarities = [
        [matcher.similarity(reference, hypothesis) for hypothesis in hypotheses]
        for reference in references
    ]
    return tuple(
        (row, column)
        for row, column in maximum_gain_assignment(similarities)
        if similarities[row][column] >= matcher.threshold
    )


def action_item_f1(
    reference: Sequence[ActionItem],
    hypothesis: Sequence[ActionItem],
    matcher: ItemMatcher | None = None,
) -> ActionItemScore:
    active = matcher if matcher is not None else TokenSetMatcher()
    matches = optimal_matches(
        [item.description for item in reference],
        [item.description for item in hypothesis],
        active,
    )
    precision, recall, f1 = _precision_recall_f1(len(matches), len(reference), len(hypothesis))
    owner_hits = sum(
        1
        for row, column in matches
        if _normalized_owner(reference[row].owner) == _normalized_owner(hypothesis[column].owner)
    )
    return ActionItemScore(
        precision=precision,
        recall=recall,
        f1=f1,
        matched=len(matches),
        reference_count=len(reference),
        hypothesis_count=len(hypothesis),
        owner_accuracy=owner_hits / len(matches) if matches else 0.0,
    )


def decision_recall(
    reference: Sequence[Decision],
    hypothesis: Sequence[Decision],
    matcher: ItemMatcher | None = None,
) -> float:
    if not reference:
        return 1.0
    active = matcher if matcher is not None else TokenSetMatcher()
    matches = optimal_matches(
        [item.statement for item in reference],
        [item.statement for item in hypothesis],
        active,
    )
    return len(matches) / len(reference)


def minutes_sentences(minutes: Minutes) -> tuple[str, ...]:
    fragments: list[str] = []
    fragments.extend(_split_sentences(minutes.abstract))
    for topic in minutes.topics:
        fragments.extend(_split_sentences(topic.summary))
        fragments.extend(topic.key_points)
    for decision in minutes.decisions:
        fragments.append(decision.statement)
        if decision.rationale:
            fragments.extend(_split_sentences(decision.rationale))
    fragments.extend(action.description for action in minutes.actions)
    fragments.extend(question.question for question in minutes.open_questions)
    return tuple(fragment.strip() for fragment in fragments if fragment.strip())


def grounding_score(
    minutes: Minutes,
    transcript: Transcript,
    normalizer: TextNormalizer | None = None,
    support_threshold: float = DEFAULT_SUPPORT_THRESHOLD,
) -> float:
    active = normalizer if normalizer is not None else BasicNormalizer()
    supported_vocabulary = set(active.normalize(transcript.text).split())
    sentences = minutes_sentences(minutes)
    scored = 0
    supported = 0
    for sentence in sentences:
        content = content_words(active.normalize(sentence))
        if not content:
            continue
        scored += 1
        covered = sum(1 for token in content if token in supported_vocabulary)
        if covered / len(content) >= support_threshold:
            supported += 1
    return supported / scored if scored else 1.0


def hallucination_rate(minutes: Minutes, transcript: Transcript) -> float:
    vocabulary = _surface_vocabulary(transcript.text)
    mentions = _extracted_mentions(minutes)
    if not mentions:
        return 0.0
    unsupported = sum(1 for mention in mentions if not _is_supported(mention, vocabulary))
    return unsupported / len(mentions)


def content_words(normalized_text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in normalized_text.split()
        if token not in _STOPWORDS
        and (token.isdigit() or len(remove_diacritics(token)) >= MINIMUM_CONTENT_WORD_LENGTH)
    )


_JUDGE_SYSTEM_PROMPT = (
    "You are a strict meeting-minutes examiner. Score the minutes against the transcript only. "
    "Never reward fluency, length or style. Any statement absent from the transcript lowers "
    "faithfulness. Answer with a single JSON object and nothing else, using integer scores from "
    "1 (unusable) to 5 (flawless) for the keys coverage, faithfulness, actionability and structure."
)

_JUDGE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "coverage": {"type": "integer", "minimum": 1, "maximum": 5},
        "faithfulness": {"type": "integer", "minimum": 1, "maximum": 5},
        "actionability": {"type": "integer", "minimum": 1, "maximum": 5},
        "structure": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["coverage", "faithfulness", "actionability", "structure"],
}

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_RUBRIC_FIELDS = ("coverage", "faithfulness", "actionability", "structure")


def _judge_user_prompt(minutes: Minutes, transcript: Transcript, max_characters: int) -> str:
    sentences = "\n".join(f"- {sentence}" for sentence in minutes_sentences(minutes))
    excerpt = transcript.text[:max_characters]
    return f"TRANSCRIPT:\n{excerpt}\n\nMINUTES:\ntitle: {minutes.title}\n{sentences}"


def _parse_rubric_scores(response: str) -> RubricScores:
    match = _JSON_OBJECT.search(response)
    if match is None:
        raise SummarizationError(f"judge response is not JSON: {response[:200]}")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise SummarizationError(f"judge response is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise SummarizationError("judge response must be a JSON object")
    missing = [field for field in _RUBRIC_FIELDS if field not in payload]
    if missing:
        raise SummarizationError(f"judge response is missing keys: {missing}")
    values = {field: _clamped_score(payload[field]) for field in _RUBRIC_FIELDS}
    return RubricScores(**values)


def _clamped_score(value: object) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise SummarizationError(f"judge score is not numeric: {value!r}") from error
    return min(5.0, max(1.0, numeric))


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT.split(text) if sentence.strip()]


def _precision_recall_f1(
    matched: int,
    reference_count: int,
    hypothesis_count: int,
) -> tuple[float, float, float]:
    precision = matched / hypothesis_count if hypothesis_count else (1.0 if reference_count == 0 else 0.0)
    recall = matched / reference_count if reference_count else (1.0 if hypothesis_count == 0 else 0.0)
    if precision + recall == 0.0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def _normalized_owner(owner: str | None) -> str:
    return remove_diacritics((owner or "").strip().casefold())


def _surface_vocabulary(text: str) -> frozenset[str]:
    tokens = {remove_diacritics(token.casefold()) for token in _WORD.findall(text)}
    tokens.update(number.replace(",", "").replace(".", "") for number in _NUMBER.findall(text))
    return frozenset(tokens)


def _extracted_mentions(minutes: Minutes) -> tuple[str, ...]:
    mentions: list[str] = []
    for sentence in minutes_sentences(minutes):
        mentions.extend(_NUMBER.findall(sentence))
        mentions.extend(
            match.group(0)
            for match in _CAPITALISED_RUN.finditer(sentence)
            if match.start() > 0 or " " in match.group(0)
        )
    return tuple(mentions)


def _is_supported(mention: str, vocabulary: frozenset[str]) -> bool:
    if _NUMBER.fullmatch(mention):
        return mention.replace(",", "").replace(".", "") in vocabulary
    tokens = [remove_diacritics(token.casefold()) for token in _WORD.findall(mention)]
    return all(token in vocabulary for token in tokens) if tokens else True


def _ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()
