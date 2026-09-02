from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hansard.application.jobs import JobQueue, JobRecord, now
from hansard.application.persistence import (
    ABANDONED_REASON,
    JOBS_DIRECTORY,
    FilesystemJobStore,
    recover_jobs,
    resumable,
)
from hansard.config import Settings
from hansard.domain.errors import ArtifactNotFound
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget, JobState, MeetingRequest
from hansard.interfaces.api.app import create_app

JOIN_URL = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0"


@pytest.fixture
def store(tmp_path) -> FilesystemJobStore:
    return FilesystemJobStore(root=tmp_path / "jobs")


def a_record(state: JobState = JobState.PENDING, **overrides) -> JobRecord:
    request = MeetingRequest(join_url=JOIN_URL, title="Comité", **overrides)
    moment = now()
    return JobRecord(
        identifier=request.identifier,
        request=request,
        state=state,
        created_at=moment,
        updated_at=moment,
    )


def a_recording(workspace: Path, identifier: str, size: int = 200_000) -> Path:
    directory = workspace / identifier
    directory.mkdir(parents=True, exist_ok=True)
    audio = directory / f"{identifier}.wav"
    audio.write_bytes(b"\0" * size)
    return audio


async def test_a_record_survives_the_process_that_wrote_it(store, tmp_path):
    record = a_record(
        JobState.CAPTURING,
        language="fr",
        vocabulary=("Hansard",),
        delivery=(DeliveryTarget(channel=DeliveryChannel.EMAIL, address="a@b.c"),),
    )
    await store.save(record)

    restarted = FilesystemJobStore(root=tmp_path / "jobs")
    reloaded = await restarted.get(record.identifier)
    assert reloaded.state is JobState.CAPTURING
    assert reloaded.request.join_url == JOIN_URL
    assert reloaded.request.language == "fr"
    assert reloaded.request.vocabulary == ("Hansard",)
    assert reloaded.request.delivery[0].address == "a@b.c"
    assert reloaded.created_at == record.created_at


async def test_an_unknown_job_is_reported_as_missing(store):
    with pytest.raises(ArtifactNotFound):
        await store.get("nothing-here")


async def test_a_meeting_interrupted_after_recording_resumes_from_its_audio(store, tmp_path):
    workspace = tmp_path / "workspace"
    record = await store.save(a_record(JobState.CAPTURING))
    audio = a_recording(workspace, record.identifier)

    recovery = await recover_jobs(store, workspace)
    assert len(recovery.resumed) == 1
    assert not recovery.abandoned
    resumed = recovery.resumed[0]
    assert resumed.state is JobState.PENDING
    assert resumed.request.audio_path == audio
    assert resumed.request.join_url is None
    assert resumed.identifier == record.identifier


async def test_a_meeting_interrupted_while_transcribing_resumes_too(store, tmp_path):
    workspace = tmp_path / "workspace"
    record = await store.save(a_record(JobState.TRANSCRIBING))
    a_recording(workspace, record.identifier)
    recovery = await recover_jobs(store, workspace)
    assert [item.identifier for item in recovery.resumed] == [record.identifier]


async def test_a_meeting_interrupted_with_nothing_recorded_is_not_pretended_to_be_recoverable(
    store, tmp_path
):
    workspace = tmp_path / "workspace"
    record = await store.save(a_record(JobState.CAPTURING))

    recovery = await recover_jobs(store, workspace)
    assert not recovery.resumed
    assert [item.identifier for item in recovery.abandoned] == [record.identifier]
    assert (await store.get(record.identifier)).state is JobState.FAILED
    assert ABANDONED_REASON in (await store.get(record.identifier)).error


async def test_an_empty_recording_does_not_count_as_something_to_resume(store, tmp_path):
    workspace = tmp_path / "workspace"
    record = await store.save(a_record(JobState.CAPTURING))
    a_recording(workspace, record.identifier, size=10)
    recovery = await recover_jobs(store, workspace)
    assert not recovery.resumed
    assert len(recovery.abandoned) == 1


async def test_a_job_that_never_started_is_simply_queued_again(store, tmp_path):
    record = await store.save(a_record(JobState.PENDING))
    recovery = await recover_jobs(store, tmp_path / "workspace")
    assert [item.identifier for item in recovery.resumed] == [record.identifier]
    assert recovery.resumed[0].request.join_url == JOIN_URL


async def test_finished_jobs_are_left_alone(store, tmp_path):
    completed = await store.save(a_record(JobState.COMPLETED))
    failed = await store.save(a_record(JobState.FAILED))
    recovery = await recover_jobs(store, tmp_path / "workspace")
    assert recovery.considered == 0
    assert (await store.get(completed.identifier)).state is JobState.COMPLETED
    assert (await store.get(failed.identifier)).state is JobState.FAILED


def test_a_file_transcription_needs_no_recording_on_disk(tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"\0" * 100)
    request = MeetingRequest(audio_path=audio)
    moment = now()
    record = JobRecord(
        identifier=request.identifier,
        request=request,
        state=JobState.TRANSCRIBING,
        created_at=moment,
        updated_at=moment,
    )
    resumed = resumable(record, tmp_path / "workspace")
    assert resumed is not None
    assert resumed.request.audio_path == audio


async def test_a_corrupt_record_is_skipped_rather_than_bringing_the_listing_down(store):
    good = await store.save(a_record(JobState.COMPLETED))
    (store.root / "broken.json").write_text("{not json", encoding="utf-8")
    listed = await store.list(10)
    assert [item.identifier for item in listed] == [good.identifier]


async def test_a_resubmitted_record_runs_again(store):
    seen: list[str] = []

    async def handler(record: JobRecord) -> JobRecord:
        seen.append(record.identifier)
        return record.advanced(JobState.COMPLETED)

    queue = JobQueue(store=store, handler=handler, concurrency=1)
    record = await store.save(a_record(JobState.PENDING))
    await queue.start()
    await queue.resubmit(record)
    await queue._queue.join()
    await queue.stop()
    assert seen == [record.identifier]
    assert (await store.get(record.identifier)).state is JobState.COMPLETED


def test_the_api_keeps_its_jobs_across_a_restart(tmp_path):
    configured = Settings()
    configured.minutes.enabled = False
    configured.capture.engine = "file"
    configured.asr.engine = "null"
    configured.diarization.engine = "null"
    configured.vad.engine = "energy"
    configured.runtime.workspace = tmp_path / "workspace"
    configured.runtime.models_dir = tmp_path / "models"
    configured.runtime.models_dir.mkdir(parents=True)

    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"")
    with TestClient(create_app(configured)) as first:
        identifier = first.post("/v1/meetings", json={"audio_path": str(audio)}).json()["identifier"]

    stored = configured.runtime.workspace / JOBS_DIRECTORY / f"{identifier}.json"
    assert stored.is_file()
    assert json.loads(stored.read_text(encoding="utf-8"))["request"]["identifier"] == identifier

    with TestClient(create_app(configured)) as second:
        assert second.get(f"/v1/meetings/{identifier}").status_code == 200
