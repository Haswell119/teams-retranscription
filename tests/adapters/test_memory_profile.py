from hansard.adapters.asr.onnx_engine import OnnxRecognizer
from hansard.adapters.asr.registry import build_recognizer
from hansard.config import AsrSettings


def options_for(profile):
    return OnnxRecognizer(memory_profile=profile, intra_op_threads=2)._session_options()


def test_the_compact_profile_turns_off_the_allocations_that_grow_with_input_length():
    options = options_for("compact")
    assert options.enable_cpu_mem_arena is False
    assert options.enable_mem_pattern is False


def test_the_default_profile_leaves_the_runtime_defaults_alone():
    options = options_for("default")
    assert options.enable_cpu_mem_arena is True
    assert options.enable_mem_pattern is True


def test_thread_counts_survive_either_profile():
    for profile in ("default", "compact"):
        assert options_for(profile).intra_op_num_threads == 2


def test_the_setting_reaches_the_engine(tmp_path):
    recognizer = build_recognizer(AsrSettings(engine="parakeet", memory_profile="default"), tmp_path)
    assert getattr(recognizer, "memory_profile", None) == "default"


def test_the_runtime_defaults_ship_until_the_compact_profile_is_measured():
    assert AsrSettings().memory_profile == "default"
