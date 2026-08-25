from __future__ import annotations

import pytest

from hansard.adapters.storage.keys import resolved_path, sanitised_key
from hansard.domain.errors import ArtifactKeyError

TRAVERSAL_ATTACKS = [
    "../../etc/passwd",
    "..",
    "a/../../b",
    "a/./b",
    "/etc/passwd",
    "//etc/passwd",
    "a//b",
    "..\\..\\windows\\system32",
    "C:/windows/system32",
    "meeting/\x00passwd",
    "meeting/\ntranscript.md",
    " leading-space.md",
    "trailing-space.md ",
    "meeting/ padded /file.md",
    "",
]


@pytest.mark.parametrize("attack", TRAVERSAL_ATTACKS)
def test_hostile_keys_are_rejected(attack):
    with pytest.raises(ArtifactKeyError):
        sanitised_key(attack)


@pytest.mark.parametrize(
    "key",
    [
        "transcript.md",
        "2026-08-25/comité-de-direction/transcript.vtt",
        "a1b2c3/minutes.html",
        "dossier.avec.points/fichier_final-2.json",
    ],
)
def test_legitimate_keys_survive_unchanged(key):
    assert sanitised_key(key) == key


def test_overlong_keys_are_rejected():
    with pytest.raises(ArtifactKeyError):
        sanitised_key("a" * 513)


def test_resolved_paths_stay_under_the_root(tmp_path):
    assert resolved_path(tmp_path, "meeting/transcript.md") == tmp_path / "meeting" / "transcript.md"


def test_symlinks_that_escape_the_root_are_rejected(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "escape").symlink_to(tmp_path / "outside", target_is_directory=True)
    (tmp_path / "outside").mkdir()
    with pytest.raises(ArtifactKeyError):
        resolved_path(root, "escape/passwd")
