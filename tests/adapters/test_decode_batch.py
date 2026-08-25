from dataclasses import dataclass

import numpy as np
import pytest

from hansard.adapters.asr.onnx_engine import OnnxRecognizer
from hansard.domain.errors import RecognitionError
from hansard.domain.timespan import TimeSpan


@dataclass
class FakeResult:
    text: str
    tokens: tuple[str, ...] = ()
    timestamps: tuple[float, ...] = ()
    logprobs: tuple[float, ...] = ()


@dataclass
class FakeModel:
    results: list[FakeResult]

    def recognize(self, waveforms, **_options):
        return self.results


def decode(results, spans):
    recognizer = OnnxRecognizer()
    waveforms = [np.zeros(16_000, dtype=np.float32) for _ in spans]
    return recognizer._decode_batch(FakeModel(results), waveforms, spans, "en")


def test_a_result_per_segment_is_decoded():
    spans = [TimeSpan(0.0, 1.0), TimeSpan(1.0, 2.0)]
    utterances = decode([FakeResult("alpha"), FakeResult("beta")], spans)
    assert [item.text for item in utterances] == ["alpha", "beta"]


def test_a_silent_segment_produces_no_utterance():
    spans = [TimeSpan(0.0, 1.0), TimeSpan(1.0, 2.0)]
    assert [item.text for item in decode([FakeResult("alpha"), FakeResult("  ")], spans)] == ["alpha"]


def test_fewer_results_than_segments_is_an_error_rather_than_lost_speech():
    spans = [TimeSpan(0.0, 1.0), TimeSpan(1.0, 2.0), TimeSpan(2.0, 3.0)]
    with pytest.raises(RecognitionError, match="2 results for 3 speech segments"):
        decode([FakeResult("alpha"), FakeResult("beta")], spans)
