from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from hansard.adapters.storage.filesystem import FilesystemArtifactStore
from hansard.adapters.storage.registry import available_artifact_stores, build_artifact_store
from hansard.adapters.storage.s3 import S3ArtifactStore
from hansard.config import Settings, StorageSettings
from hansard.domain.errors import ConfigurationError
from hansard.factory import Composition


def test_both_backends_are_registered():
    assert available_artifact_stores() == ("filesystem", "s3")


def test_the_filesystem_backend_is_built_from_settings(tmp_path):
    settings = StorageSettings(root=tmp_path, retention_days=7)
    store = build_artifact_store(settings)
    assert isinstance(store, FilesystemArtifactStore)
    assert store.root == tmp_path
    assert store.retention_days == 7


def test_the_s3_backend_is_built_from_settings():
    settings = StorageSettings(
        backend="s3",
        bucket="hansard",
        endpoint_url="https://objects.internal",
        region="eu-west-3",
        access_key=SecretStr("AKIA"),
        secret_key=SecretStr("shhh"),
        ca_bundle=Path("/etc/ssl/certs/internal.pem"),
        retention_days=90,
    )
    store = build_artifact_store(settings)
    assert isinstance(store, S3ArtifactStore)
    assert store.bucket == "hansard"
    assert store.endpoint_url == "https://objects.internal"
    assert store.region == "eu-west-3"
    assert store.force_path_style is True
    assert store.ca_bundle == Path("/etc/ssl/certs/internal.pem")
    assert store.retention_days == 90


def test_the_s3_backend_requires_a_bucket():
    with pytest.raises(ConfigurationError, match="BUCKET"):
        build_artifact_store(StorageSettings(backend="s3"))


def test_an_unknown_backend_is_refused():
    settings = StorageSettings()
    object.__setattr__(settings, "backend", "dropbox")
    with pytest.raises(ConfigurationError, match="unknown storage backend"):
        build_artifact_store(settings)


def test_the_composition_resolves_a_relative_root_inside_the_workspace(tmp_path):
    settings = Settings()
    settings.runtime.workspace = tmp_path / "workspace"
    store = Composition(settings).artifact_store()
    assert isinstance(store, FilesystemArtifactStore)
    assert store.root == tmp_path / "workspace" / "artifacts"


def test_the_composition_keeps_an_absolute_root(tmp_path):
    settings = Settings()
    settings.storage.root = tmp_path / "elsewhere"
    store = Composition(settings).artifact_store()
    assert isinstance(store, FilesystemArtifactStore)
    assert store.root == tmp_path / "elsewhere"
