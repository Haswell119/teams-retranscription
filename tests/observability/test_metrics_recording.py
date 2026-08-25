from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from hansard.adapters.asr.null_engine import NullRecognizer
from hansard.adapters.attribution.fusion import WordLevelAttributor
from hansard.adapters.delivery.dispatcher import DeliveryDispatcher
from hansard.adapters.diarization.null_diarizer import NullDiarizer
from hansard.application.pipeline import TranscriptionPipeline
from hansard.config import Settings
from hansard.domain.audio import AudioClip
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget, MeetingRequest
from hansard.interfaces.api.app import create_app
from hansard.observability import metrics
from hansard.ports.delivery import Payload

pytestmark = pytest.mark.skipif(not metrics.backend_available(), reason="prometheus_client is not installed")

SAMPLE_RATE = 16_000


def value(name: str, **labels: str) -> float:
    return metrics.REGISTRY.get_sample_value(name, labels) or 0.0


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


def clip(seconds: float = 2.0) -> AudioClip:
    samples = np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
    return AudioClip(samples=samples, sample_rate=SAMPLE_RATE)


def pipeline() -> TranscriptionPipeline:
    return TranscriptionPipeline(
        recognizer=NullRecognizer(placeholder="bonjour"),
        attributor=WordLevelAttributor(),
        diarizer=NullDiarizer(),
    )


def test_the_metrics_endpoint_is_served_when_enabled(settings):
    settings.api.metrics_enabled = True
    with TestClient(create_app(settings)) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "hansard_build_info" in response.text


def test_the_metrics_endpoint_is_absent_when_disabled(settings):
    settings.api.metrics_enabled = False
    with TestClient(create_app(settings)) as client:
        assert client.get("/metrics").status_code == 404


def test_build_information_names_the_recognition_engine(settings):
    settings.asr.engine = "whisper"
    settings.asr.model_id = "large-v3-turbo"
    with TestClient(create_app(settings)) as client:
        body = client.get("/metrics").text
    assert 'asr_engine="whisper"' in body
    assert 'asr_model="large-v3-turbo"' in body


def test_submitting_a_meeting_counts_it_once(settings, tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"")
    before = value("hansard_meetings_scheduled_total")
    pending_before = value("hansard_job_state_transitions_total", state="pending")
    with TestClient(create_app(settings)) as client:
        client.post("/v1/meetings", json={"audio_path": str(audio), "title": "Comité"})
    assert value("hansard_meetings_scheduled_total") == before + 1
    assert value("hansard_job_state_transitions_total", state="pending") == pending_before + 1


def test_recognition_duration_and_realtime_factor_are_recorded():
    labels = {"model": "null", "compute": "unknown", "language": "fr"}
    before = value("hansard_asr_transcribe_duration_seconds_count", **labels)
    rtf_before = value("hansard_asr_realtime_factor_count", **labels)
    pipeline().run(clip(), MeetingRequest(audio_path=None, join_url="https://teams", language="fr"))
    assert value("hansard_asr_transcribe_duration_seconds_count", **labels) == before + 1
    assert value("hansard_asr_realtime_factor_count", **labels) == rtf_before + 1


def test_an_unknown_language_never_becomes_a_metric_label():
    labels = {"model": "null", "compute": "unknown", "language": "unknown"}
    before = value("hansard_asr_transcribe_duration_seconds_count", **labels)
    pipeline().run(clip(), MeetingRequest(join_url="https://teams", language="klingon"))
    assert value("hansard_asr_transcribe_duration_seconds_count", **labels) == before + 1


def test_the_speaker_count_is_recorded_once_per_diarized_meeting():
    before = value("hansard_diarization_speakers_count")
    pipeline().run(clip(), MeetingRequest(join_url="https://teams", language="en"))
    assert value("hansard_diarization_speakers_count") == before + 1


def test_recognition_failures_are_counted_by_reason():
    class BrokenRecognizer(NullRecognizer):
        def transcribe(self, clip, hints):
            raise RuntimeError("no model")

    broken = TranscriptionPipeline(recognizer=BrokenRecognizer(), attributor=WordLevelAttributor())
    before = value("hansard_asr_failures_total", reason="RuntimeError")
    with pytest.raises(RuntimeError):
        broken.run(clip(), MeetingRequest(join_url="https://teams"))
    assert value("hansard_asr_failures_total", reason="RuntimeError") == before + 1


async def test_delivery_attempts_are_counted_by_channel_and_result():
    class Publisher:
        channel = DeliveryChannel.WEBHOOK

        def __init__(self, fails: bool) -> None:
            self.fails = fails

        async def publish(self, target, payload):
            if self.fails:
                raise RuntimeError("unreachable")

    target = DeliveryTarget(channel=DeliveryChannel.WEBHOOK, address="https://hooks.internal")
    payload = Payload(subject="Comité", body="body")
    delivered = value("hansard_delivery_attempts_total", channel="webhook", result="success")
    failed = value("hansard_delivery_attempts_total", channel="webhook", result="failure")

    await DeliveryDispatcher(resolve_publisher=lambda _c: Publisher(False)).deliver([target], payload)
    await DeliveryDispatcher(resolve_publisher=lambda _c: Publisher(True)).deliver([target], payload)

    assert value("hansard_delivery_attempts_total", channel="webhook", result="success") == delivered + 1
    assert value("hansard_delivery_attempts_total", channel="webhook", result="failure") == failed + 1


def test_identifying_labels_are_refused_by_construction():
    for forbidden in ("meeting_id", "user_id", "join_url"):
        assert forbidden in metrics.FORBIDDEN_LABEL_NAMES
