from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from hansard.adapters.asr.registry import build_recognizer
from hansard.adapters.audio import load_clip
from hansard.config import Settings
from hansard.domain.language import MIXED
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Diarization
from hansard.domain.transcript import Transcript
from hansard.evaluation.ami import discover_meetings
from hansard.evaluation.corpora import (
    SUMM_RE_LANGUAGE,
    SUMM_RE_SPLITS,
    meeting_diarization,
    meeting_transcript,
    read_meeting,
    summ_re_split,
)
from hansard.evaluation.datasets import load_manifest, load_reference_json
from hansard.evaluation.metrics.decomposition import decompose, sentence_joined
from hansard.evaluation.metrics.language import language_identification
from hansard.evaluation.metrics.quiet import quiet_speaker_report
from hansard.evaluation.metrics.speaker import (
    concatenated_minimum_permutation_wer,
    diarization_error_rate,
    jaccard_error_rate,
    overlap_ratio,
    time_constrained_cpwer,
    word_diarization_error_rate,
)
from hansard.evaluation.metrics.system import ResourceProbe
from hansard.evaluation.metrics.text import word_error_rate
from hansard.evaluation.normalizers import NORMALIZER_VERSION, normalizer_for
from hansard.evaluation.shootout import (
    ami_segments,
    budgeted,
    preset,
    run_shootout,
    shootout_payload,
    summ_re_segments,
)
from hansard.evaluation.sweep import SweepMeeting, SweepPoint, run_sweep
from hansard.factory import Composition
from hansard.ports.asr import RecognitionHints

DEFAULT_DATA_DIR = Path("bench/data")

ASR_CORPORA: tuple[tuple[str, str, str], ...] = (
    ("fleurs_fr.jsonl", "fr", "FLEURS fr_fr (read speech)"),
    ("fleurs_en.jsonl", "en", "FLEURS en_us (read speech)"),
    ("librispeech_dummy.jsonl", "en", "LibriSpeech dev-clean (read speech)"),
)

MEETING_FIXTURES: tuple[tuple[str, str], ...] = (
    ("meeting_3spk", "en"),
    ("meeting_6spk", "en"),
    ("meeting_9spk", "en"),
    ("meeting_fr_3spk", "fr"),
    ("meeting_fr_6spk", "fr"),
    ("meeting_fr_9spk", "fr"),
    ("meeting_mixed_4spk", MIXED),
    ("meeting_mixed_6spk", MIXED),
    ("meeting_mixed_8spk", MIXED),
    ("meeting_mixed_5spk_heldout", MIXED),
    ("meeting_mixed_7spk_heldout", MIXED),
)
AMI_CONDITION = "Mix-Headset"


@dataclass(frozen=True, slots=True)
class RunOptions:
    data_dir: Path
    output: Path
    threads: int
    language: str | None = None
    roster: bool = False
    corpus: str = "summ-re"
    engines: tuple[str, ...] = ()
    seconds: float = 0.0
    split: str | None = None
    transcripts: Path | None = None
    minimum_segment_seconds: float = 0.4
    points: tuple[str, ...] = ()
    meetings: tuple[str, ...] = ()
    cache: Path = Path("bench/cache")


def _percent(value: float) -> float:
    return round(value * 100, 2)


def _recognition_profile(settings: Settings) -> dict[str, object]:
    quantization = settings.asr.quantization
    return {
        "model_id": settings.asr.model_id,
        "precision": "float32" if quantization == "none" else quantization,
        "batch_size": settings.asr.batch_size,
        "batch_seconds": settings.asr.batch_seconds,
        "max_segment_seconds": settings.audio.max_segment_seconds,
        "merge_similarity": settings.diarization.merge_similarity,
        "minimum_speaker_seconds": settings.diarization.minimum_speaker_seconds,
    }


def run_asr(options: RunOptions) -> dict[str, object]:
    settings = Settings()
    settings.asr.intra_op_threads = options.threads
    engine = build_recognizer(settings.asr, settings.runtime.models_dir)
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
    profile = _recognition_profile(settings)
    return {
        "benchmark": "asr",
        "model": f"{settings.asr.model_id} {profile['precision']} ONNX",
        "recognition": profile,
        "normalizer_version": NORMALIZER_VERSION,
        "rows": rows,
    }


def run_meetings(options: RunOptions) -> dict[str, object]:
    settings = Settings()
    settings.asr.intra_op_threads = options.threads
    rows: list[dict[str, object]] = []
    for name, language in MEETING_FIXTURES:
        if options.language and options.language != language:
            continue
        reference_path = options.data_dir / "synthetic" / f"{name}.ref.json"
        if not reference_path.exists():
            continue
        sample = load_reference_json(reference_path, language, "synthetic")
        reference_diarization = sample.reference_diarization
        if reference_diarization is None:
            continue
        clip = load_clip(Path(str(sample.audio_path)))
        pipeline = Composition(settings).pipeline()
        request = MeetingRequest(
            audio_path=Path(str(sample.audio_path)),
            title=name,
            language=None if language == MIXED else language,
        )
        with ResourceProbe() as probe:
            outcome = pipeline.run(clip, request)
        normalizer = normalizer_for(language)
        reference = sample.reference
        hypothesis = outcome.transcript
        scored = word_error_rate(reference.text, hypothesis.text, normalizer)
        identified = language_identification(hypothesis, reference)
        strict = diarization_error_rate(reference_diarization, outcome.diarization, collar=0.0)
        lenient = diarization_error_rate(reference_diarization, outcome.diarization, collar=0.25)
        rows.append(
            {
                "meeting": name,
                "language": language,
                "duration_seconds": round(clip.duration, 1),
                "reference_speakers": len({turn.label for turn in reference_diarization.turns}),
                "detected_speakers": outcome.diarization.speaker_count,
                "reference_words": reference.word_count,
                "hypothesis_words": hypothesis.word_count,
                "wer_percent": _percent(scored.wer),
                "cer_percent": _percent(scored.cer),
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
                "reference_overlap_percent": _percent(overlap_ratio(reference_diarization)),
                "speakers": quiet_speaker_report(
                    reference, hypothesis, reference_diarization, outcome.diarization, normalizer
                ).as_dict(),
                "decomposition": decompose(
                    normalizer.normalize(reference.text),
                    normalizer.normalize(hypothesis.text),
                    language if language != MIXED else "fr",
                    reference.text,
                ).as_dict(),
                "language_accuracy_percent": _percent(identified.accuracy),
                "detected_languages": list(hypothesis.language_profile.significant),
                "language_confusions": [
                    {"expected": expected, "observed": observed, "words": words}
                    for expected, observed, words in identified.confusions
                ],
                "real_time_factor": round(outcome.real_time_factor, 4),
                "speedup": round(1 / outcome.real_time_factor, 1) if outcome.real_time_factor else None,
                "peak_rss_mb": round(probe.usage.peak_rss_mb, 1),
                "stage_seconds": outcome.stage_seconds,
            }
        )
    return {
        "benchmark": "meetings",
        "recognition": _recognition_profile(settings),
        "normalizer_version": NORMALIZER_VERSION,
        "rows": rows,
    }


def _score_corpus_meeting(
    settings: Settings,
    identifier: str,
    audio_path: Path,
    reference: Transcript,
    reference_diarization: Diarization,
    language: str,
    roster: bool = False,
) -> dict[str, object]:
    normalizer = normalizer_for(language)
    clip = load_clip(audio_path)
    speakers = sorted({turn.label for turn in reference_diarization.turns})
    pipeline = Composition(settings).pipeline()
    request = MeetingRequest(
        audio_path=audio_path,
        title=identifier,
        language=language,
        expected_participants=tuple(speakers) if roster else (),
    )
    started = time.perf_counter()
    with ResourceProbe() as probe:
        outcome = pipeline.run(clip, request)
    elapsed = time.perf_counter() - started
    hypothesis = outcome.transcript
    scored = word_error_rate(reference.text, hypothesis.text, normalizer)
    strict = diarization_error_rate(reference_diarization, outcome.diarization, collar=0.0)
    lenient = diarization_error_rate(reference_diarization, outcome.diarization, collar=0.25)
    return {
        "meeting": identifier,
        "language": language,
        "roster": roster,
        "duration_minutes": round(clip.duration / 60, 1),
        "reference_speakers": len(speakers),
        "detected_speakers": outcome.diarization.speaker_count,
        "reference_words": reference.word_count,
        "hypothesis_words": hypothesis.word_count,
        "wer_percent": _percent(scored.wer),
        "cer_percent": _percent(scored.cer),
        "cpwer_percent": _percent(
            concatenated_minimum_permutation_wer(reference, hypothesis, normalizer).wer
        ),
        "tcpwer_percent": _percent(time_constrained_cpwer(reference, hypothesis, normalizer, collar=5.0).wer),
        "wder_percent": _percent(word_diarization_error_rate(reference, hypothesis, normalizer)),
        "der_percent": _percent(strict.der),
        "der_collar_percent": _percent(lenient.der),
        "jer_percent": _percent(jaccard_error_rate(reference_diarization, outcome.diarization).jer),
        "der_missed_percent": _percent(strict.missed_rate),
        "der_false_alarm_percent": _percent(strict.false_alarm_rate),
        "der_confusion_percent": _percent(strict.confusion_rate),
        "reference_overlap_percent": _percent(overlap_ratio(reference_diarization)),
        "speakers": quiet_speaker_report(
            reference, hypothesis, reference_diarization, outcome.diarization, normalizer
        ).as_dict(),
        "decomposition": decompose(
            normalizer.normalize(reference.text),
            normalizer.normalize(hypothesis.text),
            language if language != MIXED else "fr",
            sentence_joined(utterance.text for utterance in reference.utterances),
        ).as_dict(),
        "real_time_factor": round(elapsed / clip.duration, 4),
        "peak_rss_mb": round(probe.usage.peak_rss_mb, 1),
        "stage_seconds": outcome.stage_seconds,
    }


def run_ami(options: RunOptions) -> dict[str, object]:
    audio_root = options.data_dir / "ami"
    annotations = audio_root / "annotations"
    settings = Settings()
    settings.asr.intra_op_threads = options.threads
    rows: list[dict[str, object]] = []
    for meeting in discover_meetings(audio_root, annotations):
        row = _score_corpus_meeting(
            settings,
            meeting.identifier,
            meeting.audio_path,
            meeting.reference,
            meeting.diarization,
            "en",
            options.roster,
        )
        row["condition"] = AMI_CONDITION
        rows.append(row)
    return {
        "benchmark": "ami",
        "profile": "roster" if options.roster else "default",
        "condition": AMI_CONDITION,
        "recognition": _recognition_profile(settings),
        "normalizer_version": NORMALIZER_VERSION,
        "rows": rows,
        "summary": _aggregate(rows),
    }


def run_summ_re(options: RunOptions) -> dict[str, object]:
    root = options.data_dir / "summ-re"
    settings = Settings()
    settings.asr.intra_op_threads = options.threads
    rows: list[dict[str, object]] = []
    if not root.is_dir():
        return {"benchmark": "summ-re", "normalizer_version": NORMALIZER_VERSION, "rows": rows}
    for directory in sorted(item for item in root.iterdir() if item.is_dir()):
        if options.meetings and directory.name not in options.meetings:
            continue
        if options.split is not None and summ_re_split(directory.name) != options.split:
            continue
        meeting = read_meeting(directory)
        if meeting.mixed_audio is None:
            continue
        rows.append(
            _score_corpus_meeting(
                settings,
                meeting.identifier,
                meeting.mixed_audio,
                meeting_transcript(meeting),
                meeting_diarization(meeting),
                SUMM_RE_LANGUAGE,
                options.roster,
            )
        )
    return {
        "benchmark": "summ-re",
        "profile": "roster" if options.roster else "default",
        "condition": "mixed headsets",
        "recognition": _recognition_profile(settings),
        "normalizer_version": NORMALIZER_VERSION,
        "rows": rows,
        "summary": _aggregate(rows),
    }


def _numeric(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    return float(value) if isinstance(value, int | float) else 0.0


def _aggregate(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {}
    metrics = (
        "wer_percent",
        "cpwer_percent",
        "tcpwer_percent",
        "wder_percent",
        "der_percent",
        "der_collar_percent",
        "jer_percent",
        "reference_overlap_percent",
    )
    macro = {key: round(sum(_numeric(row, key) for row in rows) / len(rows), 2) for key in metrics}
    weights = [_numeric(row, "reference_words") for row in rows]
    total = sum(weights) or 1.0
    pairs = zip(rows, weights, strict=True)
    weighted = sum(_numeric(row, "cpwer_percent") * weight for row, weight in pairs)
    return {
        "meetings": len(rows),
        "total_minutes": round(sum(_numeric(row, "duration_minutes") for row in rows), 1),
        "macro_average": macro,
        "word_weighted_cpwer_percent": round(weighted / total, 2),
    }


def run_shootout_benchmark(options: RunOptions) -> dict[str, object]:
    settings = Settings()
    settings.asr.intra_op_threads = options.threads
    if options.corpus == "ami":
        segments = ami_segments(options.data_dir / "ami", options.data_dir / "ami" / "annotations")
        if options.meetings:
            segments = tuple(item for item in segments if item.meeting in options.meetings)
    else:
        segments = summ_re_segments(
            options.data_dir / "summ-re",
            minimum_seconds=options.minimum_segment_seconds,
            split=options.split,
            meetings=options.meetings or None,
        )
    selected = budgeted(segments, options.seconds)
    specs = tuple(preset(name) for name in options.engines) or (preset("parakeet-fp32"),)
    outcomes = run_shootout(
        specs,
        selected,
        settings.runtime.models_dir,
        threads=options.threads,
        transcripts_dir=options.transcripts,
    )
    return shootout_payload(outcomes, selected, options.corpus, settings)


def sweep_meetings(options: RunOptions) -> tuple[SweepMeeting, ...]:
    if options.corpus == "ami":
        audio_root = options.data_dir / "ami"
        return tuple(
            SweepMeeting(
                identifier=meeting.identifier,
                audio=meeting.audio_path,
                language="en",
                reference=meeting.reference,
                reference_diarization=meeting.diarization,
            )
            for meeting in discover_meetings(audio_root, audio_root / "annotations")
        )
    root = options.data_dir / "summ-re"
    if not root.is_dir():
        return ()
    meetings: list[SweepMeeting] = []
    for directory in sorted(item for item in root.iterdir() if item.is_dir()):
        if options.meetings and directory.name not in options.meetings:
            continue
        if options.split is not None and summ_re_split(directory.name) != options.split:
            continue
        meeting = read_meeting(directory)
        if meeting.mixed_audio is None:
            continue
        meetings.append(
            SweepMeeting(
                identifier=meeting.identifier,
                audio=meeting.mixed_audio,
                language=SUMM_RE_LANGUAGE,
                reference=meeting_transcript(meeting),
                reference_diarization=meeting_diarization(meeting),
            )
        )
    return tuple(meetings)


def run_diarization_sweep(options: RunOptions) -> dict[str, object]:
    settings = Settings()
    settings.asr.intra_op_threads = options.threads
    points = tuple(_sweep_point(entry) for entry in options.points) or (SweepPoint(label="default"),)
    report = run_sweep(sweep_meetings(options), points, settings, options.cache)
    report["corpus"] = options.corpus
    report["split"] = options.split or "all"
    return report


def _sweep_point(entry: str) -> SweepPoint:
    label, separator, body = entry.partition(":")
    if not separator:
        body, label = entry, entry
    overrides: dict[str, object] = {}
    for pair in body.split(","):
        if not pair:
            continue
        key, _, raw = pair.partition("=")
        overrides[key.strip()] = _sweep_value(raw.strip())
    return SweepPoint(label=label, overrides=overrides)


def _sweep_value(raw: str) -> object:
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return float(raw)
    except ValueError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hansard-bench")
    parser.add_argument(
        "benchmark", choices=("asr", "meetings", "ami", "summ-re", "shootout", "diarization-sweep")
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--language", default=None)
    parser.add_argument(
        "--roster",
        action="store_true",
        help="supply the speakers as a participant list, as a Teams meeting would",
    )
    parser.add_argument("--corpus", default="summ-re", choices=("summ-re", "ami"))
    parser.add_argument("--engines", default="", help="comma separated shootout engine presets")
    parser.add_argument(
        "--seconds", type=float, default=0.0, help="audio budget per engine, 0 for everything"
    )
    parser.add_argument("--split", default=None, choices=SUMM_RE_SPLITS)
    parser.add_argument("--transcripts", type=Path, default=None)
    parser.add_argument(
        "--min-segment-seconds",
        type=float,
        default=0.4,
        help="drop reference segments shorter than this from the shootout",
    )
    parser.add_argument(
        "--point",
        action="append",
        default=[],
        help="a sweep point, as label:key=value,key=value",
    )
    parser.add_argument("--cache", type=Path, default=Path("bench/cache"))
    parser.add_argument(
        "--meetings", default="", help="comma separated meeting identifiers to restrict the run to"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    options = RunOptions(
        data_dir=arguments.data_dir,
        output=arguments.output or Path(f"bench/results/{arguments.benchmark}.json"),
        threads=arguments.threads,
        language=arguments.language,
        roster=arguments.roster,
        corpus=arguments.corpus,
        engines=tuple(name for name in arguments.engines.split(",") if name),
        seconds=arguments.seconds,
        split=arguments.split,
        transcripts=arguments.transcripts,
        minimum_segment_seconds=arguments.min_segment_seconds,
        points=tuple(arguments.point),
        cache=arguments.cache,
        meetings=tuple(name for name in arguments.meetings.split(",") if name),
    )
    runners = {
        "asr": run_asr,
        "meetings": run_meetings,
        "ami": run_ami,
        "summ-re": run_summ_re,
        "shootout": run_shootout_benchmark,
        "diarization-sweep": run_diarization_sweep,
    }
    report = runners[arguments.benchmark](options)
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
