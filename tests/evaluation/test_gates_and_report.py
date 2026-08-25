import json
import re
from datetime import UTC, datetime

import pytest

from hansard.domain.errors import QualityGateFailed
from hansard.evaluation.gates import (
    DEFAULT_GATES,
    READ_SPEECH_GATES,
    QualityGate,
    evaluate_gates,
    gates_for,
)
from hansard.evaluation.harness import BenchmarkReport, CorpusMetrics, CorpusSlice, SampleOutcome
from hansard.evaluation.metrics.system import RealTimeFactor, ResourceUsage
from hansard.evaluation.normalizers import NORMALIZER_VERSION
from hansard.evaluation.report import (
    COPILOT_BASELINE,
    BaselineColumn,
    render_json,
    render_markdown,
    report_to_dict,
)


def corpus(wer, der=None, cpwer=0.2, tcpwer=0.22):
    return CorpusMetrics(
        wer=wer,
        cer=0.05,
        substitutions=2,
        deletions=1,
        insertions=1,
        reference_words=40,
        cpwer=cpwer,
        tcpwer=tcpwer,
        wder=0.05,
        der=der,
        missed_speech_rate=0.04 if der is not None else None,
        false_alarm_rate=0.03 if der is not None else None,
        confusion_rate=0.03 if der is not None else None,
        jer=0.2 if der is not None else None,
        speaker_count_error=0.0 if der is not None else None,
    )


def outcome(identifier, dataset, language, wer, der=None):
    return SampleOutcome(
        identifier=identifier,
        dataset=dataset,
        language=language,
        audio_seconds=10.0,
        processing_seconds=5.0,
        reference_words=20,
        wer=wer,
        cer=0.05,
        cpwer=0.2,
        tcpwer=0.22,
        wder=0.05,
        der=der,
        jer=0.2 if der is not None else None,
        speaker_count_error=0 if der is not None else None,
    )


def build_report(french_wer=0.18, english_wer=0.10, der=0.10):
    slices = (
        CorpusSlice("meetings-en", "en", 1, 10.0, 5.0, corpus(english_wer, der)),
        CorpusSlice("meetings-fr", "fr", 1, 10.0, 5.0, corpus(french_wer, der)),
    )
    languages = (
        CorpusSlice("all", "en", 1, 10.0, 5.0, corpus(english_wer, der)),
        CorpusSlice("all", "fr", 1, 10.0, 5.0, corpus(french_wer, der)),
    )
    return BenchmarkReport(
        label="Hansard vs Copilot",
        engine="parakeet",
        generated_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        samples=(
            outcome("b", "meetings-fr", "fr", french_wer, der),
            outcome("a", "meetings-en", "en", english_wer, der),
        ),
        corpus=corpus((french_wer + english_wer) / 2, der),
        resources=ResourceUsage(wall_seconds=10.0, cpu_seconds=18.0, peak_rss_mb=1024.0, vram_mb=None),
        real_time_factor=RealTimeFactor(processing_seconds=10.0, audio_seconds=20.0),
        dataset_slices=slices,
        language_slices=languages,
    )


def test_metric_values_expose_every_reported_metric():
    values = build_report().metric_values
    assert values["wer"] == pytest.approx(0.14)
    assert values["rtf"] == pytest.approx(0.5)
    assert values["peak_rss_mb"] == pytest.approx(1024.0)
    assert "vram_mb" not in values


def test_default_gates_pass_on_a_healthy_report():
    outcome = evaluate_gates(build_report())
    assert outcome.passed
    assert outcome.failures == ()
    assert outcome.missing == ()
    outcome.raise_for_status()


def test_gates_detect_regressions_per_language():
    result = evaluate_gates(build_report(french_wer=0.30))
    assert not result.passed
    assert [(item.gate.language, item.gate.metric) for item in result.failures] == [("fr", "wer")]
    assert result.failures[0].observed == pytest.approx(0.30)
    with pytest.raises(QualityGateFailed, match=re.escape("fr:wer <= 0.2")):
        result.raise_for_status()


def test_english_only_runs_fail_the_french_gates():
    report = build_report()
    english_only = BenchmarkReport(
        label=report.label,
        engine=report.engine,
        generated_at=report.generated_at,
        samples=report.samples[1:],
        corpus=report.corpus,
        resources=report.resources,
        real_time_factor=report.real_time_factor,
        dataset_slices=report.dataset_slices[:1],
        language_slices=report.language_slices[:1],
    )
    result = evaluate_gates(english_only)
    assert not result.passed
    assert {item.gate.language for item in result.missing} == {"fr"}


def test_gates_for_selects_a_language():
    assert {gate.language for gate in gates_for("fr")} == {"fr"}
    assert {gate.metric for gate in gates_for("en")} >= {"cpwer", "tcpwer", "wder", "wer"}


def test_read_speech_gates_are_stricter_than_meeting_gates():
    read_speech = {(gate.language, gate.metric): gate.threshold for gate in READ_SPEECH_GATES}
    meetings = {(gate.language, gate.metric): gate.threshold for gate in DEFAULT_GATES}
    assert read_speech[("fr", "wer")] < meetings[("fr", "wer")]
    assert read_speech[("en", "wer")] < meetings[("en", "wer")]


def test_stretch_gates_never_block():
    result = evaluate_gates(build_report())
    assert result.passed
    assert {item.gate.metric for item in result.stretch_failures} >= {"wer", "der"}


def test_missing_metrics_are_reported_not_silently_passed():
    gates = (QualityGate("action_item_f1", ">=", 0.7, "must_pass"),)
    result = evaluate_gates(build_report(), gates)
    assert result.missing[0].status == "missing"
    assert not result.passed


def test_default_gate_set_covers_both_languages_and_leads_with_cpwer():
    assert all(gate.tier in {"must_pass", "stretch"} for gate in DEFAULT_GATES)
    assert DEFAULT_GATES[0].metric == "cpwer"
    assert {gate.language for gate in DEFAULT_GATES} == {"en", "fr", "all"}


def test_json_report_is_deterministic_and_parsable():
    report = build_report()
    first = render_json(report)
    assert first == render_json(report)
    payload = json.loads(first)
    assert payload["engine"] == "parakeet"
    assert payload["generated_at"] == "2026-03-01T12:00:00+00:00"
    assert payload["normalizer_version"] == NORMALIZER_VERSION
    assert payload["metrics"]["wer"] == pytest.approx(0.14)
    assert list(payload["metrics_by_language"]) == ["en", "fr"]
    assert payload["metrics_by_language"]["fr"]["wer"] == pytest.approx(0.18)
    assert list(payload["metrics_by_dataset"]) == ["meetings-en:en", "meetings-fr:fr"]
    assert [sample["identifier"] for sample in payload["samples"]] == ["b", "a"]


def test_json_report_includes_gate_outcome():
    report = build_report(french_wer=0.30)
    payload = report_to_dict(report, evaluate_gates(report))
    assert payload["gates_passed"] is False
    assert {gate["language"] for gate in payload["gates"]} == {"en", "fr", "all"}


def test_markdown_reports_every_language_side_by_side():
    report = build_report()
    baseline = BaselineColumn(
        name="Microsoft Copilot",
        values={"en:wer": 0.1154, "en:cpwer": 0.2739, "wer": 0.1154},
        note="Published vendor figures, English only.",
    )
    markdown = render_markdown(report, baseline, evaluate_gates(report), include_samples=True)
    assert markdown == render_markdown(report, baseline, evaluate_gates(report), include_samples=True)
    assert f"- Normalizer version: `{NORMALIZER_VERSION}`" in markdown
    assert "- Languages: en, fr" in markdown
    assert "| Word error rate | en | 10.00 % | 11.54 % | lower is better |" in markdown
    assert "| Word error rate | fr | 18.00 % | n/a | lower is better |" in markdown
    assert "| Word error rate | all | 14.00 % | 11.54 % | lower is better |" in markdown
    assert "| meetings-fr | fr | 1 | 10.0 s | 20.00 % | 22.00 % | 5.00 % | 18.00 %" in markdown
    assert "## Results by dataset and language" in markdown
    assert "## Quality gates" in markdown
    assert "> Published vendor figures, English only." in markdown


def test_markdown_leads_with_the_primary_metric():
    markdown = render_markdown(build_report())
    headline = markdown[markdown.index("## Headline quality") :]
    assert headline.index("Concatenated minimum-permutation WER") < headline.index("Word error rate")


def test_shipped_copilot_baseline_has_no_french_number():
    assert "fr:wer" not in COPILOT_BASELINE.values
    assert "fr:cpwer" not in COPILOT_BASELINE.values
    assert COPILOT_BASELINE.values["en:cpwer"] == pytest.approx(0.2739)
    assert "2.4 %" in COPILOT_BASELINE.note


def test_markdown_without_baseline_marks_unknown_values():
    markdown = render_markdown(build_report())
    assert "| Metric | Language | Hansard | Baseline | Direction |" in markdown
    assert "| Word error rate | fr | 18.00 % | n/a | lower is better |" in markdown
