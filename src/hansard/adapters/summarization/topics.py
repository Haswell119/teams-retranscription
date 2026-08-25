from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from hansard.adapters.summarization.text import (
    content_tokens,
    lexical_stem,
    resolve_language,
)
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript

TITLE_SEPARATOR = ", "


@dataclass(frozen=True, slots=True)
class TopicOptions:
    pseudo_sentence_tokens: int = 20
    block_size: int = 6
    smoothing_width: int = 2
    smoothing_passes: int = 1
    cutoff_factor: float = 0.5
    minimum_duration: float = 90.0
    minimum_utterances: int = 3
    max_topics: int = 12
    keywords_per_topic: int = 4
    speaker_snap_distance: int = 2
    adaptive: bool = True


@dataclass(frozen=True, slots=True)
class TopicSegment:
    index: int
    span: TimeSpan
    first_utterance: int
    last_utterance: int
    keywords: tuple[str, ...]
    title: str

    @property
    def utterance_indices(self) -> range:
        return range(self.first_utterance, self.last_utterance + 1)


@dataclass(frozen=True, slots=True)
class _TokenStream:
    stems: tuple[str, ...]
    surfaces: tuple[str, ...]
    utterances: tuple[int, ...]


def _token_stream(transcript: Transcript, language: str) -> _TokenStream:
    stems: list[str] = []
    surfaces: list[str] = []
    owners: list[int] = []
    for index, utterance in enumerate(transcript.utterances):
        for token in content_tokens(utterance.text, language):
            stems.append(lexical_stem(token, language))
            surfaces.append(token)
            owners.append(index)
    return _TokenStream(tuple(stems), tuple(surfaces), tuple(owners))


def _count_matrix(stems: Sequence[str], width: int) -> tuple[np.ndarray, int]:
    vocabulary = {term: position for position, term in enumerate(sorted(set(stems)))}
    rows = len(stems) // width
    matrix = np.zeros((rows, len(vocabulary)), dtype=np.float32)
    for row in range(rows):
        for term in stems[row * width : (row + 1) * width]:
            matrix[row, vocabulary[term]] += 1.0
    return matrix, rows


def _block_similarities(matrix: np.ndarray, block_size: int) -> np.ndarray:
    rows = matrix.shape[0]
    cumulative = np.vstack([np.zeros((1, matrix.shape[1]), dtype=np.float32), np.cumsum(matrix, axis=0)])
    scores = np.zeros(max(rows - 1, 0), dtype=np.float32)
    for gap in range(rows - 1):
        left_start = max(0, gap + 1 - block_size)
        right_end = min(rows, gap + 1 + block_size)
        left = cumulative[gap + 1] - cumulative[left_start]
        right = cumulative[right_end] - cumulative[gap + 1]
        norm = float(np.linalg.norm(left) * np.linalg.norm(right))
        scores[gap] = float(np.dot(left, right) / norm) if norm > 0.0 else 0.0
    return scores


def _smooth(scores: np.ndarray, width: int, passes: int) -> np.ndarray:
    if width <= 0 or scores.size == 0:
        return scores
    window = np.ones(2 * width + 1, dtype=np.float32)
    window /= window.sum()
    smoothed = scores
    for _ in range(max(passes, 0)):
        padded = np.pad(smoothed, width, mode="edge")
        smoothed = np.convolve(padded, window, mode="valid").astype(np.float32)
    return smoothed


def _depth_scores(scores: np.ndarray) -> np.ndarray:
    depths = np.zeros_like(scores)
    for gap in range(scores.size):
        left = gap
        while left > 0 and scores[left - 1] >= scores[left]:
            left -= 1
        right = gap
        while right + 1 < scores.size and scores[right + 1] >= scores[right]:
            right += 1
        depths[gap] = (scores[left] - scores[gap]) + (scores[right] - scores[gap])
    return depths


def _candidate_gaps(depths: np.ndarray, cutoff_factor: float) -> tuple[int, ...]:
    if depths.size == 0:
        return ()
    threshold = float(depths.mean() - cutoff_factor * depths.std())
    ranked = sorted(range(depths.size), key=lambda gap: float(depths[gap]), reverse=True)
    return tuple(gap for gap in ranked if float(depths[gap]) > max(threshold, 0.0))


def _snap_to_utterance(
    transcript: Transcript,
    target: int,
    distance: int,
) -> int:
    utterances = transcript.utterances
    best = target
    best_score = -1.0
    lower = max(1, target - distance)
    upper = min(len(utterances) - 1, target + distance)
    for candidate in range(lower, upper + 1):
        previous = utterances[candidate - 1]
        current = utterances[candidate]
        pause = max(0.0, current.span.start - previous.span.end)
        score = pause + (1.0 if current.speaker != previous.speaker else 0.0)
        if score > best_score:
            best_score = score
            best = candidate
    return best


def _accepted_boundaries(
    transcript: Transcript,
    candidates: Sequence[int],
    options: TopicOptions,
) -> tuple[int, ...]:
    utterances = transcript.utterances
    accepted: list[int] = []
    edges = [0, len(utterances)]
    for candidate in candidates:
        if len(accepted) + 1 >= options.max_topics:
            break
        if candidate in accepted:
            continue
        trial = sorted([*edges, candidate])
        viable = all(
            _segment_is_viable(transcript, trial[index], trial[index + 1], options)
            for index in range(len(trial) - 1)
        )
        if viable:
            accepted.append(candidate)
            edges = trial
    return tuple(sorted(accepted))


def _segment_is_viable(transcript: Transcript, start: int, stop: int, options: TopicOptions) -> bool:
    if stop - start < options.minimum_utterances:
        return False
    span = TimeSpan(transcript.utterances[start].span.start, transcript.utterances[stop - 1].span.end)
    return span.duration >= options.minimum_duration


MINIMUM_KEYWORD_LENGTH = 4


def _keywords(
    stream: _TokenStream,
    ranges: Sequence[tuple[int, int]],
    limit: int,
) -> tuple[tuple[str, ...], ...]:
    per_segment: list[dict[str, int]] = [{} for _ in ranges]
    surface: dict[str, dict[str, int]] = {}
    utterance_frequency: dict[str, set[int]] = {}
    for position, stem in enumerate(stream.stems):
        owner = stream.utterances[position]
        utterance_frequency.setdefault(stem, set()).add(owner)
        forms = surface.setdefault(stem, {})
        forms[stream.surfaces[position]] = forms.get(stream.surfaces[position], 0) + 1
        for index, (start, stop) in enumerate(ranges):
            if start <= owner < stop:
                per_segment[index][stem] = per_segment[index].get(stem, 0) + 1
                break
    total_utterances = len(set(stream.utterances)) or 1
    keywords: list[tuple[str, ...]] = []
    for counts in per_segment:
        scored = sorted(
            (
                (stem, count * float(np.log(1.0 + total_utterances / len(utterance_frequency[stem]))))
                for stem, count in counts.items()
                if not stem.isdigit() and len(stem) >= MINIMUM_KEYWORD_LENGTH
            ),
            key=lambda item: (-item[1], item[0]),
        )
        keywords.append(tuple(_surface_form(surface, stem) for stem, _ in scored[:limit]))
    return tuple(keywords)


def _surface_form(surface: dict[str, dict[str, int]], stem: str) -> str:
    forms = surface.get(stem)
    if not forms:
        return stem
    return max(forms.items(), key=lambda item: (item[1], -len(item[0])))[0]


def _title_from(keywords: Sequence[str], position: int) -> str:
    if not keywords:
        return f"Topic {position}"
    joined = TITLE_SEPARATOR.join(keywords[:3])
    return joined[0].upper() + joined[1:]


def _ranges_from(boundaries: Sequence[int], count: int) -> tuple[tuple[int, int], ...]:
    edges = [0, *boundaries, count]
    return tuple((edges[index], edges[index + 1]) for index in range(len(edges) - 1))


def _adapted(options: TopicOptions, token_count: int, duration: float) -> TopicOptions:
    if not options.adaptive:
        return options
    width = min(max(round(token_count / 60), 6), options.pseudo_sentence_tokens)
    block = min(max(round(token_count / (width * 6)), 3), options.block_size)
    minimum = min(options.minimum_duration, duration / 4.0) if duration > 0.0 else options.minimum_duration
    return replace(
        options,
        pseudo_sentence_tokens=width,
        block_size=block,
        minimum_duration=minimum,
    )


def segment_topics(
    transcript: Transcript,
    language: str | None = None,
    options: TopicOptions | None = None,
) -> tuple[TopicSegment, ...]:
    active = options or TopicOptions()
    resolved = resolve_language(language, transcript.language)
    utterances = transcript.utterances
    if not utterances:
        return ()
    stream = _token_stream(transcript, resolved)
    duration = utterances[-1].span.end - utterances[0].span.start
    active = _adapted(active, len(stream.stems), duration)
    boundaries = _boundaries(transcript, stream, active)
    ranges = _ranges_from(boundaries, len(utterances))
    keywords = _keywords(stream, ranges, active.keywords_per_topic)
    return tuple(
        TopicSegment(
            index=index,
            span=TimeSpan(utterances[start].span.start, utterances[stop - 1].span.end),
            first_utterance=start,
            last_utterance=stop - 1,
            keywords=terms,
            title=_title_from(terms, index + 1),
        )
        for index, ((start, stop), terms) in enumerate(zip(ranges, keywords, strict=True))
    )


def _boundaries(transcript: Transcript, stream: _TokenStream, options: TopicOptions) -> tuple[int, ...]:
    width = max(options.pseudo_sentence_tokens, 1)
    if len(stream.stems) < width * (options.block_size + 1):
        return ()
    matrix, rows = _count_matrix(stream.stems, width)
    if rows < 2:
        return ()
    scores = _smooth(
        _block_similarities(matrix, options.block_size),
        options.smoothing_width,
        options.smoothing_passes,
    )
    depths = _depth_scores(scores)
    candidates: list[int] = []
    for gap in _candidate_gaps(depths, options.cutoff_factor):
        position = min((gap + 1) * width, len(stream.utterances) - 1)
        utterance = stream.utterances[position]
        snapped = _snap_to_utterance(transcript, utterance, options.speaker_snap_distance)
        if snapped > 0 and snapped < len(transcript.utterances) and snapped not in candidates:
            candidates.append(snapped)
    return _accepted_boundaries(transcript, candidates, options)
