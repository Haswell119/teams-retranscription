from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from sample_meeting import (
    french_context,
    french_minutes,
    french_transcript,
    sample_context,
    sample_minutes,
    sample_transcript,
)

GOLDEN_DIRECTORY = Path(__file__).parent / "golden"
UPDATE_ENVIRONMENT_VARIABLE = "HANSARD_UPDATE_GOLDEN"


@pytest.fixture
def context():
    return sample_context()


@pytest.fixture
def transcript():
    return sample_transcript()


@pytest.fixture
def minutes():
    return sample_minutes()


@pytest.fixture
def fr_context():
    return french_context()


@pytest.fixture
def fr_transcript():
    return french_transcript()


@pytest.fixture
def fr_minutes():
    return french_minutes()


@pytest.fixture
def assert_golden() -> Callable[[str, str], None]:
    def compare(name: str, content: str) -> None:
        path = GOLDEN_DIRECTORY / name
        if os.environ.get(UPDATE_ENVIRONMENT_VARIABLE):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        assert path.exists(), f"missing golden file {path}"
        assert content == path.read_text(encoding="utf-8")

    return compare
