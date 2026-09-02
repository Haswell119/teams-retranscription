from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hansard.adapters.asr.biasing import VocabularyBiaser
from hansard.application.jobs import JobRecord, now
from hansard.application.meeting_service import MeetingService
from hansard.config import Settings
from hansard.domain.errors import CaptureError
from hansard.domain.meeting import Capture, JobState, MeetingRequest
from hansard.domain.speakers import Roster
from hansard.factory import Composition

FIXTURE = Path("tests/fixtures/speech_en_8s.wav")


@pytest.fixture
def settings(tmp_path):
    configured = Settings()
    configured.asr.engine = "null"
    configured.diarization.engine = "null"
    configured.vad.engine = "energy"
    configured.minutes.enabled = False
    configured.capture.engine = "browser"
    configured.delivery.formats = ("markdown", "json")
    configured.runtime.workspace = tmp_path / "workspace"
    configured.runtime.models_dir = tmp_path / "models"
    configured.runtime.models_dir.mkdir(parents=True)
    return configured


class RecordingCapture:
    def __init__(self, audio: Path, error: Exception | None = None) -> None:
        self.audio = audio
        self.error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return "fake"

    async def capture(self, request: MeetingRequest, workspace: Path) -> Capture:
        self.calls += 1
        workspace.mkdir(parents=True, exist_ok=True)
        landed = workspace / f"{request.identifier}.wav"
        landed.write_bytes(self.audio.read_bytes())
        if self.error is not None:
            raise self.error
        finished = datetime.now(UTC)
        return Capture(
            audio_path=landed,
            roster=Roster(),
            started_at=finished - timedelta(seconds=8),
            ended_at=finished,
            sample_rate=16_000,
        )


def service_for(settings, capture) -> MeetingService:
    composition = Composition(settings)
    return MeetingService(
        settings=settings,
        pipeline=composition.pipeline(),
        capture=capture,
        minutes_writer=None,
        biaser=VocabularyBiaser(),
        artifact_store=None,
    )


def a_job(request: MeetingRequest) -> JobRecord:
    moment = now()
    return JobRecord(
        identifier=request.identifier,
        request=request,
        state=JobState.CAPTURING,
        created_at=moment,
        updated_at=moment,
    )


async def test_a_finished_meeting_flows_straight_into_a_rendered_transcript(settings):
    capture = RecordingCapture(FIXTURE)
    service = service_for(settings, capture)
    record = a_job(MeetingRequest(join_url="https://teams.microsoft.com/l/meetup-join/x/0"))

    completed = await service.execute(record)

    assert completed.state is JobState.COMPLETED
    assert {path.name for path in completed.artifacts} == {"transcript.md", "transcript.json"}
    assert all(path.is_file() for path in completed.artifacts)
    assert completed.metrics["audio_seconds"] > 0


async def test_the_states_between_capture_and_delivery_are_reported(settings):
    service = service_for(settings, RecordingCapture(FIXTURE))
    record = a_job(MeetingRequest(join_url="https://teams.microsoft.com/l/meetup-join/x/0"))
    seen: list[JobState] = []

    async def report(state: JobState) -> None:
        seen.append(state)

    await service.execute(record, on_state=report)
    assert seen == [JobState.TRANSCRIBING, JobState.SUMMARIZING, JobState.DELIVERING]


async def test_a_capture_that_raises_leaves_its_recording_where_recovery_will_find_it(settings):
    capture = RecordingCapture(FIXTURE, error=CaptureError("pulseaudio went away"))
    service = service_for(settings, capture)
    request = MeetingRequest(join_url="https://teams.microsoft.com/l/meetup-join/x/0")

    with pytest.raises(CaptureError):
        await service.execute(a_job(request))

    from hansard.application.persistence import captured_audio

    assert captured_audio(settings.runtime.workspace, request.identifier) is not None


def test_the_default_filesystem_target_lands_in_the_configured_directory(settings, tmp_path):
    from hansard.adapters.delivery.filesystem import FilesystemPublisher, resolve_output_directory

    settings.delivery.output_dir = tmp_path / "artifacts"
    service = service_for(settings, RecordingCapture(FIXTURE))
    target = service.delivery_targets(MeetingRequest(audio_path=FIXTURE))[0]
    publisher = FilesystemPublisher(root=settings.delivery.output_dir)
    resolved = resolve_output_directory(publisher.root, target.address, publisher.allow_absolute_paths)
    assert resolved == settings.delivery.output_dir.resolve()


async def test_minutes_reach_the_filesystem_channel_with_an_absolute_output_dir(settings, tmp_path):
    from hansard.adapters.delivery.dispatcher import dispatcher_from_settings
    from hansard.ports.delivery import Payload

    settings.delivery.output_dir = (tmp_path / "delivered").resolve()
    service = service_for(settings, RecordingCapture(FIXTURE))
    dispatcher = dispatcher_from_settings(settings.delivery)
    targets = service.delivery_targets(MeetingRequest(audio_path=FIXTURE))

    await dispatcher.deliver(targets, Payload(subject="Comité", body="# Minutes", body_format="markdown"))

    assert sorted(path.name for path in settings.delivery.output_dir.glob("*")) == ["Comité.md"]
