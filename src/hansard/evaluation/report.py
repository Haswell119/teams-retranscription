from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from hansard.evaluation.gates import GateOutcome
from hansard.evaluation.harness import BenchmarkReport

RATE = "rate"
SECONDS = "seconds"
MEGABYTES = "megabytes"
FACTOR = "factor"
COUNT = "count"

LOWER_IS_BETTER = "lower is better"
HIGHER_IS_BETTER = "higher is better"

METRIC_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("wer", "Word error rate", RATE, LOWER_IS_BETTER),
    ("cer", "Character error rate", RATE, LOWER_IS_BETTER),
    ("cpwer", "Concatenated minimum-permutation WER", RATE, LOWER_IS_BETTER),
    ("wder", "Word diarization error rate", RATE, LOWER_IS_BETTER),
    ("der", "Diarization error rate", RATE, LOWER_IS_BETTER),
    ("missed_speech_rate", "Missed speech", RATE, LOWER_IS_BETTER),
    ("false_alarm_rate", "False alarm speech", RATE, LOWER_IS_BETTER),
    ("confusion_rate", "Speaker confusion", RATE, LOWER_IS_BETTER),
    ("jer", "Jaccard error rate", RATE, LOWER_IS_BETTER),
    ("speaker_count_error", "Speaker count error", COUNT, LOWER_IS_BETTER),
    ("rtf", "Real-time factor", FACTOR, LOWER_IS_BETTER),
    ("peak_rss_mb", "Peak resident memory", MEGABYTES, LOWER_IS_BETTER),
    ("vram_mb", "GPU memory", MEGABYTES, LOWER_IS_BETTER),
    ("wall_seconds", "Wall-clock time", SECONDS, LOWER_IS_BETTER),
    ("cpu_seconds", "CPU time", SECONDS, LOWER_IS_BETTER),
    ("audio_seconds", "Audio duration", SECONDS, HIGHER_IS_BETTER),
    ("sample_count", "Evaluated samples", COUNT, HIGHER_IS_BETTER),
)

_UNITS: dict[str, str] = {key: unit for key, _, unit, _ in METRIC_SPECS}
_LABELS: dict[str, str] = {key: label for key, label, _, _ in METRIC_SPECS}
_DIRECTIONS: dict[str, str] = {key: direction for key, _, _, direction in METRIC_SPECS}
_UNAVAILABLE = "n/a"


@dataclass(frozen=True, slots=True)
class BaselineColumn:
    name: str
    values: Mapping[str, float] = field(default_factory=dict)
    note: str = ""


def report_to_dict(report: BenchmarkReport, gates: GateOutcome | None = None) -> dict[str, object]:
    payload: dict[str, object] = asdict(report)
    payload["generated_at"] = report.generated_at.isoformat()
    payload["metrics"] = {name: report.metric_values[name] for name in ordered_metric_names(report)}
    if gates is not None:
        payload["gates"] = [
            {
                "metric": result.gate.metric,
                "comparison": result.gate.comparison,
                "threshold": result.gate.threshold,
                "tier": result.gate.tier,
                "observed": result.observed,
                "status": result.status,
            }
            for result in gates.results
        ]
        payload["gates_passed"] = gates.passed
    return payload


def render_json(report: BenchmarkReport, gates: GateOutcome | None = None, indent: int = 2) -> str:
    return json.dumps(report_to_dict(report, gates), indent=indent, ensure_ascii=False, default=str)


def render_markdown(
    report: BenchmarkReport,
    baseline: BaselineColumn | None = None,
    gates: GateOutcome | None = None,
    include_samples: bool = False,
) -> str:
    values = report.metric_values
    baseline_name = baseline.name if baseline is not None else "Baseline"
    baseline_values = baseline.values if baseline is not None else {}
    lines = [
        f"# {report.label}",
        "",
        f"- Engine: `{report.engine}`",
        f"- Generated: {report.generated_at.isoformat()}",
        f"- Samples: {len(report.samples)}",
        "",
        f"| Metric | Hansard | {baseline_name} | Direction |",
        "| --- | ---: | ---: | --- |",
    ]
    lines.extend(
        _metric_row(name, values.get(name), baseline_values.get(name))
        for name in ordered_metric_names(report, baseline_values)
    )
    if baseline is not None and baseline.note:
        lines.extend(["", f"> {baseline.note}"])
    if gates is not None:
        lines.extend(_gate_section(gates))
    if include_samples:
        lines.extend(_sample_section(report))
    return "\n".join(lines) + "\n"


def ordered_metric_names(
    report: BenchmarkReport,
    baseline_values: Mapping[str, float] | None = None,
) -> tuple[str, ...]:
    available = set(report.metric_values)
    available.update(baseline_values or {})
    ordered = [name for name, _, _, _ in METRIC_SPECS if name in available]
    extra = sorted(available - set(ordered))
    return tuple(ordered + extra)


def _metric_row(name: str, observed: float | None, baseline: float | None) -> str:
    label = _LABELS.get(name, name)
    direction = _DIRECTIONS.get(name, LOWER_IS_BETTER)
    return f"| {label} | {_format_value(name, observed)} | {_format_value(name, baseline)} | {direction} |"


def _format_value(name: str, value: float | None) -> str:
    if value is None:
        return _UNAVAILABLE
    unit = _UNITS.get(name, FACTOR)
    if unit == RATE:
        return f"{value * 100:.2f} %"
    if unit == SECONDS:
        return f"{value:.1f} s"
    if unit == MEGABYTES:
        return f"{value:.0f} MB"
    if unit == COUNT:
        return f"{value:.2f}" if value % 1 else f"{value:.0f}"
    return f"{value:.3f}"


def _gate_section(gates: GateOutcome) -> list[str]:
    lines = [
        "",
        "## Quality gates",
        "",
        "| Metric | Expectation | Observed | Tier | Status |",
        "| --- | --- | ---: | --- | --- |",
    ]
    lines.extend(
        "| {metric} | `{expectation}` | {observed} | {tier} | {status} |".format(
            metric=_LABELS.get(result.gate.metric, result.gate.metric),
            expectation=result.gate.expectation,
            observed=_UNAVAILABLE if result.observed is None else f"{result.observed:g}",
            tier=result.gate.tier,
            status=result.status,
        )
        for result in gates.results
    )
    lines.extend(["", f"Overall: {'PASS' if gates.passed else 'FAIL'}"])
    return lines


def _sample_section(report: BenchmarkReport) -> list[str]:
    lines = [
        "",
        "## Per-sample results",
        "",
        "| Sample | Language | Audio (s) | WER | CER | cpWER | DER | RTF |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        "| {identifier} | {language} | {audio:.2f} | {wer} | {cer} | {cpwer} | {der} | {rtf:.3f} |".format(
            identifier=sample.identifier,
            language=sample.language,
            audio=sample.audio_seconds,
            wer=_format_value("wer", sample.wer),
            cer=_format_value("cer", sample.cer),
            cpwer=_format_value("cpwer", sample.cpwer),
            der=_format_value("der", sample.der),
            rtf=sample.real_time_factor,
        )
        for sample in sorted(report.samples, key=lambda item: item.identifier)
    )
    return lines
