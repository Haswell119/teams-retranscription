from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from hansard.domain.errors import ConfigurationError
from hansard.rendering.html import HtmlRenderer
from hansard.rendering.json_export import JsonRenderer
from hansard.rendering.markdown import MarkdownRenderer
from hansard.rendering.plaintext import PlainTextRenderer
from hansard.rendering.ports import AnyRenderer, MinutesRenderer, TranscriptRenderer
from hansard.rendering.subtitles import SubRipRenderer, WebVttRenderer

ItemT = TypeVar("ItemT")
RENDERER_SUBJECT = "output format"


class NamedRegistry(Generic[ItemT]):
    def __init__(self, subject: str) -> None:
        self._subject = subject
        self._items: dict[str, ItemT] = {}

    def register(self, name: str, item: ItemT) -> None:
        self._items[name] = item

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))

    def get(self, name: str) -> ItemT:
        item = self._items.get(name)
        if item is None:
            raise ConfigurationError(f"unknown {self._subject} '{name}', available: {self.names()}")
        return item

    def matching(self, predicate: Callable[[ItemT], bool]) -> tuple[str, ...]:
        return tuple(sorted(name for name, item in self._items.items() if predicate(item)))

    def __contains__(self, name: str) -> bool:
        return name in self._items


_RENDERERS: NamedRegistry[AnyRenderer] = NamedRegistry(RENDERER_SUBJECT)


def register_renderer(renderer: AnyRenderer) -> None:
    _RENDERERS.register(renderer.name, renderer)


def available_formats() -> tuple[str, ...]:
    return _RENDERERS.names()


def renderer_for(name: str) -> AnyRenderer:
    return _RENDERERS.get(name)


def transcript_renderer_for(name: str) -> TranscriptRenderer:
    renderer = renderer_for(name)
    if not isinstance(renderer, TranscriptRenderer):
        raise ConfigurationError(f"{RENDERER_SUBJECT} '{name}' does not render transcripts")
    return renderer


def minutes_renderer_for(name: str) -> MinutesRenderer:
    renderer = renderer_for(name)
    if not isinstance(renderer, MinutesRenderer):
        raise ConfigurationError(f"{RENDERER_SUBJECT} '{name}' does not render minutes")
    return renderer


def transcript_formats() -> tuple[str, ...]:
    return _RENDERERS.matching(lambda renderer: isinstance(renderer, TranscriptRenderer))


def minutes_formats() -> tuple[str, ...]:
    return _RENDERERS.matching(lambda renderer: isinstance(renderer, MinutesRenderer))


for _default in (
    MarkdownRenderer(),
    HtmlRenderer(),
    JsonRenderer(),
    WebVttRenderer(),
    SubRipRenderer(),
    PlainTextRenderer(),
):
    register_renderer(_default)
