from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from hansard.adapters.asr.onnx_engine import OnnxRecognizer
from hansard.adapters.audio import load_clip
from hansard.config import Settings
from hansard.domain.meeting import MeetingRequest
from hansard.evaluation.datasets import load_manifest, load_reference_json
from hansard.evaluation.metrics.speaker import (
    concatenated_minimum_permutation_wer,
    diarization_error_rate,
    jaccard_error_rate,
    time_constrained_cpwer,
    word_diarization_error_rate,
)
from hansard.evaluation.metrics.system import ResourceProbe
from hansard.evaluation.metrics.text import word_error_rate
from hansard.evaluation.normalizers import NORMALIZER_VERSION, normalizer_for
from hansard.factory import Composition
from hansard.ports.asr import RecognitionHints

DEFAULT_DATA_DIR = Path("bench/data")

ASR_CORPORA: tuple[tuple[str, str, str], ...] = (
    ("fleurs_fr.jsonl", "fr", "FLEURS fr_fr (read speech)"),
    ("fleurs_en.jsonl", "en", "FLEURS en_us (read speech)"),
    ("librispeech_dummy.jsonl", "en", "LibriSpeech dev-clean (read speech)"),
)

MEETING_FIXTURES: tuple[str, ...] = ("meeting_3spk", "meeting_6spk", "meeting_9spk")


@dataclass(frozen=True, slots=True)
class RunOptions:
    data_dir: Path
    output: Path
    threads: int
    language: str | None = None


def _percent(value: float) -> float:
    return round(value * 100, 2)


def run_asr(options: RunOptions) -> dict[str, object]:
    engine = OnnxRecognizer(quantization="int8", batch_size=4, intra_op_threads=options.threads)
    engine.warm_up()
    rows: list[dict[str, object]] = []
    for filename, language, label in ASR_CORPORA:
        manifest = options.data_dir / filename
        if not manifest.exists():
            continue
        if options.language and options.language != language:
            continue
        samples = load_manifest(manifest)
        normalizer = normalizer_for(language)
        references: list[str] = []
        hypotheses: list[str] = []
        audio_seconds = 0.0
        with ResourceProbe() as probe:
            started = time.perf_counter()
            for sample in samples:
                clip = load_clip(Path(str(sample.audio_path)))
                audio_seconds += clip.duration
                transcript = engine.transcribe(clip, RecognitionHints(language=language))
                references.append(sample.reference.text)
                hypotheses.append(transcript.text)
            elapsed = time.perf_counter() - started
        result = word_error_rate(references, hypotheses, normalizer)
        rows.append(
            {
                "dataset": label,
                "language": language,
                "utterances": len(samples),
                "audio_seconds": round(audio_seconds, 1),
                "wer_percent": _percent(result.wer),
                "cer_percent": _percent(result.cer),
                "substitutions": result.substitutions,
                "deletions": result.deletions,
                "insertions": result.insertions,
                "real_time_factor": round(elapsed / audio_seconds, 4) if audio_seconds else None,
                "speedup": round(audio_seconds / elapsed, 1) if elapsed else None,
                "peak_rss_mb": round(probe.usage.peak_rss_mb, 1),
            }
        )
    return {
        "benchmark": "asr",
        "model": "nemo-parakeet-tdt-0.6b-v3 int8 ONNX",
        "normalizer_version": NORMALIZER_VERSION,
        "rows": rows,
    }


def run_meetings(options: RunOptions) -> dict[str, object]:
    settings = Settings()
    settings.asr.intra_op_threads = options.threads
    rows: list[dict[str, object]] = []
    for name in MEETING_FIXTURES:
        reference_path = options.data_dir / "synthetic" / f"{name}.ref.json"
        if not reference_path.exists():
            continue
        sample = load_reference_json(reference_path, "en", "synthetic")
        reference_diarization = sample.reference_diarization
        if reference_diarization is None:
            continue
        clip = load_clip(Path(str(sample.audio_path)))
        pipeline = Composition(settings).pipeline()
        request = MeetingRequest(audio_path=Path(str(sample.audio_path)), title=name, language="en")
        with ResourceProbe() as probe:
            outcome = pipeline.run(clip, request)
        normalizer = normalizer_for("en")
        reference = sample.reference
        hypothesis = outcome.transcript
        strict = diarization_error_rate(reference_diarization, outcome.diarization, collar=0.0)
        lenient = diarization_error_rate(reference_diarization, outcome.diarization, collar=0.25)
        rows.append(
            {
                "meeting": name,
                "duration_seconds": round(clip.duration, 1),
                "reference_speakers": len({turn.label for turn in reference_diarization.turns}),
                "detected_speakers": outcome.diarization.speaker_count,
                "wer_percent": _percent(word_error_rate(reference.text, hypothesis.text, normalizer).wer),
                "cpwer_percent": _percent(
                    concatenated_minimum_permutation_wer(reference, hypothesis, normalizer).wer
                ),
                "tcpwer_percent": _percent(
                    time_constrained_cpwer(reference, hypothesis, normalizer, collar=5.0).wer
                ),
                "wder_percent": _percent(word_diarization_error_rate(reference, hypothesis, normalizer)),
                "der_percent": _percent(strict.der),
                "der_collar_percent": _percent(lenient.der),
                "jer_percent": _percent(jaccard_error_rate(reference_diarization, outcome.diarization).jer),
                "der_missed_percent": _percent(strict.missed_rate),
                "der_false_alarm_percent": _percent(strict.false_alarm_rate),
                "der_confusion_percent": _percent(strict.confusion_rate),
                "real_time_factor": round(outcome.real_time_factor, 4),
                "speedup": round(1 / outcome.real_time_factor, 1) if outcome.real_time_factor else None,
                "peak_rss_mb": round(probe.usage.peak_rss_mb, 1),
                "stage_seconds": outcome.stage_seconds,
            }
        )
    return {
        "benchmark": "meetings",
        "normalizer_version": NORMALIZER_VERSION,
        "rows": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hansard-bench")
    parser.add_argument("benchmark", choices=("asr", "meetings"))
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--language", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    options = RunOptions(
        data_dir=arguments.data_dir,
        output=arguments.output or Path(f"bench/results/{arguments.benchmark}.json"),
        threads=arguments.threads,
        language=arguments.language,
    )
    report = run_asr(options) if arguments.benchmark == "asr" else run_meetings(options)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = report.get("rows")
    if isinstance(rows, list):
        for row in rows:
            print(json.dumps(row))
    print(f"wrote {options.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
