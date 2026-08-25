from __future__ import annotations

import httpx
import pytest

from hansard.adapters.summarization import registry
from hansard.adapters.summarization.extractive import ExtractiveMinutesWriter
from hansard.adapters.summarization.llm_writer import LlmMinutesWriter
from hansard.adapters.summarization.registry import (
    ENGINE_ENVIRONMENT_VARIABLE,
    available_minutes_writers,
    build_minutes_writer,
    chunk_budget,
    resolve_engine,
)
from hansard.config import MinutesSettings
from hansard.domain.errors import ConfigurationError
from hansard.ports.summarization import MinutesWriter


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    monkeypatch.delenv(ENGINE_ENVIRONMENT_VARIABLE, raising=False)


def test_available_engines():
    assert available_minutes_writers() == ("auto", "extractive", "llm")


def test_default_engine_is_auto():
    assert resolve_engine(MinutesSettings()) == "auto"


def test_disabled_minutes_never_reach_the_network():
    writer = build_minutes_writer(MinutesSettings(enabled=False))
    assert isinstance(writer, ExtractiveMinutesWriter)


def test_engine_can_be_selected_by_environment(monkeypatch):
    monkeypatch.setenv(ENGINE_ENVIRONMENT_VARIABLE, "llm")
    writer = build_minutes_writer(MinutesSettings())
    assert isinstance(writer, LlmMinutesWriter)
    assert isinstance(writer, MinutesWriter)


def test_extractive_engine_is_selectable(monkeypatch):
    monkeypatch.setenv(ENGINE_ENVIRONMENT_VARIABLE, "extractive")
    assert build_minutes_writer(MinutesSettings()).name == "extractive"


def test_unknown_engine_is_refused(monkeypatch):
    monkeypatch.setenv(ENGINE_ENVIRONMENT_VARIABLE, "gpt5")
    with pytest.raises(ConfigurationError, match="unknown minutes engine"):
        build_minutes_writer(MinutesSettings())


def test_auto_uses_the_llm_when_the_endpoint_answers(monkeypatch):
    monkeypatch.setattr(registry.OpenAiCompatibleGenerator, "probe", lambda self: True)
    assert isinstance(build_minutes_writer(MinutesSettings()), LlmMinutesWriter)


def test_auto_falls_back_to_extractive_when_the_endpoint_is_silent(monkeypatch):
    monkeypatch.setattr(registry.OpenAiCompatibleGenerator, "probe", lambda self: False)
    assert isinstance(build_minutes_writer(MinutesSettings()), ExtractiveMinutesWriter)


def test_auto_probe_is_offline_safe():
    settings = MinutesSettings(endpoint="http://127.0.0.1:9/v1")
    writer = build_minutes_writer(settings)
    assert isinstance(writer, ExtractiveMinutesWriter)


def test_chunk_budget_respects_the_context_window():
    settings = MinutesSettings(context_tokens=8_192, max_output_tokens=4_096, chunk_tokens=8_192)
    assert chunk_budget(settings) == 8_192 - 4_096 - 1_024
    assert chunk_budget(MinutesSettings()) == 8_192


def test_generator_is_configured_from_settings():
    settings = MinutesSettings(endpoint="http://gpu-box:8000/v1", model_id="mistral-small", temperature=0.1)
    generator = registry.build_generator(settings)
    assert generator.endpoint == "http://gpu-box:8000/v1"
    assert generator.model_id == "mistral-small"
    assert generator.temperature == pytest.approx(0.1)
    assert isinstance(generator.timeout, httpx.Timeout)


def test_citation_and_speaking_time_switches_reach_the_writer(monkeypatch):
    monkeypatch.setenv(ENGINE_ENVIRONMENT_VARIABLE, "extractive")
    settings = MinutesSettings(include_citations=False, include_speaking_time=False, language="fr")
    writer = build_minutes_writer(settings)
    assert isinstance(writer, ExtractiveMinutesWriter)
    assert writer.include_citations is False
    assert writer.include_speaking_time is False
    assert writer.language == "fr"
