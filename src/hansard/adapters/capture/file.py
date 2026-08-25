from __future__ import annotations

import shutil
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hansard.domain.errors import CaptureError
from hansard.domain.meeting import Capture, MeetingRequest
from hansard.domain.speakers import Participant, Roster


@dataclass(frozen=True, slots=True)
class AudioProbe:
    sample_rate: int
    duration_seconds: float


def probe_audio(path: Path) -> AudioProbe:
    if not path.exists():
        raise CaptureError(f"audio file not found: {path}")
    try:
        import soundfile
    except ImportError:
        return _probe_wave(path)
    try:
        info = soundfile.info(str(path))
    except Exception:
        return _probe_wave(path)
    return AudioProbe(sample_rate=int(info.samplerate), duration_seconds=float(info.duration))


def _probe_wave(path: Path) -> AudioProbe:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
    except (OSError, wave.Error) as error:
        raise CaptureError(f"could not read {path}; convert it to WAV or FLAC first ({error})") from error
    return AudioProbe(sample_rate=rate, duration_seconds=frames / rate if rate else 0.0)


def roster_from_expected(names: tuple[str, ...]) -> Roster:
    return Roster(
        participants=tuple(
            Participant(identifier=f"expected-{index}", display_name=name)
            for index, name in enumerate(names)
            if name.strip()
        )
    )


@dataclass(slots=True)
class FileCapture:
    copy_into_workspace: bool = True
    probe: Callable[[Path], AudioProbe] = probe_audio
    copy: Callable[[Path, Path], object] = shutil.copy2
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    @property
    def name(self) -> str:
        return "file"

    async def capture(self, request: MeetingRequest, workspace: Path) -> Capture:
        source = request.audio_path
        if source is None:
            raise CaptureError("FileCapture requires MeetingRequest.audio_path")
        probe = self.probe(source)
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / f"{request.identifier}{source.suffix or '.wav'}"
        if not self.copy_into_workspace or source.resolve() == target.resolve():
            target = source
        else:
            self.copy(source, target)
        ended_at = self.now()
        started_at = ended_at - timedelta(seconds=probe.duration_seconds)
        return Capture(
            audio_path=target,
            roster=roster_from_expected(request.expected_participants),
            started_at=started_at,
            ended_at=ended_at,
            sample_rate=probe.sample_rate,
        )


@dataclass(slots=True)
class NullCapture:
    sample_rate: int = 16_000
    silence_seconds: float = 1.0
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    written: list[Path] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "null"

    async def capture(self, request: MeetingRequest, workspace: Path) -> Capture:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / f"{request.identifier}.wav"
        frames = int(self.sample_rate * self.silence_seconds)
        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.sample_rate)
            handle.writeframes(b"\x00\x00" * frames)
        self.written.append(target)
        started_at = self.now()
        return Capture(
            audio_path=target,
            roster=roster_from_expected(request.expected_participants),
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=self.silence_seconds),
            sample_rate=self.sample_rate,
        )
