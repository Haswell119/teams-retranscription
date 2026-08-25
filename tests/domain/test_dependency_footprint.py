import importlib.util

import pytest

HEAVY_PACKAGES = ("torch", "tensorflow", "jax", "transformers", "nemo")


@pytest.mark.parametrize("package", HEAVY_PACKAGES)
def test_the_default_install_avoids_heavy_frameworks(package):
    if importlib.util.find_spec(package) is not None:
        pytest.skip(f"{package} is installed in this environment, probably by an optional extra")
    assert importlib.util.find_spec(package) is None


def test_the_recognition_stack_is_onnx():
    assert importlib.util.find_spec("onnxruntime") is not None
    assert importlib.util.find_spec("onnx_asr") is not None


def test_importing_the_package_pulls_in_no_framework():
    import subprocess
    import sys

    probe = (
        "import sys, hansard, hansard.factory, hansard.application.pipeline;"
        "loaded=[n for n in ('torch','tensorflow','jax') if n in sys.modules];"
        "print(','.join(loaded))"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""
