from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
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
from hansard.observability.logging import configure_logging
from hansard.rendering.ports import ModelProvenance, RenderContext

application = typer.Typer(
    name="hansard",
    help="Sovereign, self-hosted meeting transcription and minutes. Nothing leaves your machine.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _serve_metrics(port: int) -> None:
    try:
        from prometheus_client import start_http_server
    except ImportError:
        console.print("[yellow]prometheus-client is not installed; metrics disabled[/yellow]")
        return
    start_http_server(port)
    console.print(f"metrics on http://0.0.0.0:{port}/metrics")


def _provenance(settings: Settings) -> tuple[ModelProvenance, ...]:

    entries = [
        ModelProvenance("recognition", settings.asr.engine, settings.asr.model_id),
        ModelProvenance("diarization", settings.diarization.engine, settings.diarization.embedding_model),
        ModelProvenance("voice activity", settings.vad.engine, ""),
    ]
    if settings.minutes.enabled:
        entries.append(ModelProvenance("minutes", "local", settings.minutes.model_id))
    return tuple(entries)


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
            extra = "asr-onnx" if probe == "onnxruntime" else "diarization"
            table.add_row(label, "missing", f"pip install hansard[{extra}]")
    table.add_row("telemetry", "disabled", "Hansard never sends data anywhere")
    console.print(table)


@application.command()
def transcribe(
    audio: Annotated[Path, typer.Argument(help="Audio or video file to transcribe")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Directory for artefacts")] = None,
    language: Annotated[
        str | None, typer.Option("--language", "-l", help="fr, en, or omit to autodetect")
    ] = None,
    formats: Annotated[
        str, typer.Option("--format", "-f", help="Comma-separated output formats")
    ] = "markdown,json,vtt",
    vocabulary: Annotated[
        Path | None, typer.Option("--vocabulary", help="File with one boost phrase per line")
    ] = None,
    speakers: Annotated[int | None, typer.Option("--speakers", help="Known number of participants")] = None,
    title: Annotated[str, typer.Option("--title", help="Meeting title")] = "Meeting",
) -> None:
    from hansard.rendering.registry import transcript_renderer_for

    settings = _settings({"asr.language": language})
    phrases = (
        tuple(line.strip() for line in vocabulary.read_text(encoding="utf-8").splitlines() if line.strip())
        if vocabulary
        else ()
    )
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
        speaker_count=speakers,
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
        started_at=datetime.now(UTC),
        duration_seconds=clip.duration,
        language=language or transcript.language or "en",
        provenance=_provenance(settings),
    )
    written: list[Path] = []
    for name in (item.strip() for item in formats.split(",") if item.strip()):
        renderer = transcript_renderer_for(name)
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


@application.command()
def worker(
    inbox: Annotated[
        Path | None, typer.Option("--inbox", help="Directory watched for recordings to process")
    ] = None,
    outbox: Annotated[
        Path | None, typer.Option("--outbox", help="Directory artefacts are written to")
    ] = None,
    poll_seconds: Annotated[float, typer.Option("--poll", help="Seconds between scans")] = 5.0,
    once: Annotated[bool, typer.Option("--once", help="Process what is present, then exit")] = False,
    heartbeat: Annotated[
        Path, typer.Option("--heartbeat", help="File touched on every scan, for liveness probes")
    ] = Path("/tmp/hansard-worker.alive"),
    metrics_port: Annotated[
        int, typer.Option("--metrics-port", help="Serve Prometheus metrics on this port, 0 to disable")
    ] = 0,
) -> None:
    import asyncio

    from hansard.application.watcher import InboxWatcher

    settings = load_settings()
    watched = inbox or settings.runtime.workspace / "inbox"
    produced = outbox or settings.runtime.workspace / "outbox"
    if metrics_port:
        _serve_metrics(metrics_port)
    watcher = InboxWatcher(
        settings=settings,
        inbox=watched,
        outbox=produced,
        poll_seconds=poll_seconds,
        heartbeat_path=None if once else heartbeat,
        on_event=lambda message: console.print(message),
    )
    console.print(f"watching [bold]{watched}[/bold], writing to [bold]{produced}[/bold]")
    console.print("drop an audio file in the inbox; a sidecar .json may carry title, language, vocabulary")
    asyncio.run(watcher.run_once() if once else watcher.run_forever())


@application.command()
def serve(
    host: Annotated[str | None, typer.Option("--host", help="Bind address")] = None,
    port: Annotated[int | None, typer.Option("--port", help="Bind port")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Reload on source change")] = False,
) -> None:
    import uvicorn

    settings = load_settings()
    console.print(
        f"Hansard API on http://{host or settings.api.host}:{port or settings.api.port} "
        f"(telemetry disabled, no outbound calls)"
    )
    uvicorn.run(
        "hansard.interfaces.api.app:create_app",
        factory=True,
        host=host or settings.api.host,
        port=port or settings.api.port,
        reload=reload,
    )


@application.command()
def join(
    meeting_url: Annotated[str, typer.Argument(help="Teams meeting join URL")],
    title: Annotated[str, typer.Option("--title", help="Meeting title")] = "Meeting",
    language: Annotated[str | None, typer.Option("--language", "-l")] = None,
    deliver: Annotated[list[str] | None, typer.Option("--deliver", help="channel:address")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    vocabulary: Annotated[Path | None, typer.Option("--vocabulary")] = None,
) -> None:
    import asyncio

    from hansard.adapters.capture.registry import build_capture
    from hansard.adapters.summarization.registry import build_minutes_writer
    from hansard.application.jobs import InMemoryJobStore
    from hansard.application.meeting_service import MeetingService
    from hansard.domain.meeting import DeliveryChannel, DeliveryTarget

    settings = _settings({"asr.language": language})
    if output is not None:
        settings.runtime.workspace = output
    targets = tuple(
        DeliveryTarget(channel=DeliveryChannel(channel.replace("-", "_")), address=address)
        for channel, _, address in (item.partition(":") for item in (deliver or []))
        if address
    )
    phrases = (
        tuple(line.strip() for line in vocabulary.read_text(encoding="utf-8").splitlines() if line.strip())
        if vocabulary
        else ()
    )
    request = MeetingRequest(
        join_url=meeting_url,
        title=title,
        language=language,
        vocabulary=phrases,
        delivery=targets,
    )
    minutes_writer = None
    if settings.minutes.enabled:
        try:
            minutes_writer = build_minutes_writer(settings.minutes)
        except Exception as error:
            console.print(f"[yellow]minutes generator unavailable: {error}[/yellow]")
    composition = Composition(settings)
    service = MeetingService(
        settings=settings,
        pipeline=composition.pipeline(),
        capture=build_capture(settings.capture, settings.audio.sample_rate),
        minutes_writer=minutes_writer,
        biaser=VocabularyBiaser(),
        artifact_store=composition.artifact_store(),
    )

    async def run() -> None:
        store = InMemoryJobStore()
        record = await store.create(request)
        console.print(f"joining meeting as [bold]{settings.capture.display_name}[/bold]")
        completed = await service.execute(record)
        console.print(f"state: {completed.state}")
        for artifact in completed.artifacts:
            console.print(f"  wrote {artifact}")

    asyncio.run(run())


def main() -> None:
    configure_logging(load_settings().runtime)
    application()


if __name__ == "__main__":
    main()
