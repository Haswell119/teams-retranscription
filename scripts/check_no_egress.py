from __future__ import annotations

import socket
import sys
import tempfile
from pathlib import Path

FIXTURE = Path("tests/fixtures/speech_en_8s.wav")


class EgressAttemptedError(RuntimeError):
    pass


def _seal_network() -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise EgressAttemptedError(
            "the inference path opened a network connection; this build is not sovereign"
        )

    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse  # type: ignore[assignment]


def _run(models_dir: Path) -> int:
    from hansard.adapters.audio import load_clip
    from hansard.config import Settings
    from hansard.domain.errors import ConfigurationError, DiarizationError, RecognitionError
    from hansard.domain.meeting import MeetingRequest
    from hansard.factory import Composition

    settings = Settings()
    settings.runtime.models_dir = models_dir
    settings.runtime.allow_model_downloads = False
    settings.minutes.enabled = False
    settings.vad.model_subdirectory = "."

    clip = load_clip(FIXTURE, settings.audio.sample_rate)
    pipeline = Composition(settings).pipeline()
    request = MeetingRequest(audio_path=FIXTURE, title="egress probe", language="en")

    staged = (models_dir / "sherpa-onnx-pyannote-segmentation-3-0").is_dir()
    try:
        outcome = pipeline.run(clip, request)
    except EgressAttemptedError as error:
        print(f"FAIL: {error}")
        return 1
    except (ConfigurationError, DiarizationError, RecognitionError) as error:
        if staged:
            print(f"FAIL: models are staged but the pipeline failed: {error}")
            return 1
        print("PASS: no models staged, and the pipeline refused to reach the network for them")
        print(f"       it reported: {error}")
        return 0
    print(
        "PASS: full transcription completed with every socket sealed "
        f"({outcome.transcript.word_count} words, "
        f"{outcome.diarization.speaker_count} speakers)"
    )
    return 0


def main() -> int:
    if not FIXTURE.exists():
        print(f"FAIL: missing fixture {FIXTURE}")
        return 1
    import hansard.factory  # noqa: F401

    _seal_network()
    configured = Path(__import__("os").environ.get("HANSARD_RUNTIME__MODELS_DIR", ""))
    with tempfile.TemporaryDirectory() as scratch:
        models_dir = configured if configured.is_dir() else Path(scratch)
        return _run(models_dir)


if __name__ == "__main__":
    sys.exit(main())
