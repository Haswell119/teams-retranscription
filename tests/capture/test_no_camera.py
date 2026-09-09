from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from hansard.adapters.capture.browser.session import NO_CAMERA_PATH, load_camera_guard

HARNESS = """
const results = { calls: [], rejected: null, devices: null, legacy: null };

const navigator = {
  mediaDevices: {
    getUserMedia(constraints) {
      results.calls.push(constraints);
      return Promise.resolve({ track: 'stream' });
    },
    enumerateDevices() {
      return Promise.resolve([
        { kind: 'audioinput', label: 'mic' },
        { kind: 'videoinput', label: 'camera' },
        { kind: 'audiooutput', label: 'speaker' },
      ]);
    },
  },
  getUserMedia(constraints, onSuccess) {
    results.legacy = constraints;
    onSuccess({ track: 'legacy' });
  },
};

class DOMException extends Error {
  constructor(message, name) {
    super(message);
    this.name = name;
  }
}

GUARD

async function main() {
  await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
  await navigator.mediaDevices.getUserMedia({ audio: true });
  try {
    await navigator.mediaDevices.getUserMedia({ video: true });
  } catch (error) {
    results.rejected = error.name;
  }
  results.devices = (await navigator.mediaDevices.enumerateDevices()).map((d) => d.kind);
  navigator.getUserMedia({ audio: true, video: true }, () => {});
  console.log(JSON.stringify(results));
}

main();
"""


def run_guard(tmp_path):
    script = tmp_path / "harness.mjs"
    script.write_text(HARNESS.replace("GUARD", load_camera_guard()), encoding="utf-8")
    finished = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(finished.stdout.strip().splitlines()[-1])


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@needs_node
def test_a_request_for_audio_and_video_reaches_the_browser_without_video(tmp_path):
    results = run_guard(tmp_path)
    assert results["calls"][0] == {"audio": True}


@needs_node
def test_an_audio_only_request_is_left_alone(tmp_path):
    results = run_guard(tmp_path)
    assert results["calls"][1] == {"audio": True}


@needs_node
def test_no_call_ever_carries_video(tmp_path):
    results = run_guard(tmp_path)
    assert all("video" not in call for call in results["calls"])


@needs_node
def test_a_video_only_request_is_refused_rather_than_silently_downgraded(tmp_path):
    results = run_guard(tmp_path)
    assert results["rejected"] == "NotFoundError"
    assert len(results["calls"]) == 2


@needs_node
def test_the_page_is_told_there_is_no_camera_to_offer(tmp_path):
    results = run_guard(tmp_path)
    assert "videoinput" not in results["devices"]
    assert results["devices"] == ["audioinput", "audiooutput"]


@needs_node
def test_the_legacy_entry_point_is_covered_too(tmp_path):
    results = run_guard(tmp_path)
    assert results["legacy"] == {"audio": True}


def test_the_guard_ships_beside_the_module_that_loads_it():
    assert NO_CAMERA_PATH.is_file()
    assert load_camera_guard().strip()
