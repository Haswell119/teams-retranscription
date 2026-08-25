from __future__ import annotations

from collections.abc import Callable

from hansard.adapters.storage.filesystem import FilesystemArtifactStore
from hansard.adapters.storage.s3 import S3ArtifactStore
from hansard.config import StorageSettings
from hansard.domain.errors import ConfigurationError
from hansard.ports.storage import ArtifactStore

ArtifactStoreFactory = Callable[[StorageSettings], ArtifactStore]

_FACTORIES: dict[str, ArtifactStoreFactory] = {}


def register_artifact_store(name: str, factory: ArtifactStoreFactory) -> None:
    _FACTORIES[name] = factory


def available_artifact_stores() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def build_artifact_store(settings: StorageSettings) -> ArtifactStore:
    factory = _FACTORIES.get(settings.backend)
    if factory is None:
        raise ConfigurationError(
            f"unknown storage backend '{settings.backend}', available: {available_artifact_stores()}"
        )
    return factory(settings)


def _build_filesystem(settings: StorageSettings) -> ArtifactStore:
    return FilesystemArtifactStore(root=settings.root, retention_days=settings.retention_days)


def _build_s3(settings: StorageSettings) -> ArtifactStore:
    if not settings.bucket:
        raise ConfigurationError("storage backend 's3' requires HANSARD_STORAGE__BUCKET")
    return S3ArtifactStore(
        bucket=settings.bucket,
        endpoint_url=settings.endpoint_url,
        region=settings.region,
        access_key=settings.access_key,
        secret_key=settings.secret_key,
        ca_bundle=settings.ca_bundle,
        force_path_style=settings.force_path_style,
        retention_days=settings.retention_days,
    )


register_artifact_store("filesystem", _build_filesystem)
register_artifact_store("s3", _build_s3)
