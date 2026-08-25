from __future__ import annotations

import math
from dataclasses import dataclass

from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Word

_SENTENCEPIECE_BOUNDARY = "▁"


@dataclass(frozen=True, slots=True)
class TokenStream:
    tokens: tuple[str, ...]
    timestamps: tuple[float, ...]
    logprobs: tuple[float, ...]


def _starts_word(token: str) -> bool:
    return token.startswith(_SENTENCEPIECE_BOUNDARY) or token.startswith(" ")


def _clean(token: str) -> str:
    return token.replace(_SENTENCEPIECE_BOUNDARY, " ")


def _confidence(logprobs: list[float]) -> float:
    if not logprobs:
        return 1.0
    return float(min(1.0, math.exp(sum(logprobs) / len(logprobs))))


def tokens_to_words(stream: TokenStream, span: TimeSpan) -> tuple[Word, ...]:
    if not stream.tokens or not stream.timestamps:
        return ()
    groups: list[tuple[list[str], list[float], list[float]]] = []
    for index, token in enumerate(stream.tokens):
        piece = _clean(token)
        if not piece.strip():
            continue
        timestamp = stream.timestamps[index] if index < len(stream.timestamps) else span.start
        logprob = stream.logprobs[index] if index < len(stream.logprobs) else 0.0
        if not groups or _starts_word(token):
            groups.append(([piece], [timestamp], [logprob]))
        else:
            groups[-1][0].append(piece)
            groups[-1][1].append(timestamp)
            groups[-1][2].append(logprob)
    words: list[Word] = []
    for position, (pieces, times, logprobs) in enumerate(groups):
        text = "".join(pieces).strip()
        if not text:
            continue
        start = min(times) + span.start
        following = groups[position + 1][1] if position + 1 < len(groups) else None
        end = (min(following) + span.start) if following else span.end
        words.append(
            Word(
                text=text,
                span=TimeSpan(min(start, span.end), min(max(end, start), span.end)),
                confidence=_confidence(logprobs),
            )
        )
    return tuple(words)


def words_to_text(words: tuple[Word, ...]) -> str:
    return " ".join(word.text for word in words).strip()
