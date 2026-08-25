from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from hansard.adapters.asr.registry import build_recognizer
from hansard.adapters.asr.whisper_engine import (
    WhisperModelRequest,
    WhisperRecognizer,
    load_faster_whisper_model,
    local_model_directory,
)
from hansard.config import AsrSettings
from hansard.domain.audio import AudioClip
from hansard.domain.errors import RecognitionError
from hansard.domain.timespan import TimeSpan
from hansard.ports.asr import RecognitionHints, SpeechRecognizer

SAMPLE_RATE = 16_000


@dataclass
class FakeWord:
    start: float
    end: float
    word: str
    probability: float = 0.9


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str
    avg_logprob: float = -0.2
    compression_ratio: float = 1.4
    no_speech_prob: float = 0.05
    words: list[FakeWord] = field(default_factory=list)


@dataclass
class FakeInfo:
    language: str = "fr"
    language_probability: float = 0.99


class FakeWhisperModel:
    def __init__(self, segments, info=None):
        self.segments = list(segments)
        self.info = info or FakeInfo()
        self.calls = []

    def transcribe(self, audio, **options):
        self.calls.append((audio, options))
        return iter(self.segments), self.info


def clip(seconds: float = 6.0) -> AudioClip:
    samples = np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
    return AudioClip(samples=samples, sample_rate=SAMPLE_RATE)


def recognizer_for(model, **overrides) -> WhisperRecognizer:
    options = {"model_id": "large-v3-turbo", "loader": lambda _request: model}
    options.update(overrides)
    return WhisperRecognizer(**options)


def test_it_satisfies_the_speech_recognizer_port():
    assert isinstance(recognizer_for(FakeWhisperModel([])), SpeechRecognizer)


def test_profile_reports_word_timestamps_punctuation_and_the_mit_licence():
    profile = recognizer_for(FakeWhisperModel([])).profile
    assert profile.emits_word_timestamps
    assert profile.emits_punctuation
    assert profile.license_identifier == "mit"
    assert profile.supports_vocabulary_biasing
    assert profile.metadata["word_timestamps"] == "approximate"
    assert {"fr", "en"} <= set(profile.languages)


def test_english_only_models_declare_english_and_memory_grows_without_int8():
    english = recognizer_for(FakeWhisperModel([]), model_id="small.en")
    assert english.profile.languages == ("en",)
    compact = recognizer_for(FakeWhisperModel([]), model_id="small").profile
    wide = recognizer_for(FakeWhisperModel([]), model_id="small", compute_type="float32").profile
    assert 0 < compact.resident_memory_mb < wide.resident_memory_mb


def test_hallucination_mitigations_are_applied_to_every_call():
    model = FakeWhisperModel([FakeSegment(0.0, 1.0, "bonjour")])
    recognizer_for(model, beam_size=5).transcribe(clip(2.0), RecognitionHints(language="fr"))
    _audio, options = model.calls[0]
    assert options["vad_filter"] is True
    assert options["condition_on_previous_text"] is False
    assert options["no_speech_threshold"] == pytest.approx(0.6)
    assert options["compression_ratio_threshold"] == pytest.approx(2.4)
    assert options["log_prob_threshold"] == pytest.approx(-1.0)
    assert options["beam_size"] == 5
    assert options["word_timestamps"] is True
    assert options["language"] == "fr"


def test_planned_segments_are_transcribed_and_timestamps_are_shifted():
    model = FakeWhisperModel(
        [FakeSegment(0.0, 1.5, " Bonjour à tous.", words=[FakeWord(0.0, 0.5, " Bonjour")])]
    )
    recognizer = recognizer_for(model)
    hints = RecognitionHints(language="fr", segments=(TimeSpan(2.0, 4.0), TimeSpan(4.0, 6.0)))
    transcript = recognizer.transcribe(clip(6.0), hints)
    assert len(model.calls) == 2
    assert [utterance.span.start for utterance in transcript.utterances] == [2.0, 4.0]
    assert transcript.utterances[0].text == "Bonjour à tous."
    assert transcript.utterances[0].words[0].span == TimeSpan(2.0, 2.5)
    assert transcript.utterances[1].words[0].span == TimeSpan(4.0, 4.5)


def test_timestamps_never_leave_the_planned_span():
    model = FakeWhisperModel([FakeSegment(0.0, 9.0, "overrun", words=[FakeWord(0.0, 9.0, "overrun")])])
    hints = RecognitionHints(segments=(TimeSpan(1.0, 2.0),))
    transcript = recognizer_for(model).transcribe(clip(6.0), hints)
    assert transcript.utterances[0].span == TimeSpan(1.0, 2.0)
    assert transcript.utterances[0].words[0].span.end <= 2.0


def test_average_log_probability_becomes_a_bounded_confidence():
    model = FakeWhisperModel([FakeSegment(0.0, 1.0, "hello", avg_logprob=-0.35)])
    transcript = recognizer_for(model).transcribe(clip(2.0), RecognitionHints(language="en"))
    assert transcript.utterances[0].confidence == pytest.approx(0.7046, abs=1e-3)

    confident = FakeWhisperModel([FakeSegment(0.0, 1.0, "hello", avg_logprob=0.5)])
    perfect = recognizer_for(confident).transcribe(clip(2.0), RecognitionHints(language="en"))
    assert perfect.utterances[0].confidence == 1.0


def test_silence_and_repetition_hallucinations_are_dropped():
    model = FakeWhisperModel(
        [
            FakeSegment(
                0.0, 1.0, "Sous-titres réalisés par la communauté", no_speech_prob=0.95, avg_logprob=-1.8
            ),
            FakeSegment(1.0, 2.0, "merci merci merci merci", compression_ratio=3.9),
            FakeSegment(2.0, 3.0, "   "),
            FakeSegment(3.0, 4.0, "Le comité approuve le budget."),
        ]
    )
    transcript = recognizer_for(model).transcribe(clip(6.0), RecognitionHints(language="fr"))
    assert [utterance.text for utterance in transcript.utterances] == ["Le comité approuve le budget."]


def test_english_and_french_both_reach_the_decoder():
    for language in ("fr", "en"):
        model = FakeWhisperModel([FakeSegment(0.0, 1.0, "text")], FakeInfo(language=language))
        transcript = recognizer_for(model).transcribe(clip(2.0), RecognitionHints(language=language))
        assert transcript.language == language
        assert transcript.utterances[0].language == language


def test_detected_language_is_used_when_none_was_requested():
    model = FakeWhisperModel([FakeSegment(0.0, 1.0, "bonjour")], FakeInfo(language="fr"))
    transcript = recognizer_for(model).transcribe(clip(2.0), RecognitionHints())
    assert transcript.language == "fr"
    assert "language" not in model.calls[0][1]


def test_vocabulary_and_prompt_become_hotwords_and_initial_prompt():
    model = FakeWhisperModel([FakeSegment(0.0, 1.0, "text")])
    hints = RecognitionHints(vocabulary=("Nutanix", "Hansard"), prompt="Conseil municipal")
    recognizer_for(model).transcribe(clip(2.0), hints)
    options = model.calls[0][1]
    assert options["hotwords"] == "Nutanix Hansard"
    assert options["initial_prompt"] == "Conseil municipal"


def test_decoding_failures_become_recognition_errors():
    class ExplodingModel:
        def transcribe(self, audio, **options):
            raise RuntimeError("ctranslate2 exploded")

    with pytest.raises(RecognitionError, match="Whisper decoding failed"):
        recognizer_for(ExplodingModel()).transcribe(clip(2.0), RecognitionHints())


def test_a_local_ctranslate2_directory_is_preferred_and_forbids_downloads(tmp_path):
    local = tmp_path / "Systran__faster-whisper-large-v3"
    local.mkdir()
    (local / "model.bin").write_bytes(b"weights")
    assert local_model_directory(tmp_path, "Systran/faster-whisper-large-v3") == local

    seen: list[WhisperModelRequest] = []
    recognizer = WhisperRecognizer(
        model_id="Systran/faster-whisper-large-v3",
        models_dir=tmp_path,
        loader=lambda request: seen.append(request) or FakeWhisperModel([]),
    )
    recognizer.transcribe(clip(1.0), RecognitionHints())
    assert seen[0].source == str(local)
    assert seen[0].local_files_only is True


def test_the_hub_name_is_only_used_when_downloads_are_allowed(tmp_path):
    seen: list[WhisperModelRequest] = []
    allowed = WhisperRecognizer(
        model_id="large-v3-turbo",
        models_dir=tmp_path,
        loader=lambda request: seen.append(request) or FakeWhisperModel([]),
    )
    allowed.transcribe(clip(1.0), RecognitionHints())
    assert seen[0].source == "large-v3-turbo"
    assert seen[0].local_files_only is False
    assert seen[0].download_root == str(tmp_path)

    airgapped = WhisperRecognizer(
        model_id="large-v3-turbo",
        models_dir=tmp_path,
        allow_downloads=False,
        loader=lambda _request: FakeWhisperModel([]),
    )
    with pytest.raises(RecognitionError, match="downloads are disabled"):
        airgapped.transcribe(clip(1.0), RecognitionHints())


def test_the_model_is_loaded_once_and_reused():
    loads: list[WhisperModelRequest] = []
    model = FakeWhisperModel([FakeSegment(0.0, 1.0, "text")])
    recognizer = recognizer_for(model, loader=lambda request: loads.append(request) or model)
    recognizer.transcribe(clip(2.0), RecognitionHints())
    recognizer.transcribe(clip(2.0), RecognitionHints())
    assert len(loads) == 1


def test_empty_spans_are_skipped():
    model = FakeWhisperModel([FakeSegment(0.0, 1.0, "text")])
    hints = RecognitionHints(segments=(TimeSpan(9.0, 9.0),))
    transcript = recognizer_for(model).transcribe(clip(2.0), hints)
    assert transcript.utterances == ()
    assert model.calls == []


def test_the_registry_builds_the_whisper_engine_from_settings(tmp_path):
    settings = AsrSettings(engine="whisper", model_id="large-v3-turbo", beam_size=3, language="fr")
    built = build_recognizer(settings, tmp_path)
    assert isinstance(built, WhisperRecognizer)
    assert built.beam_size == 3
    assert built.language == "fr"
    assert built.compute_type == "int8"
    assert built.models_dir == tmp_path


def test_the_faster_whisper_module_is_imported_lazily(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class StubModel:
        def __init__(self, source, **kwargs):
            captured["source"] = source
            captured.update(kwargs)

        def transcribe(self, audio, **options):
            return iter(()), FakeInfo()

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = StubModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    load_faster_whisper_model(
        WhisperModelRequest(
            source="tiny",
            device="cpu",
            compute_type="int8",
            download_root=str(tmp_path),
            local_files_only=True,
        )
    )
    assert captured == {
        "source": "tiny",
        "device": "cpu",
        "compute_type": "int8",
        "download_root": str(tmp_path),
        "local_files_only": True,
    }


def test_a_missing_faster_whisper_is_reported_as_a_recognition_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(RecognitionError, match="faster-whisper is not installed"):
        load_faster_whisper_model(
            WhisperModelRequest(
                source="tiny",
                device="cpu",
                compute_type="int8",
                download_root=None,
                local_files_only=False,
            )
        )


def test_model_files_must_look_like_ctranslate2_weights(tmp_path: Path):
    empty = tmp_path / "tiny"
    empty.mkdir()
    assert local_model_directory(tmp_path, "tiny") is None
