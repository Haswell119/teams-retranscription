import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hansard.config import Settings
from hansard.interfaces.api.app import create_app


@pytest.fixture
def settings(tmp_path):
    configured = Settings()
    configured.minutes.enabled = False
    configured.capture.engine = "file"
    configured.asr.engine = "null"
    configured.diarization.engine = "null"
    configured.vad.engine = "energy"
    configured.runtime.workspace = tmp_path / "workspace"
    configured.runtime.models_dir = tmp_path / "models"
    configured.runtime.models_dir.mkdir(parents=True)
    return configured


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as instance:
        yield instance


def test_health_reports_version_and_telemetry(client):
    payload = client.get("/healthz").json()
    assert payload["telemetry"] == "disabled"
    assert payload["version"]
    assert "models" in payload["checks"]


def test_readiness_probe_answers(client):
    assert client.get("/readyz").status_code in {200, 503}


def test_submission_requires_a_source(client):
    response = client.post("/v1/meetings", json={"title": "Empty"})
    assert response.status_code == 422


def test_submitted_meeting_is_listed(client, tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"")
    response = client.post(
        "/v1/meetings", json={"audio_path": str(audio), "title": "Comité", "language": "fr"}
    )
    assert response.status_code == 202
    identifier = response.json()["identifier"]
    assert response.json()["title"] == "Comité"
    listing = client.get("/v1/meetings").json()
    assert any(item["identifier"] == identifier for item in listing)


def test_unknown_meeting_returns_404(client):
    assert client.get("/v1/meetings/does-not-exist").status_code == 404


def test_unknown_artifact_returns_404(client, tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"")
    identifier = client.post("/v1/meetings", json={"audio_path": str(audio)}).json()["identifier"]
    assert client.get(f"/v1/meetings/{identifier}/artifacts/nope.md").status_code == 404


def test_api_key_is_enforced_when_configured(settings):
    settings.api.api_key = SecretStr("secret-value")
    with TestClient(create_app(settings)) as guarded:
        assert guarded.get("/v1/meetings").status_code == 401
        assert guarded.get("/v1/meetings", headers={"x-api-key": "secret-value"}).status_code == 200
        assert guarded.get("/healthz").status_code == 200


def test_delivery_targets_are_accepted(client, tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"")
    response = client.post(
        "/v1/meetings",
        json={
            "audio_path": str(audio),
            "delivery": [{"channel": "filesystem", "address": str(tmp_path / "out")}],
        },
    )
    assert response.status_code == 202
