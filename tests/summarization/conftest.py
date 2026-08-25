from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from meetings import (
    MEETING_DATE,
    english_request,
    english_roster,
    english_transcript,
    french_request,
    french_roster,
    french_transcript,
)

from hansard.adapters.summarization.prompts import MAP_SCHEMA
from hansard.domain.errors import SummarizationError


class ScriptedGenerator:
    def __init__(self, map_answers: Sequence[object], reduce_answer: object | None = None) -> None:
        self.map_answers = list(map_answers)
        self.reduce_answer = reduce_answer
        self.prompts: list[tuple[str, str]] = []
        self.schemas: list[object] = []

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def context_tokens(self) -> int:
        return 32_768

    def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, object] | None) -> str:
        self.prompts.append((system, user))
        self.schemas.append(schema)
        if schema is MAP_SCHEMA:
            if not self.map_answers:
                raise SummarizationError("no scripted answer left")
            return _render(self.map_answers.pop(0))
        if self.reduce_answer is None:
            raise SummarizationError("no scripted consolidation answer")
        return _render(self.reduce_answer)


class UnreachableGenerator:
    @property
    def name(self) -> str:
        return "unreachable"

    @property
    def context_tokens(self) -> int:
        return 32_768

    def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, object] | None) -> str:
        raise SummarizationError("cannot reach the local model endpoint http://localhost:8080/v1")


def _render(answer: object) -> str:
    if isinstance(answer, str):
        return answer
    return json.dumps(answer, ensure_ascii=False)


@pytest.fixture
def meeting_date():
    return MEETING_DATE


@pytest.fixture
def fr_transcript():
    return french_transcript()


@pytest.fixture
def fr_roster():
    return french_roster()


@pytest.fixture
def fr_request():
    return french_request()


@pytest.fixture
def en_transcript():
    return english_transcript()


@pytest.fixture
def en_roster():
    return english_roster()


@pytest.fixture
def en_request():
    return english_request()
