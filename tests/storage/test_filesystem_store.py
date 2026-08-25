from __future__ import annotations

import os

import pytest

from hansard.adapters.storage.filesystem import FilesystemArtifactStore
from hansard.domain.errors import ArtifactKeyError, ArtifactNotFoundError
from hansard.ports.storage import ArtifactStore

DAY_SECONDS = 86_400.0
NOW = 1_800_000_000.0


@pytest.fixture
def store(tmp_path):
    return FilesystemArtifactStore(root=tmp_path / "artifacts", clock=lambda: NOW)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source" / "transcript.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Comité\n\nLa séance est ouverte.\n", encoding="utf-8")
    return path


def test_it_satisfies_the_artifact_store_port(store):
    assert isinstance(store, ArtifactStore)
    assert store.name == "filesystem"


async def test_put_get_list_and_delete_round_trip(store, source, tmp_path):
    location = await store.put("meeting-1/transcript.md", source)
    assert location.startswith("file://")
    assert await store.exists("meeting-1/transcript.md")
    assert await store.list_keys() == ("meeting-1/transcript.md",)

    restored = await store.get("meeting-1/transcript.md", tmp_path / "restored" / "transcript.md")
    assert restored.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")

    await store.delete("meeting-1/transcript.md")
    assert not await store.exists("meeting-1/transcript.md")
    assert await store.list_keys() == ()


async def test_deleting_twice_is_harmless(store, source):
    await store.put("meeting-1/transcript.md", source)
    await store.delete("meeting-1/transcript.md")
    await store.delete("meeting-1/transcript.md")


async def test_listing_can_be_filtered_by_prefix(store, source):
    await store.put("meeting-1/transcript.md", source)
    await store.put("meeting-2/transcript.md", source)
    assert await store.list_keys("meeting-2/") == ("meeting-2/transcript.md",)


async def test_writes_are_atomic_and_leave_no_partial_files(store, source):
    await store.put("meeting-1/transcript.md", source)
    remaining = [path.name for path in store.root.rglob("*") if path.is_file()]
    assert remaining == ["transcript.md"]


async def test_overwriting_replaces_the_previous_content(store, source, tmp_path):
    await store.put("meeting-1/transcript.md", source)
    newer = tmp_path / "newer.md"
    newer.write_text("nouvelle version", encoding="utf-8")
    await store.put("meeting-1/transcript.md", newer)
    restored = await store.get("meeting-1/transcript.md", tmp_path / "out.md")
    assert restored.read_text(encoding="utf-8") == "nouvelle version"


async def test_a_traversing_key_is_refused_by_every_operation(store, source):
    for attack in ("../../etc/passwd", "/etc/passwd", "meeting/../../secret"):
        with pytest.raises(ArtifactKeyError):
            await store.put(attack, source)
        with pytest.raises(ArtifactKeyError):
            await store.exists(attack)
        with pytest.raises(ArtifactKeyError):
            await store.delete(attack)


async def test_storing_a_missing_source_is_reported(store, tmp_path):
    with pytest.raises(ArtifactNotFoundError):
        await store.put("meeting-1/transcript.md", tmp_path / "absent.md")


async def test_reading_an_unknown_key_is_reported(store, tmp_path):
    with pytest.raises(ArtifactNotFoundError):
        await store.get("meeting-1/transcript.md", tmp_path / "out.md")


async def test_retention_purges_only_expired_artifacts(store, source):
    await store.put("old/transcript.md", source)
    await store.put("fresh/transcript.md", source)
    stale = NOW - 45 * DAY_SECONDS
    os.utime(store.path_for("old/transcript.md"), (stale, stale))
    os.utime(store.path_for("fresh/transcript.md"), (NOW, NOW))

    purged = await store.purge_older_than()
    assert purged == ("old/transcript.md",)
    assert await store.list_keys() == ("fresh/transcript.md",)
    assert not store.path_for("old/transcript.md").parent.exists()


async def test_an_explicit_horizon_overrides_the_configured_retention(store, source):
    await store.put("meeting-1/transcript.md", source)
    stale = NOW - 3 * DAY_SECONDS
    os.utime(store.path_for("meeting-1/transcript.md"), (stale, stale))
    assert await store.purge_older_than() == ()
    assert await store.purge_older_than(2) == ("meeting-1/transcript.md",)


async def test_zero_retention_never_purges(tmp_path, source):
    store = FilesystemArtifactStore(root=tmp_path / "artifacts", retention_days=0, clock=lambda: NOW)
    await store.put("meeting-1/transcript.md", source)
    assert await store.purge_older_than() == ()
    assert await store.list_keys() == ("meeting-1/transcript.md",)


async def test_listing_an_absent_root_is_empty(tmp_path):
    assert await FilesystemArtifactStore(root=tmp_path / "missing").list_keys() == ()
