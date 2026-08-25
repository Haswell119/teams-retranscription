from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.matching import maximum_weight_assignment
from hansard.domain.speakers import Diarization, Roster
from hansard.domain.transcript import Transcript


@dataclass(frozen=True, slots=True)
class RosterSpeakerNamer:
    minimum_coverage: float = 0.50
    minimum_margin: float = 0.15
    observation_lag: float = 0.0
    fallback_prefix: str = "Speaker"

    @property
    def name(self) -> str:
        return "roster"

    def _overlap_matrix(
        self, diarization: Diarization, roster: Roster, labels: list[str], names: list[str]
    ) -> list[list[float]]:
        matrix = [[0.0] * len(names) for _ in labels]
        label_index = {label: index for index, label in enumerate(labels)}
        name_index = {name: index for index, name in enumerate(names)}
        for turn in diarization.turns:
            row = label_index[turn.label]
            for observation in roster.observations:
                column = name_index.get(observation.display_name)
                if column is None:
                    continue
                matrix[row][column] += turn.span.overlap(observation.span.shifted(-self.observation_lag))
        return matrix

    def resolve_names(
        self, transcript: Transcript, diarization: Diarization, roster: Roster
    ) -> dict[str, str]:
        labels = list(diarization.labels or dict.fromkeys(turn.label for turn in diarization.turns))
        if not labels:
            return {}
        names = list(dict.fromkeys(observation.display_name for observation in roster.observations))
        speaking_time = diarization.speaking_time()
        fallback = {
            label: f"{self.fallback_prefix} {index + 1}" for index, label in enumerate(labels)
        }
        if not names:
            return fallback
        matrix = self._overlap_matrix(diarization, roster, labels, names)
        resolved = dict(fallback)
        for row, column in maximum_weight_assignment(matrix):
            label = labels[row]
            total = speaking_time.get(label, 0.0)
            if total <= 0.0:
                continue
            best = matrix[row][column]
            runner_up = max((value for index, value in enumerate(matrix[row]) if index != column), default=0.0)
            coverage = best / total
            margin = (best - runner_up) / total
            if coverage >= self.minimum_coverage and margin >= self.minimum_margin:
                resolved[label] = names[column]
        return resolved
