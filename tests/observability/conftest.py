from __future__ import annotations

import logging

import pytest
import structlog


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    yield
    structlog.reset_defaults()
    root.handlers = handlers
    root.setLevel(level)
