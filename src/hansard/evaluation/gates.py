from __future__ import annotations

import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from hansard.domain.errors import QualityGateFailed
from hansard.evaluation.harness import ALL_LANGUAGES, BenchmarkReport

Comparison = Literal["<=", "<", ">=", ">", "=="]
GateTier = Literal["must_pass", "stretch"]
GateStatus = Literal["passed", "failed", "missing"]

_COMPARISONS: dict[Comparison, Callable[[float, float], bool]] = {
    "<=": operator.le,
    "<": operator.lt,
    ">=": operator.ge,
    ">": operator.gt,
    "==": operator.eq,
}


@dataclass(frozen=True, slots=True)
class QualityGate:
    metric: str
    comparison: Comparison
    threshold: float
    tier: GateTier = "must_pass"
    language: str = ALL_LANGUAGES

    @property
    def expectation(self) -> str:
        return f"{self.language}:{self.metric} {self.comparison} {self.threshold:g}"


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: QualityGate
    observed: float | None
    status: GateStatus

    @property
    def summary(self) -> str:
        observed = "n/a" if self.observed is None else f"{self.observed:g}"
        return f"{self.gate.expectation} (observed {observed}) [{self.status}]"


@dataclass(frozen=True, slots=True)
class GateOutcome:
    results: tuple[GateResult, ...]

    @property
    def failures(self) -> tuple[GateResult, ...]:
        return self._blocking("failed")

    @property
    def missing(self) -> tuple[GateResult, ...]:
        return self._blocking("missing")

    @property
    def stretch_failures(self) -> tuple[GateResult, ...]:
        return tuple(
            result for result in self.results if result.gate.tier == "stretch" and result.status != "passed"
        )

    @property
    def passed(self) -> bool:
        return not self.failures and not self.missing

    def raise_for_status(self) -> None:
        if self.passed:
            return
        blocking = self.failures + self.missing
        raise QualityGateFailed("; ".join(result.summary for result in blocking))

    def _blocking(self, status: GateStatus) -> tuple[GateResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.gate.tier == "must_pass" and result.status == status
        )


SYSTEM_GATES: tuple[QualityGate, ...] = (
    QualityGate("rtf", "<=", 1.0, "must_pass"),
    QualityGate("rtf", "<=", 0.35, "stretch"),
    QualityGate("peak_rss_mb", "<=", 8192.0, "must_pass"),
)

ENGLISH_MEETING_GATES: tuple[QualityGate, ...] = (
    QualityGate("cpwer", "<=", 0.27, "must_pass", "en"),
    QualityGate("cpwer", "<=", 0.20, "stretch", "en"),
    QualityGate("tcpwer", "<=", 0.30, "must_pass", "en"),
    QualityGate("wder", "<=", 0.10, "must_pass", "en"),
    QualityGate("wder", "<=", 0.05, "stretch", "en"),
    QualityGate("wer", "<=", 0.15, "must_pass", "en"),
    QualityGate("wer", "<=", 0.12, "stretch", "en"),
    QualityGate("cer", "<=", 0.08, "must_pass", "en"),
    QualityGate("der", "<=", 0.15, "must_pass", "en"),
    QualityGate("der", "<=", 0.08, "stretch", "en"),
    QualityGate("speaker_count_error", "<=", 1.0, "must_pass", "en"),
)

FRENCH_MEETING_GATES: tuple[QualityGate, ...] = (
    QualityGate("cpwer", "<=", 0.30, "must_pass", "fr"),
    QualityGate("cpwer", "<=", 0.22, "stretch", "fr"),
    QualityGate("tcpwer", "<=", 0.33, "must_pass", "fr"),
    QualityGate("wder", "<=", 0.12, "must_pass", "fr"),
    QualityGate("wder", "<=", 0.06, "stretch", "fr"),
    QualityGate("wer", "<=", 0.20, "must_pass", "fr"),
    QualityGate("wer", "<=", 0.17, "stretch", "fr"),
    QualityGate("cer", "<=", 0.10, "must_pass", "fr"),
    QualityGate("der", "<=", 0.15, "must_pass", "fr"),
    QualityGate("der", "<=", 0.08, "stretch", "fr"),
    QualityGate("speaker_count_error", "<=", 1.0, "must_pass", "fr"),
)

MEETING_GATES: tuple[QualityGate, ...] = ENGLISH_MEETING_GATES + FRENCH_MEETING_GATES + SYSTEM_GATES

READ_SPEECH_GATES: tuple[QualityGate, ...] = (
    QualityGate("wer", "<=", 0.05, "must_pass", "en"),
    QualityGate("wer", "<=", 0.03, "stretch", "en"),
    QualityGate("cer", "<=", 0.02, "must_pass", "en"),
    QualityGate("wer", "<=", 0.06, "must_pass", "fr"),
    QualityGate("wer", "<=", 0.05, "stretch", "fr"),
    QualityGate("cer", "<=", 0.03, "must_pass", "fr"),
    *SYSTEM_GATES,
)

DEFAULT_GATES: tuple[QualityGate, ...] = MEETING_GATES


def gates_for(
    language: str,
    gates: Sequence[QualityGate] = DEFAULT_GATES,
) -> tuple[QualityGate, ...]:
    return tuple(gate for gate in gates if gate.language == language)


def evaluate_gate(gate: QualityGate, report: BenchmarkReport) -> GateResult:
    values = report.metric_values_for(gate.language)
    observed = values.get(gate.metric) if values is not None else None
    if observed is None:
        return GateResult(gate=gate, observed=None, status="missing")
    passed = _COMPARISONS[gate.comparison](observed, gate.threshold)
    return GateResult(gate=gate, observed=observed, status="passed" if passed else "failed")


def evaluate_gates(
    report: BenchmarkReport,
    gates: Sequence[QualityGate] = DEFAULT_GATES,
) -> GateOutcome:
    return GateOutcome(results=tuple(evaluate_gate(gate, report) for gate in gates))
