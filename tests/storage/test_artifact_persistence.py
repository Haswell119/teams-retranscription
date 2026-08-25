from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from hansard.adapters.capture.registry import build_capture
from hansard.adapters.storage.filesystem import FilesystemArtifactStore
from hansard.application.jobs import InMemoryJobStore
from hansard.application.meeting_service import MeetingService, artifact_key
from hansard.config import Settings
from hansard.domain.meeting import JobState, MeetingRequest
from hansard.factory import Composition
from hansard.interfaces.api.app import create_app

SAMPLE_RATE = 16_000


@pytest.fixture
def settings(tmp_path):
    configured = Settings()
    configured.minutes.enabled = False
    configured.capture.engine = "file"
    configured.asr.engine = "null"
    configured.diarization.engine = "null"
    configured.vad.engine = "energy"
    configured.audio.loudness_normalisation = False
    configured.audio.denoise = False
    configured.audio.high_pass_hz = 0.0
    configured.delivery.formats = ("markdown",)
    configured.runtime.workspace = tmp_path / "workspace"
    configured.runtime.models_dir = tmp_path / "models"
    configured.runtime.models_dir.mkdir(parents=True)
    configured.storage.root = tmp_path / "store"
    return configured


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "meeting.wav"
    sf.write(str(path), np.zeros(SAMPLE_RATE * 2, dtype=np.float32), SAMPLE_RATE)
    return path


def service_for(settings, store=None) -> MeetingService:
    composition = Composition(settings)
    return MeetingService(
        settings=settings,
        pipeline=composition.pipeline(),
        capture=build_capture(settings.capture, settings.audio.sample_rate),
        artifact_store=store if store is not None else composition.artifact_store(),
    )


async def completed_record(service, audio):
    store = InMemoryJobStore()
    record = await store.create(MeetingRequest(audio_path=audio, title="Comité", language="fr"))
    return await service.execute(record)


async def test_rendered_artifacts_are_copied_into_the_store(settings, audio):
    store = Composition(settings).artifact_store()
    record = await completed_record(service_for(settings, store), audio)
    assert record.state is JobState.COMPLETED
    assert record.artifacts
    expected = tuple(artifact_key(record.identifier, path.name) for path in record.artifacts)
    assert await store.list_keys() == tuple(sorted(expected))
    assert record.metrics["stored_artifacts"] == float(len(expected))


async def test_stored_artifacts_match_the_rendered_bytes(settings, audio, tmp_path):
    store = Composition(settings).artifact_store()
    record = await completed_record(service_for(settings, store), audio)
    rendered = record.artifacts[0]
    restored = await store.get(artifact_key(record.identifier, rendered.name), tmp_path / "copy.md")
    assert restored.read_bytes() == rendered.read_bytes()


async def test_a_broken_store_never_loses_the_meeting(settings, audio):
    class BrokenStore(FilesystemArtifactStore):
        async def put(self, key: str, source: Path) -> str:
            raise OSError("object storage unreachable")

    record = await completed_record(service_for(settings, BrokenStore(root=settings.storage.root)), audio)
    assert record.state is JobState.COMPLETED
    assert record.metrics["stored_artifacts"] == 0.0
    assert all(path.is_file() for path in record.artifacts)


async def test_no_store_means_no_persistence_step(settings, audio):
    composition = Composition(settings)
    service = MeetingService(
        settings=settings,
        pipeline=composition.pipeline(),
        capture=build_capture(settings.capture, settings.audio.sample_rate),
    )
    record = await completed_record(service, audio)
    assert record.metrics["stored_artifacts"] == 0.0


def test_the_api_serves_an_artifact_restored_from_the_store(settings, audio):
    with TestClient(create_app(settings)) as client:
        identifier = client.post(
            "/v1/meetings", json={"audio_path": str(audio), "title": "Comité", "language": "fr"}
        ).json()["identifier"]
        detail = _awaited(client, identifier)
        assert detail["state"] == JobState.COMPLETED
        name = detail["artifacts"][0]
        served = client.get(f"/v1/meetings/{identifier}/artifacts/{name}").content

        (settings.runtime.workspace / identifier / name).unlink()
        restored = client.get(f"/v1/meetings/{identifier}/artifacts/{name}")

    assert restored.status_code == 200
    assert restored.content == served


def _awaited(client, identifier, attempts: int = 100):
    for _ in range(attempts):
        detail = client.get(f"/v1/meetings/{identifier}").json()
        if detail["state"] in {JobState.COMPLETED, JobState.FAILED}:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"job {identifier} never finished")
