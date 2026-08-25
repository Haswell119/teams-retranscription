import asyncio
import json
from pathlib import Path

import pytest

from hansard.application.watcher import InboxWatcher
from hansard.config import Settings


@pytest.fixture
def settings(tmp_path):
    configured = Settings()
    configured.asr.engine = "null"
    configured.diarization.engine = "null"
    configured.vad.engine = "energy"
    configured.minutes.enabled = False
    configured.capture.engine = "file"
    configured.runtime.workspace = tmp_path / "workspace"
    configured.runtime.models_dir = tmp_path / "models"
    configured.runtime.models_dir.mkdir(parents=True)
    configured.delivery.formats = ("markdown",)
    return configured


def watcher_for(settings, tmp_path, **overrides):
    inbox = tmp_path / "inbox"
    outbox = tmp_path / "outbox"
    inbox.mkdir()
    outbox.mkdir()
    return InboxWatcher(settings=settings, inbox=inbox, outbox=outbox, **overrides)


def drop(inbox, name="meeting.wav", sidecar=None):
    audio = inbox / name
    audio.write_bytes(Path("tests/fixtures/speech_en_8s.wav").read_bytes())
    if sidecar is not None:
        audio.with_suffix(".json").write_text(json.dumps(sidecar), encoding="utf-8")
    return audio


def test_only_audio_files_are_picked_up(settings, tmp_path):
    watcher = watcher_for(settings, tmp_path)
    drop(watcher.inbox)
    (watcher.inbox / "notes.txt").write_text("ignore me", encoding="utf-8")
    assert [path.name for path in watcher.pending()] == ["meeting.wav"]


def test_a_recording_produces_artefacts(settings, tmp_path):
    watcher = watcher_for(settings, tmp_path)
    drop(watcher.inbox)
    processed = asyncio.run(watcher.run_once())
    assert processed == 1
    produced = list(watcher.outbox.rglob("transcript.md"))
    assert produced


def test_the_sidecar_supplies_the_title(settings, tmp_path):
    watcher = watcher_for(settings, tmp_path)
    drop(watcher.inbox, sidecar={"title": "Comité de lancement", "language": "fr"})
    asyncio.run(watcher.run_once())
    written = next(iter(watcher.outbox.rglob("transcript.md")))
    assert "Comité de lancement" in written.read_text(encoding="utf-8")


def test_a_processed_recording_leaves_the_inbox(settings, tmp_path):
    watcher = watcher_for(settings, tmp_path)
    drop(watcher.inbox, sidecar={"title": "One"})
    asyncio.run(watcher.run_once())
    assert watcher.pending() == ()
    assert not (watcher.inbox / "meeting.json").exists()


def test_a_malformed_sidecar_is_ignored_not_fatal(settings, tmp_path):
    watcher = watcher_for(settings, tmp_path)
    audio = drop(watcher.inbox)
    audio.with_suffix(".json").write_text("{not json", encoding="utf-8")
    assert asyncio.run(watcher.run_once()) == 1


def test_the_heartbeat_file_is_written(settings, tmp_path):
    beat = tmp_path / "beat" / "alive"
    watcher = watcher_for(settings, tmp_path, heartbeat_path=beat)
    watcher._beat()
    assert beat.exists()


def test_an_empty_inbox_processes_nothing(settings, tmp_path):
    watcher = watcher_for(settings, tmp_path)
    assert asyncio.run(watcher.run_once()) == 0
