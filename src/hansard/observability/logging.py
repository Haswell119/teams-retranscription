from __future__ import annotations

import logging
import re
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final, cast

import structlog
from pydantic import SecretBytes, SecretStr
from structlog.typing import EventDict, FilteringBoundLogger, Processor, WrappedLogger

from hansard.config import RuntimeSettings

REDACTED: Final[str] = "***"
DEFAULT_LOG_LEVEL: Final[int] = logging.INFO
MAXIMUM_REDACTION_DEPTH: Final[int] = 4

SECRET_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"pass(word|phrase)?|secret|token|credential|authoriz|authoris|cookie|bearer|signature"
    r"|(^|[^a-z])keys?([^a-z]|$)",
    re.IGNORECASE,
)

CONTENT_FIELDS: Final[frozenset[str]] = frozenset({"text", "transcript", "body", "quote"})

StageLogger = FilteringBoundLogger


def log_level_number(name: str) -> int:
    return logging.getLevelNamesMapping().get(name.strip().upper(), DEFAULT_LOG_LEVEL)


def is_secret_name(name: str) -> bool:
    return SECRET_NAME_PATTERN.search(name) is not None


def redact_secrets(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    return {name: _redacted(name, value, 0) for name, value in event_dict.items()}


def content_elider(preview_characters: int = 0) -> Processor:
    def elide(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
        for name in CONTENT_FIELDS.intersection(event_dict):
            event_dict[name] = _elided(event_dict[name], preview_characters)
        return event_dict

    return elide


def get_logger(name: str) -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, structlog.wrap_logger(logging.getLogger(name)))


def configure_logging(settings: RuntimeSettings, content_preview_characters: int = 0) -> None:
    level = log_level_number(settings.log_level)
    shared = _shared_processors(content_preview_characters)
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *_renderers(settings.log_format),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


@contextmanager
def stage_span(logger: FilteringBoundLogger, stage: str, **fields: Any) -> Iterator[dict[str, float]]:
    started = time.perf_counter()
    measurements: dict[str, float] = {}
    logger.debug("stage.started", stage=stage, **fields)
    try:
        yield measurements
    except Exception as error:
        logger.warning(
            "stage.failed",
            stage=stage,
            duration_seconds=_elapsed_since(started),
            error=type(error).__name__,
            **fields,
        )
        raise
    logger.info(
        "stage.completed",
        stage=stage,
        duration_seconds=_elapsed_since(started),
        **{**fields, **measurements},
    )


def _shared_processors(content_preview_characters: int) -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        redact_secrets,
        content_elider(content_preview_characters),
    ]


def _renderers(log_format: str) -> list[Processor]:
    if log_format == "console":
        return [structlog.dev.ConsoleRenderer(colors=False)]
    return [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]


def _redacted(name: str, value: Any, depth: int) -> Any:
    if isinstance(value, SecretStr | SecretBytes):
        return REDACTED
    if is_secret_name(name):
        return REDACTED
    if depth >= MAXIMUM_REDACTION_DEPTH:
        return value
    if isinstance(value, Mapping):
        return {inner: _redacted(str(inner), item, depth + 1) for inner, item in value.items()}
    if isinstance(value, list):
        return [_redacted(name, item, depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_redacted(name, item, depth + 1) for item in value)
    return value


def _elided(value: Any, preview_characters: int) -> str:
    text = value if isinstance(value, str) else str(value)
    if preview_characters <= 0:
        return f"<elided {len(text)} characters>"
    if len(text) <= preview_characters:
        return text
    return f"{text[:preview_characters]}… <{len(text)} characters>"


def _elapsed_since(started: float) -> float:
    return round(time.perf_counter() - started, 3)
