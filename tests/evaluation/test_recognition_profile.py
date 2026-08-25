from hansard.config import Settings
from hansard.evaluation.run import _recognition_profile


def test_the_shipped_default_is_recorded_as_float32():
    assert _recognition_profile(Settings())["precision"] == "float32"


def test_the_low_memory_profile_is_recorded_by_name():
    settings = Settings()
    settings.asr.quantization = "int8"
    assert _recognition_profile(settings)["precision"] == "int8"


def test_the_settings_that_moved_a_published_number_are_all_recorded():
    profile = _recognition_profile(Settings())
    assert set(profile) == {
        "model_id",
        "precision",
        "batch_size",
        "batch_seconds",
        "max_segment_seconds",
        "merge_similarity",
        "minimum_speaker_seconds",
    }


def test_the_profile_follows_the_settings_it_is_given():
    settings = Settings()
    settings.diarization.merge_similarity = 0.5
    settings.audio.max_segment_seconds = 42.0
    profile = _recognition_profile(settings)
    assert profile["merge_similarity"] == 0.5
    assert profile["max_segment_seconds"] == 42.0
