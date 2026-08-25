from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from hansard.adapters.storage.keys import key_for_path, resolved_path
from hansard.domain.errors import ArtifactNotFoundError

SECONDS_PER_DAY = 86_400.0
PARTIAL_SUFFIX = ".partial"

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class FilesystemArtifactStore:
    root: Path
    retention_days: int = 30
    clock: Clock = time.time

    @property
    def name(self) -> str:
        return "filesystem"

    def path_for(self, key: str) -> Path:
        return resolved_path(self.root, key)

    async def put(self, key: str, source: Path) -> str:
        return await asyncio.to_thread(self._put, key, source)

    async def get(self, key: str, destination: Path) -> Path:
        return await asyncio.to_thread(self._get, key, destination)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(lambda: self.path_for(key).is_file())

    async def list_keys(self, prefix: str = "") -> tuple[str, ...]:
        return await asyncio.to_thread(self._list_keys, prefix)

    async def purge_older_than(self, days: int | None = None) -> tuple[str, ...]:
        return await asyncio.to_thread(self._purge_older_than, days)

    def _put(self, key: str, source: Path) -> str:
        if not source.is_file():
            raise ArtifactNotFoundError(f"cannot store missing file {source}")
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = _staging_path(target)
        try:
            shutil.copyfile(source, staged)
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)
        return target.as_uri()

    def _get(self, key: str, destination: Path) -> Path:
        source = self.path_for(key)
        if not source.is_file():
            raise ArtifactNotFoundError(f"unknown artifact {key}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = _staging_path(destination)
        try:
            shutil.copyfile(source, staged)
            staged.replace(destination)
        finally:
            staged.unlink(missing_ok=True)
        return destination

    def _delete(self, key: str) -> None:
        target = self.path_for(key)
        target.unlink(missing_ok=True)
        self._prune_empty_directories(target.parent)

    def _list_keys(self, prefix: str) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        base = self.root
        keys = (key_for_path(base, path) for path in base.rglob("*") if path.is_file())
        return tuple(sorted(key for key in keys if key.startswith(prefix) and not _is_staging(key)))

    def _purge_older_than(self, days: int | None) -> tuple[str, ...]:
        retention = self.retention_days if days is None else days
        if retention <= 0 or not self.root.is_dir():
            return ()
        cutoff = self.clock() - retention * SECONDS_PER_DAY
        removed: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            removed.append(key_for_path(self.root, path))
            path.unlink(missing_ok=True)
            self._prune_empty_directories(path.parent)
        return tuple(removed)

    def _prune_empty_directories(self, directory: Path) -> None:
        root = self.root.resolve()
        current = directory.resolve()
        while current != root and root in current.parents and current.is_dir():
            if any(current.iterdir()):
                return
            current.rmdir()
            current = current.parent


def _staging_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.{uuid4().hex}{PARTIAL_SUFFIX}")


def _is_staging(key: str) -> bool:
    return key.rsplit("/", 1)[-1].startswith(".") and key.endswith(PARTIAL_SUFFIX)
