from __future__ import annotations

from collections.abc import Callable, MutableMapping

from hansard.adapters.summarization.chunking import ChunkOptions
from hansard.adapters.summarization.extractive import ExtractiveMinutesWriter
from hansard.adapters.summarization.llm_writer import LlmMinutesWriter
from hansard.adapters.summarization.openai_compat import OpenAiCompatibleGenerator
from hansard.config import MinutesSettings
from hansard.domain.errors import ConfigurationError
from hansard.ports.summarization import MinutesWriter

MinutesWriterFactory = Callable[[MinutesSettings], MinutesWriter]

ENGINE_ENVIRONMENT_VARIABLE = "HANSARD_MINUTES__ENGINE"
DEFAULT_ENGINE = "auto"
DISABLED_ENGINE = "extractive"
PROMPT_OVERHEAD_TOKENS = 1_024
MINIMUM_CHUNK_TOKENS = 512

_FACTORIES: MutableMapping[str, MinutesWriterFactory] = {}


def register_minutes_writer(name: str, factory: MinutesWriterFactory) -> None:
    _FACTORIES[name] = factory


def available_minutes_writers() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def resolve_engine(settings: MinutesSettings) -> str:
    if not settings.enabled:
        return DISABLED_ENGINE
    configured = settings.engine.strip().lower()
    return configured or DEFAULT_ENGINE


def chunk_budget(settings: MinutesSettings) -> int:
    available = settings.context_tokens - settings.max_output_tokens - PROMPT_OVERHEAD_TOKENS
    return max(MINIMUM_CHUNK_TOKENS, min(settings.chunk_tokens, available))


def build_generator(settings: MinutesSettings) -> OpenAiCompatibleGenerator:
    return OpenAiCompatibleGenerator(
        endpoint=settings.endpoint,
        model_id=settings.model_id,
        api_key=settings.api_key,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        context_window=settings.context_tokens,
    )


def build_extractive_writer(settings: MinutesSettings) -> MinutesWriter:
    return ExtractiveMinutesWriter(
        language=settings.language,
        include_citations=settings.include_citations,
        include_speaking_time=settings.include_speaking_time,
    )


def build_llm_writer(settings: MinutesSettings) -> MinutesWriter:
    extractive = ExtractiveMinutesWriter(
        language=settings.language,
        include_citations=settings.include_citations,
        include_speaking_time=settings.include_speaking_time,
    )
    return LlmMinutesWriter(
        generator=build_generator(settings),
        fallback=extractive,
        chunk_options=ChunkOptions(max_tokens=chunk_budget(settings)),
        language=settings.language,
        max_reduce_tokens=settings.max_output_tokens,
        include_citations=settings.include_citations,
        include_speaking_time=settings.include_speaking_time,
    )


def build_automatic_writer(settings: MinutesSettings) -> MinutesWriter:
    if build_generator(settings).probe():
        return build_llm_writer(settings)
    return build_extractive_writer(settings)


def build_minutes_writer(settings: MinutesSettings) -> MinutesWriter:
    engine = resolve_engine(settings)
    factory = _FACTORIES.get(engine)
    if factory is None:
        raise ConfigurationError(
            f"unknown minutes engine '{engine}', available: {available_minutes_writers()}"
        )
    return factory(settings)


register_minutes_writer("extractive", build_extractive_writer)
register_minutes_writer("llm", build_llm_writer)
register_minutes_writer("auto", build_automatic_writer)
