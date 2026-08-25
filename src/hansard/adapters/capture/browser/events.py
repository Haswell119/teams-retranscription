from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Any, Final, TypeAlias

from hansard.domain.speakers import UNKNOWN_SPEAKER, ActiveSpeakerObservation, Participant, Roster
from hansard.domain.timespan import TimeSpan

ANONYMOUS_JOIN_DISABLED: Final[int] = 5723
JOIN_REQUEST_DENIED: Final[int] = 5854
MEETING_ENDED: Final[int] = 5000
PARTICIPANT_REMOVED: Final[int] = 5300

REFUSAL_SUB_CODES: Final[frozenset[int]] = frozenset({ANONYMOUS_JOIN_DISABLED, JOIN_REQUEST_DENIED})
TERMINATION_SUB_CODES: Final[frozenset[int]] = frozenset({MEETING_ENDED, PARTICIPANT_REMOVED})

SUB_CODE_EXPLANATIONS: Final[dict[int, str]] = {
    ANONYMOUS_JOIN_DISABLED: (
        "anonymous join is disabled by tenant policy (subCode 5723); "
        "an admin must allow anonymous participants or invite the bot with an account"
    ),
    JOIN_REQUEST_DENIED: "a meeting participant denied the join request from the lobby (subCode 5854)",
    MEETING_ENDED: "the meeting ended (subCode 5000)",
    PARTICIPANT_REMOVED: "the notetaker was removed from the meeting (subCode 5300)",
}

ORGANIZER_ROLES: Final[frozenset[str]] = frozenset({"organizer", "coorganizer", "co-organizer"})
EXTERNAL_ROLES: Final[frozenset[str]] = frozenset({"anonymous", "guest", "external", "federated"})


class SignalSource(StrEnum):
    ROSTER = "roster"
    CSRC = "csrc"
    DOMINANT = "dominant"
    DOM = "dom"


SPEAKER_SIGNAL_PRIORITY: Final[tuple[SignalSource, ...]] = (
    SignalSource.CSRC,
    SignalSource.DOMINANT,
    SignalSource.DOM,
)


class SpeakerState(StrEnum):
    SPEAKING = "speaking"
    CONTESTED = "contested"
    SILENT = "silent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RosterParticipantRecord:
    identifier: str
    display_name: str
    state: str = "unknown"
    meeting_role: str | None = None
    audio_sources: tuple[int, ...] = ()

    @property
    def is_active(self) -> bool:
        return self.state.lower() == "active"

    def to_participant(self) -> Participant:
        role = (self.meeting_role or "").lower()
        return Participant(
            identifier=self.identifier,
            display_name=self.display_name,
            is_organizer=role in ORGANIZER_ROLES,
            is_external=role in EXTERNAL_ROLES,
        )


@dataclass(frozen=True, slots=True)
class InstrumentationReadyEvent:
    at_epoch_ms: int
    href: str = ""


@dataclass(frozen=True, slots=True)
class RosterUpdateEvent:
    at_epoch_ms: int
    participants: tuple[RosterParticipantRecord, ...] = ()
    call_id: str | None = None


@dataclass(frozen=True, slots=True)
class CsrcActivityEvent:
    at_epoch_ms: int
    sources: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CsrcMappingEvent:
    at_epoch_ms: int
    mapping: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DominantSpeakerEvent:
    at_epoch_ms: int
    source_id: int | None = None
    history: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DomSpeakingEvent:
    at_epoch_ms: int
    display_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomRosterEvent:
    at_epoch_ms: int
    display_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CallEndEvent:
    at_epoch_ms: int
    code: int | None = None
    sub_code: int | None = None
    reason: str | None = None
    call_id: str | None = None
    url: str | None = None

    @property
    def is_refusal(self) -> bool:
        return self.sub_code in REFUSAL_SUB_CODES

    @property
    def is_termination(self) -> bool:
        return self.sub_code in TERMINATION_SUB_CODES

    @property
    def explanation(self) -> str:
        if self.sub_code is not None and self.sub_code in SUB_CODE_EXPLANATIONS:
            return SUB_CODE_EXPLANATIONS[self.sub_code]
        detail = self.reason or "no reason reported"
        return f"the call ended with code={self.code} subCode={self.sub_code} ({detail})"


@dataclass(frozen=True, slots=True)
class HealthEvent:
    at_epoch_ms: int
    counters: Mapping[str, int] = field(default_factory=dict)
    active_csrc: tuple[int, ...] = ()
    dominant_source: int | None = None
    mapped_csrc: int = 0
    peer_connections: int = 0


@dataclass(frozen=True, slots=True)
class InstrumentationErrorEvent:
    at_epoch_ms: int
    where: str = ""
    message: str = ""


CaptureEvent: TypeAlias = (
    InstrumentationReadyEvent
    | RosterUpdateEvent
    | CsrcActivityEvent
    | CsrcMappingEvent
    | DominantSpeakerEvent
    | DomSpeakingEvent
    | DomRosterEvent
    | CallEndEvent
    | HealthEvent
    | InstrumentationErrorEvent
)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_int_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    parsed = (_as_int(item) for item in value)
    return tuple(item for item in parsed if item is not None)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_roster_participants(value: Any) -> tuple[RosterParticipantRecord, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    records: list[RosterParticipantRecord] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        display_name = _as_str(item.get("display_name"))
        identifier = _as_str(item.get("id"))
        if not display_name or not identifier:
            continue
        records.append(
            RosterParticipantRecord(
                identifier=identifier,
                display_name=display_name,
                state=_as_str(item.get("state")) or "unknown",
                meeting_role=_as_str(item.get("meeting_role")),
                audio_sources=_as_int_tuple(item.get("audio_sources")),
            )
        )
    return tuple(records)


def _parse_mapping(value: Any) -> tuple[tuple[int, str], ...]:
    if not isinstance(value, Mapping):
        return ()
    pairs: list[tuple[int, str]] = []
    for key, owner in value.items():
        source = _as_int(key)
        identity = _as_str(owner)
        if source is not None and identity:
            pairs.append((source, identity))
    return tuple(sorted(pairs))


def _parse_counters(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counters: dict[str, int] = {}
    for key, item in value.items():
        parsed = _as_int(item)
        if parsed is not None:
            counters[str(key)] = parsed
    return counters


def parse_event(payload: Mapping[str, Any]) -> CaptureEvent | None:
    kind = payload.get("kind")
    at_epoch_ms = _as_int(payload.get("at_epoch_ms"))
    if not isinstance(kind, str) or at_epoch_ms is None:
        return None
    if kind == "ready":
        return InstrumentationReadyEvent(at_epoch_ms=at_epoch_ms, href=_as_str(payload.get("href")) or "")
    if kind == "roster":
        return RosterUpdateEvent(
            at_epoch_ms=at_epoch_ms,
            participants=_parse_roster_participants(payload.get("participants")),
            call_id=_as_str(payload.get("call_id")),
        )
    if kind == "csrc":
        return CsrcActivityEvent(at_epoch_ms=at_epoch_ms, sources=_as_int_tuple(payload.get("sources")))
    if kind == "csrc_map":
        return CsrcMappingEvent(at_epoch_ms=at_epoch_ms, mapping=_parse_mapping(payload.get("mapping")))
    if kind == "dominant":
        return DominantSpeakerEvent(
            at_epoch_ms=at_epoch_ms,
            source_id=_as_int(payload.get("source_id")),
            history=_as_int_tuple(payload.get("history")),
        )
    if kind == "dom_speaking":
        return DomSpeakingEvent(
            at_epoch_ms=at_epoch_ms, display_names=_as_str_tuple(payload.get("display_names"))
        )
    if kind == "dom_roster":
        return DomRosterEvent(
            at_epoch_ms=at_epoch_ms, display_names=_as_str_tuple(payload.get("display_names"))
        )
    if kind == "call_end":
        return CallEndEvent(
            at_epoch_ms=at_epoch_ms,
            code=_as_int(payload.get("code")),
            sub_code=_as_int(payload.get("sub_code")),
            reason=_as_str(payload.get("reason")),
            call_id=_as_str(payload.get("call_id")),
            url=_as_str(payload.get("url")),
        )
    if kind == "health":
        return HealthEvent(
            at_epoch_ms=at_epoch_ms,
            counters=_parse_counters(payload.get("counters")),
            active_csrc=_as_int_tuple(payload.get("active_csrc")),
            dominant_source=_as_int(payload.get("dominant_source")),
            mapped_csrc=_as_int(payload.get("mapped_csrc")) or 0,
            peer_connections=_as_int(payload.get("peer_connections")) or 0,
        )
    if kind == "error":
        return InstrumentationErrorEvent(
            at_epoch_ms=at_epoch_ms,
            where=_as_str(payload.get("where")) or "",
            message=_as_str(payload.get("message")) or "",
        )
    return None


@dataclass(frozen=True, slots=True)
class TimelineSettings:
    metadata_lag_seconds: float = 1.5
    contest_window_seconds: float = 0.35
    min_slice_seconds: float = 0.30
    cross_check_signals: bool = True
    ignore_display_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TimelineSlice:
    span: TimeSpan
    state: SpeakerState
    display_name: str = UNKNOWN_SPEAKER
    participant_id: str | None = None
    candidates: tuple[str, ...] = ()
    signal: SignalSource | None = None

    @property
    def is_attributed(self) -> bool:
        return self.state is SpeakerState.SPEAKING and self.participant_id is not None


@dataclass(frozen=True, slots=True)
class SignalHealth:
    transitions: Mapping[SignalSource, int] = field(default_factory=dict)
    last_event_epoch_ms: int | None = None
    browser_counters: Mapping[str, int] = field(default_factory=dict)
    instrumentation_errors: int = 0

    @property
    def silent_signals(self) -> tuple[SignalSource, ...]:
        return tuple(signal for signal in SPEAKER_SIGNAL_PRIORITY if not self.transitions.get(signal, 0))

    @property
    def has_any_speaker_signal(self) -> bool:
        return any(self.transitions.get(signal, 0) for signal in SPEAKER_SIGNAL_PRIORITY)


@dataclass(frozen=True, slots=True)
class SpeakerTimeline:
    slices: tuple[TimelineSlice, ...] = ()
    lag_seconds: float = 0.0
    health: SignalHealth = field(default_factory=SignalHealth)

    def observations(self) -> tuple[ActiveSpeakerObservation, ...]:
        return tuple(
            ActiveSpeakerObservation(
                span=item.span, display_name=item.display_name, participant_id=item.participant_id
            )
            for item in self.slices
            if item.state is SpeakerState.SPEAKING
        )

    def contested(self) -> tuple[TimelineSlice, ...]:
        return tuple(item for item in self.slices if item.state is SpeakerState.CONTESTED)

    def attributed_seconds(self) -> float:
        return sum(item.span.duration for item in self.slices if item.state is SpeakerState.SPEAKING)

    def contested_seconds(self) -> float:
        return sum(item.span.duration for item in self.slices if item.state is SpeakerState.CONTESTED)


@dataclass(frozen=True, slots=True)
class _Assertion:
    at_seconds: float
    resolved: frozenset[str]
    unresolved: int


@dataclass(frozen=True, slots=True)
class _RawAssertion:
    at_epoch_ms: int
    sources: tuple[int, ...] = ()
    names: tuple[str, ...] = ()


class CaptureEventReducer:
    def __init__(self, settings: TimelineSettings | None = None) -> None:
        self._settings = settings or TimelineSettings()
        self._participants: dict[str, RosterParticipantRecord] = {}
        self._source_owner: dict[int, str] = {}
        self._raw: dict[SignalSource, list[_RawAssertion]] = {
            SignalSource.CSRC: [],
            SignalSource.DOMINANT: [],
            SignalSource.DOM: [],
        }
        self._transitions: dict[SignalSource, int] = {}
        self._browser_counters: dict[str, int] = {}
        self._instrumentation_errors = 0
        self._last_event_epoch_ms: int | None = None
        self._call_end: CallEndEvent | None = None
        self._call_id: str | None = None
        self._origin_epoch_ms: int | None = None
        self._ignored = {name.casefold() for name in self._settings.ignore_display_names}

    @property
    def settings(self) -> TimelineSettings:
        return self._settings

    @property
    def call_end(self) -> CallEndEvent | None:
        return self._call_end

    @property
    def call_id(self) -> str | None:
        return self._call_id

    @property
    def origin_epoch_ms(self) -> int | None:
        return self._origin_epoch_ms

    def set_origin(self, epoch_ms: int) -> None:
        self._origin_epoch_ms = epoch_ms

    def push(self, event: CaptureEvent) -> None:
        self._last_event_epoch_ms = max(self._last_event_epoch_ms or 0, event.at_epoch_ms)
        if isinstance(event, RosterUpdateEvent):
            self._absorb_roster(event)
        elif isinstance(event, CsrcMappingEvent):
            self._source_owner.update(dict(event.mapping))
        elif isinstance(event, CsrcActivityEvent):
            self._append(SignalSource.CSRC, _RawAssertion(event.at_epoch_ms, sources=event.sources))
        elif isinstance(event, DominantSpeakerEvent):
            sources = () if event.source_id is None else (event.source_id,)
            self._append(SignalSource.DOMINANT, _RawAssertion(event.at_epoch_ms, sources=sources))
        elif isinstance(event, DomSpeakingEvent):
            self._append(SignalSource.DOM, _RawAssertion(event.at_epoch_ms, names=event.display_names))
        elif isinstance(event, CallEndEvent):
            self._call_end = event
            self._call_id = event.call_id or self._call_id
        elif isinstance(event, HealthEvent):
            self._browser_counters = dict(event.counters)
        elif isinstance(event, InstrumentationErrorEvent):
            self._instrumentation_errors += 1

    def push_payload(self, payload: Mapping[str, Any]) -> CaptureEvent | None:
        event = parse_event(payload)
        if event is not None:
            self.push(event)
        return event

    def _append(self, signal: SignalSource, assertion: _RawAssertion) -> None:
        history = self._raw[signal]
        if history and history[-1].sources == assertion.sources and history[-1].names == assertion.names:
            return
        history.append(assertion)
        self._transitions[signal] = self._transitions.get(signal, 0) + 1

    def _absorb_roster(self, event: RosterUpdateEvent) -> None:
        self._call_id = event.call_id or self._call_id
        self._transitions[SignalSource.ROSTER] = self._transitions.get(SignalSource.ROSTER, 0) + 1
        for record in event.participants:
            if record.display_name.casefold() in self._ignored:
                continue
            self._participants[record.identifier] = record
            for source in record.audio_sources:
                self._source_owner[source] = record.identifier

    def participants(self) -> tuple[Participant, ...]:
        ordered = sorted(self._participants.values(), key=lambda record: record.display_name.casefold())
        return tuple(record.to_participant() for record in ordered)

    def active_participant_count(self) -> int:
        return sum(1 for record in self._participants.values() if record.is_active)

    def health(self) -> SignalHealth:
        return SignalHealth(
            transitions=dict(self._transitions),
            last_event_epoch_ms=self._last_event_epoch_ms,
            browser_counters=dict(self._browser_counters),
            instrumentation_errors=self._instrumentation_errors,
        )

    def _resolve_source(self, source: int) -> str | None:
        owner = self._source_owner.get(source)
        if owner is not None and owner in self._participants:
            return owner
        for record in self._participants.values():
            if source in record.audio_sources:
                return record.identifier
        return None

    def _resolve_name(self, name: str) -> str | None:
        folded = name.casefold()
        for record in self._participants.values():
            if record.display_name.casefold() == folded:
                return record.identifier
        for record in self._participants.values():
            if record.display_name.casefold().startswith(folded) or folded.startswith(
                record.display_name.casefold()
            ):
                return record.identifier
        return None

    def _to_assertion(self, raw: _RawAssertion, origin_epoch_ms: int, horizon: float) -> _Assertion:
        lag_ms = self._settings.metadata_lag_seconds * 1000.0
        at_seconds = (raw.at_epoch_ms - lag_ms - origin_epoch_ms) / 1000.0
        resolved: set[str] = set()
        unresolved = 0
        for source in raw.sources:
            owner = self._resolve_source(source)
            if owner is None:
                unresolved += 1
            else:
                resolved.add(owner)
        for name in raw.names:
            if name.casefold() in self._ignored:
                continue
            owner = self._resolve_name(name)
            if owner is None:
                unresolved += 1
            else:
                resolved.add(owner)
        return _Assertion(
            at_seconds=min(max(at_seconds, 0.0), horizon),
            resolved=frozenset(resolved),
            unresolved=unresolved,
        )

    def _assertions(self, origin_epoch_ms: int, horizon: float) -> dict[SignalSource, list[_Assertion]]:
        built: dict[SignalSource, list[_Assertion]] = {}
        for signal, history in self._raw.items():
            assertions = [self._to_assertion(raw, origin_epoch_ms, horizon) for raw in history]
            assertions.sort(key=lambda item: item.at_seconds)
            built[signal] = assertions
        return built

    def timeline(self, end_epoch_ms: int) -> SpeakerTimeline:
        origin = self._origin_epoch_ms
        health = self.health()
        if origin is None or end_epoch_ms <= origin:
            return SpeakerTimeline(lag_seconds=self._settings.metadata_lag_seconds, health=health)
        horizon = (end_epoch_ms - origin) / 1000.0
        assertions = self._assertions(origin, horizon)
        boundaries = _boundaries(assertions, horizon)
        raw_slices = [
            self._classify(TimeSpan(start, end), assertions)
            for start, end in pairwise(boundaries)
            if end > start
        ]
        merged = _merge_slices(raw_slices)
        gated = _demote_short_slices(merged, self._settings.min_slice_seconds)
        contested = _apply_contest_window(gated, self._settings.contest_window_seconds)
        return SpeakerTimeline(
            slices=tuple(_merge_slices(contested)),
            lag_seconds=self._settings.metadata_lag_seconds,
            health=health,
        )

    def _classify(self, span: TimeSpan, assertions: Mapping[SignalSource, list[_Assertion]]) -> TimelineSlice:
        instant = span.start
        primary: SignalSource | None = None
        current: _Assertion | None = None
        for signal in SPEAKER_SIGNAL_PRIORITY:
            candidate = _value_at(assertions.get(signal, []), instant)
            if candidate is None:
                continue
            primary = signal
            current = candidate
            break
        if primary is None or current is None:
            return TimelineSlice(span=span, state=SpeakerState.UNKNOWN)
        total = len(current.resolved) + current.unresolved
        if total == 0:
            return TimelineSlice(span=span, state=SpeakerState.SILENT, signal=primary)
        candidates = tuple(sorted(current.resolved))
        if total > 1:
            return TimelineSlice(
                span=span,
                state=SpeakerState.CONTESTED,
                candidates=candidates,
                signal=primary,
            )
        if not candidates:
            return TimelineSlice(span=span, state=SpeakerState.UNKNOWN, signal=primary)
        winner = candidates[0]
        if self._settings.cross_check_signals and self._disputed(winner, primary, assertions, instant):
            return TimelineSlice(
                span=span, state=SpeakerState.CONTESTED, candidates=candidates, signal=primary
            )
        record = self._participants.get(winner)
        return TimelineSlice(
            span=span,
            state=SpeakerState.SPEAKING,
            display_name=record.display_name if record else UNKNOWN_SPEAKER,
            participant_id=winner,
            candidates=candidates,
            signal=primary,
        )

    def _disputed(
        self,
        winner: str,
        primary: SignalSource,
        assertions: Mapping[SignalSource, list[_Assertion]],
        instant: float,
    ) -> bool:
        for signal in SPEAKER_SIGNAL_PRIORITY:
            if signal is primary:
                continue
            other = _value_at(assertions.get(signal, []), instant)
            if other is None or other.unresolved or len(other.resolved) != 1:
                continue
            if winner not in other.resolved:
                return True
        return False

    def roster(self, end_epoch_ms: int) -> Roster:
        timeline = self.timeline(end_epoch_ms)
        return Roster(participants=self.participants(), observations=timeline.observations())


def _value_at(assertions: Sequence[_Assertion], instant: float) -> _Assertion | None:
    found: _Assertion | None = None
    for assertion in assertions:
        if assertion.at_seconds <= instant + 1e-9:
            found = assertion
        else:
            break
    return found


def _boundaries(assertions: Mapping[SignalSource, list[_Assertion]], horizon: float) -> list[float]:
    points = {0.0, horizon}
    for history in assertions.values():
        for assertion in history:
            if 0.0 <= assertion.at_seconds <= horizon:
                points.add(assertion.at_seconds)
    return sorted(points)


def _same_attribution(left: TimelineSlice, right: TimelineSlice) -> bool:
    return (
        left.state is right.state
        and left.participant_id == right.participant_id
        and left.candidates == right.candidates
    )


def _merge_slices(slices: Iterable[TimelineSlice]) -> list[TimelineSlice]:
    merged: list[TimelineSlice] = []
    for item in slices:
        if merged and _same_attribution(merged[-1], item) and merged[-1].span.end >= item.span.start - 1e-9:
            previous = merged[-1]
            merged[-1] = TimelineSlice(
                span=TimeSpan(previous.span.start, item.span.end),
                state=previous.state,
                display_name=previous.display_name,
                participant_id=previous.participant_id,
                candidates=previous.candidates,
                signal=previous.signal,
            )
        else:
            merged.append(item)
    return merged


def _demote_short_slices(slices: Sequence[TimelineSlice], minimum: float) -> list[TimelineSlice]:
    if minimum <= 0:
        return list(slices)
    return [
        item
        if item.state is not SpeakerState.SPEAKING or item.span.duration >= minimum
        else TimelineSlice(
            span=item.span,
            state=SpeakerState.SILENT,
            candidates=item.candidates,
            signal=item.signal,
        )
        for item in slices
    ]


def _carved(item: TimelineSlice, start: float, end: float) -> TimelineSlice:
    return TimelineSlice(
        span=TimeSpan(start, end),
        state=item.state,
        display_name=item.display_name,
        participant_id=item.participant_id,
        candidates=item.candidates,
        signal=item.signal,
    )


def _contested_bridge(left: TimelineSlice, right: TimelineSlice, start: float, end: float) -> TimelineSlice:
    candidates = tuple(
        sorted({identifier for identifier in (left.participant_id, right.participant_id) if identifier})
    )
    return TimelineSlice(
        span=TimeSpan(start, end),
        state=SpeakerState.CONTESTED,
        candidates=candidates,
        signal=left.signal,
    )


def _apply_contest_window(slices: Sequence[TimelineSlice], window: float) -> list[TimelineSlice]:
    if window <= 0 or len(slices) < 2:
        return list(slices)
    half = window / 2.0
    result: list[TimelineSlice] = [slices[0]]
    for item in slices[1:]:
        previous = result[-1]
        speakers_swap = (
            previous.state is SpeakerState.SPEAKING
            and item.state is SpeakerState.SPEAKING
            and previous.participant_id != item.participant_id
        )
        if not speakers_swap:
            result.append(item)
            continue
        boundary = item.span.start
        left_cut = min(half, previous.span.duration / 2.0)
        right_cut = min(half, item.span.duration / 2.0)
        result[-1] = _carved(previous, previous.span.start, boundary - left_cut)
        result.append(_contested_bridge(previous, item, boundary - left_cut, boundary + right_cut))
        result.append(_carved(item, boundary + right_cut, item.span.end))
    return [item for item in result if item.span.duration > 1e-9]
