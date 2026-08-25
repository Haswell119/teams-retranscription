import pytest

from hansard.adapters.asr.onnx_engine import OnnxRecognizer


def test_int8_profile_reports_bundle_memory():
    profile = OnnxRecognizer(quantization="int8").profile
    assert profile.name == "onnx:nemo-parakeet-tdt-0.6b-v3"
    assert profile.metadata["quantization"] == "int8"
    assert profile.resident_memory_mb == 1500


def test_float32_profile_doubles_the_memory_estimate():
    int8 = OnnxRecognizer(quantization="int8").profile
    float32 = OnnxRecognizer(quantization=None).profile
    assert float32.metadata["quantization"] == "none"
    assert float32.resident_memory_mb == 2 * int8.resident_memory_mb


@pytest.mark.parametrize("language", ["fr", "en"])
def test_multilingual_profile_covers_the_meeting_languages(language):
    assert language in OnnxRecognizer().profile.languages


def test_unknown_model_falls_back_to_a_conservative_profile():
    profile = OnnxRecognizer(model_id="not-a-real-model").profile
    assert profile.languages == ("multilingual",)
    assert profile.license_identifier == "unknown"
