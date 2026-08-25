from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from hansard.evaluation.gates import (
    ENGLISH_MEETING_GATES,
    FRENCH_MEETING_GATES,
    READ_SPEECH_GATES,
    SYSTEM_GATES,
    QualityGate,
)

PERCENT_METRICS = frozenset({"wer", "cer", "cpwer", "tcpwer", "wder", "der", "jer"})
RESULTS_DIRECTORY = Path("bench/results")


@dataclass(frozen=True, slots=True)
class Observation:
    source: str
    subject: str
    language: str
    kind: str
    metrics: dict[str, float]


@dataclass(frozen=True, slots=True)
class Verdict:
    observation: Observation
    gate: QualityGate
    value: float
    passed: bool

    @property
    def summary(self) -> str:
        marker = "pass" if self.passed else "FAIL"
        unit = "%" if self.gate.metric in PERCENT_METRICS else ""
        scale = 100.0 if self.gate.metric in PERCENT_METRICS else 1.0
        return (
            f"{marker:4s} {self.gate.tier:9s} {self.observation.subject:34s} "
            f"{self.gate.metric:20s} {self.value * scale:8.2f}{unit} "
            f"{self.gate.comparison} {self.gate.threshold * scale:.2f}{unit}"
        )


def _metrics_from(row: dict[str, object]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for key, value in row.items():
        if not isinstance(value, int | float):
            continue
        if key.endswith("_percent"):
            metrics[key.removesuffix("_percent")] = float(value) / 100.0
        elif key in {"real_time_factor", "peak_rss_mb"}:
            metrics["rtf" if key == "real_time_factor" else key] = float(value)
    reference = row.get("reference_speakers")
    detected = row.get("detected_speakers")
    if isinstance(reference, int) and isinstance(detected, int):
        metrics["speaker_count_error"] = float(abs(reference - detected))
    return metrics


def observations(directory: Path) -> tuple[Observation, ...]:
    collected: list[Observation] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("profile", "default") != "default":
            continue
        benchmark = str(payload.get("benchmark", path.stem))
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            subject = str(row.get("dataset") or row.get("meeting") or "unknown")
            language = str(row.get("language", "en"))
            kind = "read" if benchmark == "asr" else "meeting"
            collected.append(Observation(path.name, subject, language, kind, _metrics_from(row)))
    return tuple(collected)


def gates_for(observation: Observation) -> tuple[QualityGate, ...]:
    if observation.kind == "read":
        return tuple(gate for gate in READ_SPEECH_GATES if gate.language in {observation.language, "all"})
    meeting = ENGLISH_MEETING_GATES if observation.language == "en" else FRENCH_MEETING_GATES
    return tuple(meeting) + tuple(SYSTEM_GATES)


def _satisfied(value: float, gate: QualityGate) -> bool:
    if gate.comparison == "<=":
        return value <= gate.threshold
    if gate.comparison == ">=":
        return value >= gate.threshold
    if gate.comparison == "<":
        return value < gate.threshold
    return value > gate.threshold


def evaluate(directory: Path) -> list[Verdict]:
    verdicts: list[Verdict] = []
    for observation in observations(directory):
        for gate in gates_for(observation):
            value = observation.metrics.get(gate.metric)
            if value is None:
                continue
            verdicts.append(Verdict(observation, gate, value, _satisfied(value, gate)))
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hansard-gates")
    parser.add_argument("--results", type=Path, default=RESULTS_DIRECTORY)
    parser.add_argument("--strict", action="store_true")
    arguments = parser.parse_args(argv)
    verdicts = evaluate(arguments.results)
    if not verdicts:
        print(f"no benchmark results in {arguments.results}; run `make bench` first")
        return 1
    failures = [verdict for verdict in verdicts if not verdict.passed]
    must_pass = [verdict for verdict in failures if verdict.gate.tier == "must_pass"]
    for verdict in verdicts:
        if not verdict.passed:
            print(verdict.summary)
    passed = len(verdicts) - len(failures)
    print(
        f"\n{passed}/{len(verdicts)} gates met  "
        f"({len(must_pass)} must-pass failures, {len(failures) - len(must_pass)} stretch misses)"
    )
    if must_pass:
        print("\nMust-pass gates are not met. The work is not finished.")
        return 1
    if failures and arguments.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
