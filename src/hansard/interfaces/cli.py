from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from hansard import __version__
from hansard.adapters.asr.biasing import VocabularyBiaser
from hansard.adapters.audio import load_clip
from hansard.config import Settings, load_settings
from hansard.domain.meeting import MeetingRequest
from hansard.factory import Composition

application = typer.Typer(
    name="hansard",
    help="Sovereign, self-hosted meeting transcription and minutes. Nothing leaves your machine.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _settings(overrides: dict[str, object]) -> Settings:
    settings = load_settings()
    for key, value in overrides.items():
        if value is None:
            continue
        section, _, field = key.partition(".")
        setattr(getattr(settings, section), field, value)
    return settings


@application.command()
def version() -> None:
    console.print(f"hansard {__version__}")


@application.command()
def doctor() -> None:
    settings = load_settings()
    table = Table(title="Hansard environment", show_lines=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    ffmpeg = shutil.which("ffmpeg")
    table.add_row("ffmpeg", "ok" if ffmpeg else "missing", ffmpeg or "install ffmpeg to decode audio")
    models = settings.runtime.models_dir
    table.add_row(
        "models directory",
        "ok" if models.is_dir() else "missing",
        str(models),
    )
    for probe, label in (("onnxruntime", "ONNX runtime"), ("sherpa_onnx", "diarization runtime")):
        try:
            __import__(probe)
            table.add_row(label, "ok", probe)
        except ImportError:
            table.add_row(label, "missing", f"pip install hansard[{'asr-onnx' if probe == 'onnxruntime' else 'diarization'}]")
    table.add_row("telemetry", "disabled", "Hansard never sends data anywhere")
    console.print(table)


@application.command()
def transcribe(
    audio: Annotated[Path, typer.Argument(help="Audio or video file to transcribe")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Directory for artefacts")] = None,
    language: Annotated[str | None, typer.Option("--language", "-l", help="fr, en, ... or omit to autodetect")] = None,
    formats: Annotated[str, typer.Option("--format", "-f", help="Comma-separated output formats")] = "markdown,json,vtt",
    vocabulary: Annotated[Path | None, typer.Option("--vocabulary", help="File with one boost phrase per line")] = None,
    speakers: Annotated[int | None, typer.Option("--speakers", help="Known number of participants")] = None,
    title: Annotated[str, typer.Option("--title", help="Meeting title")] = "Meeting",
) -> None:
    from hansard.rendering.registry import renderer_for
    from hansard.rendering.ports import RenderContext

    settings = _settings({"asr.language": language})
    if speakers:
        settings.diarization.max_speakers = max(speakers, settings.diarization.min_speakers)
    phrases = tuple(
        line.strip() for line in vocabulary.read_text(encoding="utf-8").splitlines() if line.strip()
    ) if vocabulary else ()
    destination = output or Path("artifacts") / audio.stem
    destination.mkdir(parents=True, exist_ok=True)

    with console.status(f"Loading {audio.name}"):
        clip = load_clip(audio, settings.audio.sample_rate)
    console.print(f"[bold]{audio.name}[/bold]  {clip.duration / 60:.1f} min  {clip.sample_rate} Hz")

    pipeline = Composition(settings).pipeline()
    request = MeetingRequest(
        audio_path=audio,
        title=title,
        language=language,
        vocabulary=phrases,
        expected_participants=(),
    )
    with console.status("Transcribing"):
        outcome = pipeline.run(clip, request)
    transcript = outcome.transcript
    if phrases:
        transcript, report = VocabularyBiaser().apply(transcript, phrases, language or "en")
        if report.count:
            console.print(f"vocabulary corrections applied: {report.count}")

    context = RenderContext(
        title=title,
        duration_seconds=clip.duration,
        language=language or transcript.language or "en",
    )
    written: list[Path] = []
    for name in (item.strip() for item in formats.split(",") if item.strip()):
        renderer = renderer_for(name)
        payload = renderer.render_transcript(transcript, context)
        path = destination / f"transcript{renderer.file_extension}"
        path.write_bytes(payload if isinstance(payload, bytes) else payload.encode("utf-8"))
        written.append(path)

    metrics = {
        "audio_seconds": round(clip.duration, 1),
        "real_time_factor": round(outcome.real_time_factor, 4),
        "speedup": round(1 / outcome.real_time_factor, 1) if outcome.real_time_factor else None,
        "speakers": outcome.diarization.speaker_count,
        "words": transcript.word_count,
        "stages": outcome.stage_seconds,
    }
    (destination / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    table = Table(show_header=False)
    table.add_row("duration", f"{clip.duration / 60:.1f} min")
    table.add_row("speakers detected", str(outcome.diarization.speaker_count))
    table.add_row("words", str(transcript.word_count))
    table.add_row("real-time factor", f"{outcome.real_time_factor:.3f}")
    console.print(table)
    for path in written:
        console.print(f"  wrote {path}")


def main() -> None:
    application()


if __name__ == "__main__":
    main()
