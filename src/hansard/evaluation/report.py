from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from hansard.evaluation.gates import GateOutcome, GateResult
from hansard.evaluation.harness import ALL_LANGUAGES, BenchmarkReport, CorpusSlice, SampleOutcome

RATE = "rate"
SECONDS = "seconds"
MEGABYTES = "megabytes"
FACTOR = "factor"
COUNT = "count"

LOWER_IS_BETTER = "lower is better"
HIGHER_IS_BETTER = "higher is better"

METRIC_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("cpwer", "Concatenated minimum-permutation WER", RATE, LOWER_IS_BETTER),
    ("tcpwer", "Time-constrained cpWER", RATE, LOWER_IS_BETTER),
    ("wder", "Word diarization error rate", RATE, LOWER_IS_BETTER),
    ("wer", "Word error rate", RATE, LOWER_IS_BETTER),
    ("cer", "Character error rate", RATE, LOWER_IS_BETTER),
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

HEADLINE_METRICS: tuple[str, ...] = ("cpwer", "tcpwer", "wder", "wer", "cer", "der")
SYSTEM_METRICS: tuple[str, ...] = (
    "rtf",
    "peak_rss_mb",
    "vram_mb",
    "wall_seconds",
    "cpu_seconds",
    "audio_seconds",
    "sample_count",
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


COPILOT_BASELINE = BaselineColumn(
    name="Microsoft Teams / Copilot",
    values={"en:cpwer": 0.2739, "en:wer": 0.1154, "cpwer": 0.2739, "wer": 0.1154},
    note=(
        "English figures only: cpWER 27.39 % on AMI and WER 11.54 % on Teams live transcription "
        "under controlled conditions (12-25 % reported in the field). Microsoft advertises 2.4 % WER, "
        "but that number comes from curated short clips, not from meetings. No Azure or Copilot figure "
        "has ever been published for French meetings, so the French column is deliberately empty."
    ),
)

BASELINE_LIBRARY: dict[str, BaselineColumn] = {
    "ami": BaselineColumn(
        name="Azure / Teams on AMI",
        values={"en:cpwer": 0.2739, "cpwer": 0.2739},
        note="Diarized cpWER measured by the AssemblyAI January 2026 benchmark.",
    ),
    "notsofar1-test": BaselineColumn(
        name="Azure / Teams on NOTSOFAR-1 test",
        values={"en:cpwer": 0.3568, "cpwer": 0.3568},
        note="Diarized cpWER measured by the AssemblyAI January 2026 benchmark.",
    ),
    "notsofar1-dev": BaselineColumn(
        name="Azure / Teams on NOTSOFAR-1 dev",
        values={"en:cpwer": 0.4538, "cpwer": 0.4538},
        note="Diarized cpWER measured by the AssemblyAI January 2026 benchmark.",
    ),
    "dipco": BaselineColumn(
        name="Azure / Teams on DiPCo",
        values={"en:cpwer": 0.3323, "cpwer": 0.3323},
        note="Diarized cpWER measured by the AssemblyAI January 2026 benchmark.",
    ),
    "teams-live-en": BaselineColumn(
        name="Teams live transcription",
        values={"en:wer": 0.1154, "wer": 0.1154},
        note="TestDevLab 2024 measurement in controlled conditions; 12-25 % in field conditions.",
    ),
    "copilot": COPILOT_BASELINE,
}

FRENCH_REFERENCE_POINTS: dict[str, float] = {
    "summ-re:whisper-large-v3": 0.2257,
    "summ-re:whisper-large-v3-turbo": 0.2287,
    "summ-re:canary-1b": 0.1982,
    "summ-re:linto_stt_fr_fastconformer_pc": 0.1979,
}


def report_to_dict(report: BenchmarkReport, gates: GateOutcome | None = None) -> dict[str, object]:
    payload: dict[str, object] = asdict(report)
    payload["generated_at"] = report.generated_at.isoformat()
    payload["normalizer_version"] = report.normalizer_version
    payload["metrics"] = _ordered_values(report.metric_values)
    payload["metrics_by_language"] = {
        slice_.language: _ordered_values(slice_.metric_values) for slice_ in report.language_slices
    }
    payload["metrics_by_dataset"] = {
        f"{slice_.dataset}:{slice_.language}": _ordered_values(slice_.metric_values)
        for slice_ in report.dataset_slices
    }
    if gates is not None:
        payload["gates"] = [
            {
                "metric": result.gate.metric,
                "language": result.gate.language,
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
    lines = _header(report)
    lines.extend(_headline_section(report, baseline))
    lines.extend(_breakdown_section(report))
    lines.extend(_system_section(report, baseline))
    if baseline is not None and baseline.note:
        lines.extend(["", f"> {baseline.note}"])
    if gates is not None:
        lines.extend(_gate_section(gates))
    if include_samples:
        lines.extend(_sample_section(report))
    return "\n".join(lines) + "\n"


def report_languages(report: BenchmarkReport) -> tuple[str, ...]:
    return (*report.languages, ALL_LANGUAGES)


def _header(report: BenchmarkReport) -> list[str]:
    return [
        f"# {report.label}",
        "",
        f"- Engine: `{report.engine}`",
        f"- Normalizer version: `{report.normalizer_version}`",
        f"- Languages: {', '.join(report.languages) or 'none'}",
        f"- Generated: {report.generated_at.isoformat()}",
        f"- Samples: {len(report.samples)}",
    ]


def _headline_section(report: BenchmarkReport, baseline: BaselineColumn | None) -> list[str]:
    baseline_name = baseline.name if baseline is not None else "Baseline"
    baseline_values = baseline.values if baseline is not None else {}
    lines = [
        "",
        "## Headline quality",
        "",
        f"| Metric | Language | Hansard | {baseline_name} | Direction |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for metric in HEADLINE_METRICS:
        for language in report_languages(report):
            values = report.metric_values_for(language)
            if values is None or metric not in values:
                continue
            lines.append(
                _comparison_row(
                    metric,
                    language,
                    values[metric],
                    _baseline_value(baseline_values, language, metric),
                )
            )
    return lines


def _breakdown_section(report: BenchmarkReport) -> list[str]:
    lines = [
        "",
        "## Results by dataset and language",
        "",
        "| Dataset | Language | Samples | Audio | cpWER | tcpWER | WDER | WER | CER | DER | RTF |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(_breakdown_row(slice_) for slice_ in report.dataset_slices)
    lines.extend(_breakdown_row(slice_) for slice_ in report.language_slices)
    return lines


def _system_section(report: BenchmarkReport, baseline: BaselineColumn | None) -> list[str]:
    baseline_name = baseline.name if baseline is not None else "Baseline"
    baseline_values = baseline.values if baseline is not None else {}
    values = report.metric_values
    lines = [
        "",
        "## System cost",
        "",
        f"| Metric | Hansard | {baseline_name} | Direction |",
        "| --- | ---: | ---: | --- |",
    ]
    lines.extend(
        _metric_row(metric, values[metric], _baseline_value(baseline_values, ALL_LANGUAGES, metric))
        for metric in SYSTEM_METRICS
        if metric in values
    )
    return lines


def _breakdown_row(slice_: CorpusSlice) -> str:
    corpus = slice_.corpus
    cells = " | ".join(
        (
            slice_.dataset,
            slice_.language,
            str(slice_.sample_count),
            _format_value("audio_seconds", slice_.audio_seconds),
            _format_value("cpwer", corpus.cpwer),
            _format_value("tcpwer", corpus.tcpwer),
            _format_value("wder", corpus.wder),
            _format_value("wer", corpus.wer),
            _format_value("cer", corpus.cer),
            _format_value("der", corpus.der),
            _format_value("rtf", slice_.real_time_factor.value),
        )
    )
    return f"| {cells} |"


def _comparison_row(metric: str, language: str, observed: float, baseline: float | None) -> str:
    label = _LABELS.get(metric, metric)
    direction = _DIRECTIONS.get(metric, LOWER_IS_BETTER)
    ours = _format_value(metric, observed)
    theirs = _format_value(metric, baseline)
    return f"| {label} | {language} | {ours} | {theirs} | {direction} |"


def _metric_row(metric: str, observed: float | None, baseline: float | None) -> str:
    label = _LABELS.get(metric, metric)
    direction = _DIRECTIONS.get(metric, LOWER_IS_BETTER)
    ours = _format_value(metric, observed)
    theirs = _format_value(metric, baseline)
    return f"| {label} | {ours} | {theirs} | {direction} |"


def _baseline_value(values: Mapping[str, float], language: str, metric: str) -> float | None:
    if language == ALL_LANGUAGES:
        return values.get(metric)
    return values.get(f"{language}:{metric}")


def _ordered_values(values: Mapping[str, float]) -> dict[str, float]:
    ordered = [name for name, _, _, _ in METRIC_SPECS if name in values]
    ordered.extend(sorted(set(values) - set(ordered)))
    return {name: values[name] for name in ordered}


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
        "| Metric | Language | Expectation | Observed | Tier | Status |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    lines.extend(_gate_row(result) for result in gates.results)
    lines.extend(["", f"Overall: {'PASS' if gates.passed else 'FAIL'}"])
    return lines


def _gate_row(result: GateResult) -> str:
    gate = result.gate
    label = _LABELS.get(gate.metric, gate.metric)
    observed = _UNAVAILABLE if result.observed is None else f"{result.observed:g}"
    cells = (label, gate.language, f"`{gate.expectation}`", observed, gate.tier, result.status)
    return "| " + " | ".join(cells) + " |"


def _sample_section(report: BenchmarkReport) -> list[str]:
    lines = [
        "",
        "## Per-sample results",
        "",
        "| Sample | Dataset | Language | Audio | WER | CER | cpWER | tcpWER | DER | RTF |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        _sample_row(sample)
        for sample in sorted(report.samples, key=lambda item: (item.dataset, item.language, item.identifier))
    )
    return lines


def _sample_row(sample: SampleOutcome) -> str:
    values = (
        sample.identifier,
        sample.dataset,
        sample.language,
        _format_value("audio_seconds", sample.audio_seconds),
        _format_value("wer", sample.wer),
        _format_value("cer", sample.cer),
        _format_value("cpwer", sample.cpwer),
        _format_value("tcpwer", sample.tcpwer),
        _format_value("der", sample.der),
        _format_value("rtf", sample.real_time_factor),
    )
    return "| " + " | ".join(values) + " |"
