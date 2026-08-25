from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from hansard.adapters.summarization.citations import utterance_sentences
from hansard.adapters.summarization.text import resolve_language
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.rendering.timecode import TimestampStyle, format_timestamp

CHARACTERS_PER_TOKEN: Mapping[str, float] = {"en": 3.9, "fr": 3.3}
DEFAULT_CHARACTERS_PER_TOKEN = 3.4
TOKENS_PER_WORD = 1.15
LINE_OVERHEAD_TOKENS = 8
MINIMUM_CHUNK_TOKENS = 256


def estimate_tokens(text: str, language: str = "en") -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    density = CHARACTERS_PER_TOKEN.get(language, DEFAULT_CHARACTERS_PER_TOKEN)
    by_characters = len(stripped) / density
    by_words = len(stripped.split()) * TOKENS_PER_WORD
    return math.ceil(max(by_characters, by_words))


@dataclass(frozen=True, slots=True)
class ChunkOptions:
    max_tokens: int = 8_192
    overlap_ratio: float = 0.08
    max_overlap_tokens: int = 512
    long_pause_seconds: float = 2.5
    boundary_lookback_ratio: float = 0.2

    @property
    def budget(self) -> int:
        return max(MINIMUM_CHUNK_TOKENS, self.max_tokens)

    @property
    def overlap_budget(self) -> int:
        ratio_budget = int(self.budget * min(max(self.overlap_ratio, 0.0), 0.25))
        return min(self.max_overlap_tokens, ratio_budget)


@dataclass(frozen=True, slots=True)
class ChunkEntry:
    reference: int
    utterance: Utterance
    tokens: int

    @property
    def span(self) -> TimeSpan:
        return self.utterance.span

    @property
    def speaker(self) -> str:
        return self.utterance.speaker

    def render(self) -> str:
        stamp = format_timestamp(self.utterance.span.start, TimestampStyle.CLOCK)
        return f"[{self.reference}] {stamp} {self.utterance.speaker}: {self.utterance.text.strip()}"


@dataclass(frozen=True, slots=True)
class TranscriptChunk:
    index: int
    entries: tuple[ChunkEntry, ...]
    overlap_count: int
    span: TimeSpan
    body_span: TimeSpan
    estimated_tokens: int

    @property
    def body(self) -> tuple[ChunkEntry, ...]:
        return self.entries[self.overlap_count :]

    @property
    def overlap(self) -> tuple[ChunkEntry, ...]:
        return self.entries[: self.overlap_count]

    @property
    def references(self) -> tuple[int, ...]:
        return tuple(entry.reference for entry in self.entries)

    def render(self) -> str:
        return "\n".join(entry.render() for entry in self.entries)


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    chunks: tuple[TranscriptChunk, ...]
    entries: tuple[ChunkEntry, ...]
    language: str

    def entry(self, reference: int) -> ChunkEntry | None:
        if 0 <= reference < len(self.entries):
            return self.entries[reference]
        return None


def _entry_tokens(utterance: Utterance, language: str) -> int:
    return estimate_tokens(utterance.text, language) + LINE_OVERHEAD_TOKENS


def _split_oversized(utterance: Utterance, budget: int, language: str) -> tuple[Utterance, ...]:
    units = utterance_sentences(utterance, 0)
    if len(units) < 2:
        return (utterance,)
    parts: list[Utterance] = []
    current: list[str] = []
    start = utterance.span.start
    end = utterance.span.start
    cost = 0
    for unit in units:
        unit_cost = estimate_tokens(unit.text, language)
        if current and cost + unit_cost > budget:
            parts.append(
                replace(utterance, span=TimeSpan(start, max(start, end)), text=" ".join(current), words=())
            )
            current = []
            cost = 0
            start = unit.span.start
        current.append(unit.text)
        cost += unit_cost
        end = unit.span.end
    if current:
        parts.append(
            replace(utterance, span=TimeSpan(start, max(start, end)), text=" ".join(current), words=())
        )
    return tuple(parts)


def prepare_entries(transcript: Transcript, options: ChunkOptions, language: str) -> tuple[ChunkEntry, ...]:
    budget = options.budget - LINE_OVERHEAD_TOKENS
    entries: list[ChunkEntry] = []
    for utterance in transcript.utterances:
        if not utterance.text.strip():
            continue
        pieces = (
            (utterance,)
            if estimate_tokens(utterance.text, language) <= budget
            else _split_oversized(utterance, budget, language)
        )
        for piece in pieces:
            entries.append(
                ChunkEntry(
                    reference=len(entries),
                    utterance=piece,
                    tokens=_entry_tokens(piece, language),
                )
            )
    return tuple(entries)


def _follows_long_pause(entries: Sequence[ChunkEntry], position: int, pause_seconds: float) -> bool:
    if position <= 0 or position >= len(entries):
        return False
    return entries[position].span.start - entries[position - 1].span.end >= pause_seconds


def _changes_speaker(entries: Sequence[ChunkEntry], position: int) -> bool:
    if position <= 0 or position >= len(entries):
        return False
    return entries[position].speaker != entries[position - 1].speaker


def _preferred_split(
    entries: Sequence[ChunkEntry],
    start: int,
    limit: int,
    options: ChunkOptions,
) -> int:
    if limit - start <= 1:
        return limit
    lookback_tokens = int(options.budget * options.boundary_lookback_ratio)
    earliest = start + 1
    consumed = 0
    for position in range(limit - 1, earliest - 1, -1):
        consumed += entries[position].tokens
        if consumed > lookback_tokens:
            earliest = position + 1
            break
    for position in range(limit, earliest - 1, -1):
        if _follows_long_pause(entries, position, options.long_pause_seconds):
            return position
    for position in range(limit, earliest - 1, -1):
        if _changes_speaker(entries, position):
            return position
    return limit


def _overlap_start(entries: Sequence[ChunkEntry], split: int, options: ChunkOptions) -> int:
    if options.overlap_budget <= 0 or split <= 0:
        return split
    consumed = 0
    position = split
    while position > 0:
        cost = entries[position - 1].tokens
        if consumed + cost > options.overlap_budget:
            break
        consumed += cost
        position -= 1
    if position == split and entries[split - 1].tokens <= options.budget // 4:
        position = split - 1
    return max(position, 0)


def _chunk_from(entries: Sequence[ChunkEntry], overlap_count: int, index: int) -> TranscriptChunk:
    selected = tuple(entries)
    body = selected[overlap_count:] or selected
    return TranscriptChunk(
        index=index,
        entries=selected,
        overlap_count=overlap_count,
        span=TimeSpan(selected[0].span.start, max(entry.span.end for entry in selected)),
        body_span=TimeSpan(body[0].span.start, max(entry.span.end for entry in body)),
        estimated_tokens=sum(entry.tokens for entry in selected),
    )


def plan_chunks(
    transcript: Transcript,
    options: ChunkOptions | None = None,
    language: str | None = None,
) -> ChunkPlan:
    active = options or ChunkOptions()
    resolved = resolve_language(language, transcript.language)
    entries = prepare_entries(transcript, active, resolved)
    if not entries:
        return ChunkPlan(chunks=(), entries=(), language=resolved)
    chunks: list[TranscriptChunk] = []
    start = 0
    overlap_count = 0
    while start < len(entries):
        consumed = 0
        limit = start
        while limit < len(entries) and (consumed + entries[limit].tokens <= active.budget or limit == start):
            consumed += entries[limit].tokens
            limit += 1
        if limit >= len(entries):
            chunks.append(_chunk_from(entries[start:], overlap_count, len(chunks)))
            break
        split = _preferred_split(entries, start, limit, active)
        chunks.append(_chunk_from(entries[start:split], overlap_count, len(chunks)))
        resumed = _overlap_start(entries, split, active)
        overlap_count = split - resumed
        start = resumed
    return ChunkPlan(chunks=tuple(chunks), entries=entries, language=resolved)
