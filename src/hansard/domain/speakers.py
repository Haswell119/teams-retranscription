from __future__ import annotations

from dataclasses import dataclass, field, replace

from hansard.domain.timespan import TimeSpan

UNKNOWN_SPEAKER = "unknown"


@dataclass(frozen=True, slots=True)
class Participant:
    identifier: str
    display_name: str
    email: str | None = None
    is_organizer: bool = False
    is_external: bool = False

    @property
    def initials(self) -> str:
        parts = [part for part in self.display_name.replace("-", " ").split() if part]
        return "".join(part[0].upper() for part in parts[:2]) or "?"


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    span: TimeSpan
    label: str
    confidence: float = 1.0

    def shifted(self, offset: float) -> SpeakerTurn:
        return replace(self, span=self.span.shifted(offset))


@dataclass(frozen=True, slots=True)
class ActiveSpeakerObservation:
    span: TimeSpan
    display_name: str
    participant_id: str | None = None


@dataclass(frozen=True, slots=True)
class Roster:
    participants: tuple[Participant, ...] = ()
    observations: tuple[ActiveSpeakerObservation, ...] = ()

    def by_display_name(self) -> dict[str, Participant]:
        return {participant.display_name: participant for participant in self.participants}

    def observation_time_by_name(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for observation in self.observations:
            totals[observation.display_name] = (
                totals.get(observation.display_name, 0.0) + observation.span.duration
            )
        return totals


@dataclass(frozen=True, slots=True)
class Diarization:
    turns: tuple[SpeakerTurn, ...] = ()
    labels: tuple[str, ...] = field(default=())

    @property
    def speaker_count(self) -> int:
        return len({turn.label for turn in self.turns})

    def speaking_time(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for turn in self.turns:
            totals[turn.label] = totals.get(turn.label, 0.0) + turn.span.duration
        return totals

    def label_at(self, instant: float) -> str | None:
        for turn in self.turns:
            if turn.span.contains(instant):
                return turn.label
        return None
