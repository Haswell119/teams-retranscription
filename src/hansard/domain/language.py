from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

MIXED = "mixed"
UNDETERMINED = "und"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "fr")
MINORITY_SHARE = 0.10
MINORITY_SECONDS = 20.0


def normalise_tag(tag: str | None) -> str | None:
    if tag is None:
        return None
    cleaned = tag.strip().replace("_", "-").lower()
    if not cleaned:
        return None
    if cleaned in {MIXED, "multi", "multilingual", "bilingual", "mixte"}:
        return MIXED
    if cleaned in {"auto", "detect", "automatic"}:
        return None
    primary = cleaned.split("-")[0]
    return primary or None


def is_mixed_tag(tag: str | None) -> bool:
    return normalise_tag(tag) == MIXED


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    shares: Mapping[str, float]
    seconds: Mapping[str, float]

    @property
    def languages(self) -> tuple[str, ...]:
        ranked = sorted(self.shares.items(), key=lambda item: (-item[1], item[0]))
        return tuple(tag for tag, _ in ranked)

    @property
    def dominant(self) -> str | None:
        ranked = self.languages
        return ranked[0] if ranked else None

    @property
    def secondary(self) -> tuple[str, ...]:
        return self.languages[1:]

    @property
    def is_mixed(self) -> bool:
        return len(self.significant) > 1

    @property
    def significant(self) -> tuple[str, ...]:
        return tuple(tag for tag in self.languages if tag != UNDETERMINED and self._is_substantial(tag))

    def _is_substantial(self, tag: str) -> bool:
        return self.shares.get(tag, 0.0) >= MINORITY_SHARE or self.seconds.get(tag, 0.0) >= MINORITY_SECONDS

    @property
    def tag(self) -> str | None:
        significant = self.significant
        if len(significant) > 1:
            return MIXED
        if significant:
            return significant[0]
        return self.dominant

    def share_of(self, tag: str) -> float:
        return self.shares.get(tag, 0.0)


EMPTY_PROFILE = LanguageProfile(shares={}, seconds={})


def profile_from_counts(counts: Mapping[str, float], seconds: Mapping[str, float]) -> LanguageProfile:
    total = sum(counts.values())
    if total <= 0:
        return EMPTY_PROFILE
    shares = {tag: value / total for tag, value in counts.items() if value > 0}
    return LanguageProfile(shares=shares, seconds=dict(seconds))


def resolve_meeting_language(*candidates: str | None) -> str | None:
    for candidate in candidates:
        resolved = normalise_tag(candidate)
        if resolved is not None:
            return resolved
    return None


def languages_of(tag: str | None) -> tuple[str, ...]:
    resolved = normalise_tag(tag)
    if resolved is None or resolved == MIXED:
        return SUPPORTED_LANGUAGES
    return (resolved,)


def merge_tags(tags: Iterable[str | None]) -> str | None:
    seen: list[str] = []
    for tag in tags:
        resolved = normalise_tag(tag)
        if resolved is None:
            continue
        if resolved == MIXED:
            return MIXED
        if resolved not in seen:
            seen.append(resolved)
    if len(seen) > 1:
        return MIXED
    return seen[0] if seen else None
