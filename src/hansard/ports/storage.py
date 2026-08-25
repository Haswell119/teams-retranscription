from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ArtifactStore(Protocol):
    @property
    def name(self) -> str: ...

    async def put(self, key: str, source: Path) -> str: ...

    async def get(self, key: str, destination: Path) -> Path: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...
