from __future__ import annotations

from itertools import pairwise

import pytest

from hansard.adapters.summarization.chunking import (
    ChunkOptions,
    estimate_tokens,
    plan_chunks,
    prepare_entries,
)
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance


def _long_transcript(turns: int = 40, pause_every: int = 7) -> Transcript:
    utterances = []
    cursor = 0.0
    for index in range(turns):
        cursor += 4.0 if index % pause_every == 0 else 0.2
        text = (
            f"Point number {index} about the release, the locale files and the translation backlog "
            "that the team still has to review before the freeze."
        )
        utterances.append(Utterance(span=TimeSpan(cursor, cursor + 6.0), text=text, speaker=f"S{index % 3}"))
        cursor += 6.0
    return Transcript(utterances=tuple(utterances), language="en", audio_duration=cursor)


def test_token_estimator_is_conservative_for_both_languages():
    english = estimate_tokens("the quick brown fox jumps over the lazy dog", "en")
    french = estimate_tokens("le renard brun rapide saute par dessus le chien paresseux", "fr")
    assert 9 <= english <= 16
    assert 10 <= french <= 22
    assert estimate_tokens("   ", "fr") == 0


def test_chunks_never_split_inside_an_utterance():
    transcript = _long_transcript()
    plan = plan_chunks(transcript, ChunkOptions(max_tokens=300))
    assert len(plan.chunks) > 1
    texts = [entry.utterance.text for entry in plan.entries]
    for chunk in plan.chunks:
        for entry in chunk.entries:
            assert entry.utterance.text in texts


def test_chunks_stay_within_budget_and_cover_every_utterance():
    transcript = _long_transcript()
    options = ChunkOptions(max_tokens=300)
    plan = plan_chunks(transcript, options)
    covered = [entry.reference for chunk in plan.chunks for entry in chunk.body]
    assert covered == sorted(covered)
    assert covered == list(range(len(plan.entries)))
    for chunk in plan.chunks[:-1]:
        assert chunk.estimated_tokens <= options.budget


def test_chunks_carry_overlap_from_the_previous_chunk():
    plan = plan_chunks(_long_transcript(), ChunkOptions(max_tokens=400))
    assert all(chunk.overlap_count > 0 for chunk in plan.chunks[1:])
    for previous, current in pairwise(plan.chunks):
        assert current.overlap[0].reference <= previous.body[-1].reference


def test_chunk_spans_stay_accurate():
    plan = plan_chunks(_long_transcript(), ChunkOptions(max_tokens=300))
    for chunk in plan.chunks:
        assert chunk.span.start == chunk.entries[0].span.start
        assert chunk.body_span.start == chunk.body[0].span.start
        assert chunk.body_span.end <= chunk.span.end


def test_boundaries_prefer_long_pauses():
    utterances = []
    cursor = 0.0
    for index in range(12):
        gap = 30.0 if index == 6 else 0.5
        cursor += gap
        utterances.append(
            Utterance(
                span=TimeSpan(cursor, cursor + 5.0),
                text=(
                    f"Sentence {index} carries enough words in it to weigh a fair amount in the "
                    "token budget of the planner, or so the speaker claimed."
                ),
                speaker="A" if index < 6 else "B",
            )
        )
        cursor += 5.0
    transcript = Transcript(utterances=tuple(utterances), language="en")
    plan = plan_chunks(transcript, ChunkOptions(max_tokens=280, overlap_ratio=0.0))
    assert plan.chunks[1].body[0].reference == 6


def test_oversized_utterance_is_split_on_sentence_boundaries():
    monologue = " ".join(f"This is filler sentence {index} of the monologue." for index in range(120))
    transcript = Transcript(
        utterances=(Utterance(span=TimeSpan(0.0, 600.0), text=monologue, speaker="A"),),
        language="en",
    )
    entries = prepare_entries(transcript, ChunkOptions(max_tokens=300), "en")
    assert len(entries) > 1
    assert entries[0].span.start == 0.0
    assert entries[-1].span.end == pytest.approx(600.0, abs=1.0)
    for previous, current in pairwise(entries):
        assert current.span.start >= previous.span.start
        assert current.utterance.text.strip()


def test_empty_transcript_produces_no_chunks():
    plan = plan_chunks(Transcript(), ChunkOptions())
    assert plan.chunks == ()
    assert plan.entries == ()
