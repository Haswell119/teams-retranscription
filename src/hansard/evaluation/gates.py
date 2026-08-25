from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from hansard.domain.errors import QualityGateFailed
from hansard.evaluation.harness import BenchmarkReport

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

    @property
    def expectation(self) -> str:
        return f"{self.metric} {self.comparison} {self.threshold:g}"


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
        return tuple(
            result
            for result in self.results
            if result.gate.tier == "must_pass" and result.status == "failed"
        )

    @property
    def missing(self) -> tuple[GateResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.gate.tier == "must_pass" and result.status == "missing"
        )

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


DEFAULT_GATES: tuple[QualityGate, ...] = (
    QualityGate("wer", "<=", 0.15, "must_pass"),
    QualityGate("wer", "<=", 0.08, "stretch"),
    QualityGate("cer", "<=", 0.08, "must_pass"),
    QualityGate("cpwer", "<=", 0.25, "must_pass"),
    QualityGate("cpwer", "<=", 0.15, "stretch"),
    QualityGate("der", "<=", 0.15, "must_pass"),
    QualityGate("der", "<=", 0.08, "stretch"),
    QualityGate("wder", "<=", 0.10, "must_pass"),
    QualityGate("jer", "<=", 0.30, "stretch"),
    QualityGate("speaker_count_error", "<=", 1.0, "must_pass"),
    QualityGate("rtf", "<=", 1.0, "must_pass"),
    QualityGate("rtf", "<=", 0.35, "stretch"),
    QualityGate("peak_rss_mb", "<=", 8192.0, "must_pass"),
)


def evaluate_gate(gate: QualityGate, values: Mapping[str, float]) -> GateResult:
    observed = values.get(gate.metric)
    if observed is None:
        return GateResult(gate=gate, observed=None, status="missing")
    passed = _COMPARISONS[gate.comparison](observed, gate.threshold)
    return GateResult(gate=gate, observed=observed, status="passed" if passed else "failed")


def evaluate_gates(
    report: BenchmarkReport,
    gates: Sequence[QualityGate] = DEFAULT_GATES,
) -> GateOutcome:
    values = report.metric_values
    return GateOutcome(results=tuple(evaluate_gate(gate, values) for gate in gates))
