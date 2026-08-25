from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hansard.adapters.asr.biasing import VocabularyBiaser
from hansard.adapters.capture.registry import build_capture
from hansard.adapters.summarization.registry import build_minutes_writer
from hansard.application.jobs import InMemoryJobStore
from hansard.application.meeting_service import MeetingService
from hansard.config import Settings
from hansard.domain.errors import ConfigurationError, HansardError
from hansard.domain.meeting import MeetingRequest
from hansard.factory import Composition


def _ignore(_message: str) -> None:
    return None


def _speaker_count(value: object) -> int | None:
    return int(value) if isinstance(value, int | str) and str(value).isdigit() else None


AUDIO_SUFFIXES = frozenset(
    {".wav", ".flac", ".ogg", ".opus", ".mp3", ".m4a", ".mp4", ".mkv", ".webm", ".aac", ".wma"}
)
SIDECAR_SUFFIX = ".json"
PROCESSING_DIRECTORY = ".processing"
FAILED_DIRECTORY = ".failed"


@dataclass(slots=True)
class InboxWatcher:
    settings: Settings
    inbox: Path
    outbox: Path
    poll_seconds: float = 5.0
    on_event: Callable[[str], None] = _ignore
    _service: MeetingService | None = field(default=None, init=False, repr=False)

    def _build_service(self) -> MeetingService:
        if self._service is None:
            writer = None
            if self.settings.minutes.enabled:
                try:
                    writer = build_minutes_writer(self.settings.minutes)
                except (ConfigurationError, ImportError) as error:
                    self.on_event(f"minutes disabled: {error}")
            self._service = MeetingService(
                settings=self.settings,
                pipeline=Composition(self.settings).pipeline(),
                capture=build_capture(self.settings.capture, self.settings.audio.sample_rate),
                minutes_writer=writer,
                biaser=VocabularyBiaser(),
            )
        return self._service

    def pending(self) -> tuple[Path, ...]:
        if not self.inbox.is_dir():
            return ()
        return tuple(
            sorted(
                path
                for path in self.inbox.iterdir()
                if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
            )
        )

    def _sidecar(self, audio: Path) -> dict[str, object]:
        sidecar = audio.with_suffix(SIDECAR_SUFFIX)
        if not sidecar.exists():
            return {}
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            self.on_event(f"ignoring malformed sidecar {sidecar.name}: {error}")
            return {}
        return payload if isinstance(payload, dict) else {}

    def _request(self, audio: Path) -> MeetingRequest:
        options = self._sidecar(audio)
        vocabulary = options.get("vocabulary")
        return MeetingRequest(
            audio_path=audio,
            title=str(options.get("title") or audio.stem),
            language=str(options["language"]) if options.get("language") else None,
            vocabulary=tuple(str(item) for item in vocabulary) if isinstance(vocabulary, list) else (),
            speaker_count=_speaker_count(options.get("speakers")),
        )

    async def process(self, audio: Path) -> Path | None:
        staging = self.inbox / PROCESSING_DIRECTORY
        staging.mkdir(parents=True, exist_ok=True)
        claimed = staging / audio.name
        try:
            audio.rename(claimed)
        except OSError:
            return None
        request = self._request(claimed)
        self.on_event(f"processing {audio.name}")
        store = InMemoryJobStore()
        record = await store.create(request)
        try:
            completed = await self._build_service().execute(record)
        except HansardError as error:
            failed = self.inbox / FAILED_DIRECTORY
            failed.mkdir(parents=True, exist_ok=True)
            claimed.rename(failed / audio.name)
            (failed / f"{audio.stem}.error.txt").write_text(str(error), encoding="utf-8")
            self.on_event(f"failed {audio.name}: {error}")
            return None
        destination = self.outbox / request.identifier
        destination.mkdir(parents=True, exist_ok=True)
        for artifact in completed.artifacts:
            shutil.copy2(artifact, destination / artifact.name)
        (destination / "source.txt").write_text(audio.name, encoding="utf-8")
        claimed.unlink(missing_ok=True)
        audio.with_suffix(SIDECAR_SUFFIX).unlink(missing_ok=True)
        self.on_event(f"completed {audio.name} -> {destination}")
        return destination

    async def run_once(self) -> int:
        processed = 0
        for audio in self.pending():
            if await self.process(audio) is not None:
                processed += 1
        return processed

    async def run_forever(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
        while True:
            await self.run_once()
            await asyncio.sleep(self.poll_seconds)
