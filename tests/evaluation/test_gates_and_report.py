import json
import re
from datetime import UTC, datetime

import pytest

from hansard.domain.errors import QualityGateFailed
from hansard.evaluation.gates import DEFAULT_GATES, QualityGate, evaluate_gates
from hansard.evaluation.harness import BenchmarkReport, CorpusMetrics, SampleOutcome
from hansard.evaluation.metrics.system import RealTimeFactor, ResourceUsage
from hansard.evaluation.report import BaselineColumn, render_json, render_markdown, report_to_dict


def build_report(wer=0.10, der=0.10, rtf=0.5):
    return BenchmarkReport(
        label="Hansard vs Copilot",
        engine="parakeet",
        generated_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        samples=(
            SampleOutcome(
                identifier="b",
                language="fr",
                audio_seconds=10.0,
                processing_seconds=5.0,
                reference_words=20,
                wer=wer,
                cer=0.05,
                cpwer=0.2,
                wder=0.05,
                der=der,
                jer=0.2,
                speaker_count_error=0,
            ),
            SampleOutcome(
                identifier="a",
                language="en",
                audio_seconds=10.0,
                processing_seconds=5.0,
                reference_words=20,
                wer=wer,
                cer=0.05,
            ),
        ),
        corpus=CorpusMetrics(
            wer=wer,
            cer=0.05,
            substitutions=2,
            deletions=1,
            insertions=1,
            reference_words=40,
            cpwer=0.2,
            wder=0.05,
            der=der,
            missed_speech_rate=0.04,
            false_alarm_rate=0.03,
            confusion_rate=0.03,
            jer=0.2,
            speaker_count_error=0.0,
        ),
        resources=ResourceUsage(wall_seconds=10.0, cpu_seconds=18.0, peak_rss_mb=1024.0, vram_mb=None),
        real_time_factor=RealTimeFactor(processing_seconds=10.0, audio_seconds=20.0),
    )


def test_metric_values_expose_every_reported_metric():
    values = build_report().metric_values
    assert values["wer"] == pytest.approx(0.10)
    assert values["rtf"] == pytest.approx(0.5)
    assert values["peak_rss_mb"] == pytest.approx(1024.0)
    assert "vram_mb" not in values


def test_default_gates_pass_on_a_healthy_report():
    outcome = evaluate_gates(build_report())
    assert outcome.passed
    assert outcome.failures == ()
    assert outcome.missing == ()
    outcome.raise_for_status()


def test_gates_detect_regressions():
    outcome = evaluate_gates(build_report(wer=0.30))
    assert not outcome.passed
    assert [result.gate.metric for result in outcome.failures] == ["wer"]
    assert outcome.failures[0].observed == pytest.approx(0.30)
    with pytest.raises(QualityGateFailed, match=re.escape("wer <= 0.15")):
        outcome.raise_for_status()


def test_stretch_gates_never_block():
    outcome = evaluate_gates(build_report(wer=0.10))
    assert outcome.passed
    assert [result.gate.metric for result in outcome.stretch_failures] == ["wer", "cpwer", "der", "rtf"]


def test_missing_metrics_are_reported_not_silently_passed():
    gates = (QualityGate("action_item_f1", ">=", 0.7, "must_pass"),)
    outcome = evaluate_gates(build_report(), gates)
    assert outcome.missing[0].status == "missing"
    assert not outcome.passed


def test_default_gate_set_is_ordered_and_typed():
    assert all(gate.tier in {"must_pass", "stretch"} for gate in DEFAULT_GATES)
    assert DEFAULT_GATES[0].metric == "wer"


def test_json_report_is_deterministic_and_parsable():
    report = build_report()
    first = render_json(report)
    assert first == render_json(report)
    payload = json.loads(first)
    assert payload["engine"] == "parakeet"
    assert payload["generated_at"] == "2026-03-01T12:00:00+00:00"
    assert payload["metrics"]["wer"] == pytest.approx(0.10)
    assert [sample["identifier"] for sample in payload["samples"]] == ["b", "a"]


def test_json_report_includes_gate_outcome():
    report = build_report(wer=0.30)
    payload = report_to_dict(report, evaluate_gates(report))
    assert payload["gates_passed"] is False
    assert payload["gates"][0]["status"] == "failed"


def test_markdown_table_compares_against_a_baseline():
    report = build_report()
    baseline = BaselineColumn(
        name="Microsoft Copilot",
        values={"wer": 0.14, "der": 0.18},
        note="Published vendor figures, not reproduced locally.",
    )
    markdown = render_markdown(report, baseline, evaluate_gates(report), include_samples=True)
    assert markdown == render_markdown(report, baseline, evaluate_gates(report), include_samples=True)
    assert "| Metric | Hansard | Microsoft Copilot | Direction |" in markdown
    assert "| Word error rate | 10.00 % | 14.00 % | lower is better |" in markdown
    assert "| Diarization error rate | 10.00 % | 18.00 % | lower is better |" in markdown
    assert "| GPU memory | n/a | n/a | lower is better |" not in markdown
    assert "## Quality gates" in markdown
    assert "> Published vendor figures, not reproduced locally." in markdown
    sample_rows = [line for line in markdown.splitlines() if line.startswith(("| a |", "| b |"))]
    assert sample_rows[0].startswith("| a |")


def test_markdown_without_baseline_marks_unknown_values():
    markdown = render_markdown(build_report())
    assert "| Metric | Hansard | Baseline | Direction |" in markdown
    assert "| Word error rate | 10.00 % | n/a | lower is better |" in markdown
