import pytest

from hansard.evaluation.metrics.system import (
    RealTimeFactor,
    ResourceProbe,
    peak_resident_memory_mb,
)


def test_real_time_factor():
    factor = RealTimeFactor(processing_seconds=5.0, audio_seconds=10.0)
    assert factor.value == pytest.approx(0.5)
    assert factor.speedup == pytest.approx(2.0)


def test_real_time_factor_handles_zero_durations():
    assert RealTimeFactor(1.0, 0.0).value == pytest.approx(0.0)
    assert RealTimeFactor(0.0, 1.0).speedup == pytest.approx(0.0)


def test_resource_probe_measures_usage():
    with ResourceProbe() as probe:
        sum(index * index for index in range(200_000))
    usage = probe.usage
    assert usage.wall_seconds > 0.0
    assert usage.cpu_seconds >= 0.0
    assert usage.peak_rss_mb > 0.0
    assert usage.vram_mb is None or usage.vram_mb >= 0.0


def test_resource_probe_requires_completed_context():
    probe = ResourceProbe()
    with pytest.raises(RuntimeError, match="after the context exits"):
        _ = probe.usage


def test_peak_resident_memory_is_positive():
    assert peak_resident_memory_mb() > 0.0
