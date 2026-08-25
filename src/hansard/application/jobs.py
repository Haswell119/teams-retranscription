from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from hansard.domain.errors import ArtifactNotFound
from hansard.domain.meeting import JobState, MeetingRequest
from hansard.domain.minutes import Minutes
from hansard.domain.speakers import Roster
from hansard.domain.transcript import Transcript


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class JobRecord:
    identifier: str
    request: MeetingRequest
    state: JobState
    created_at: datetime
    updated_at: datetime
    transcript: Transcript | None = None
    minutes: Minutes | None = None
    roster: Roster = field(default_factory=Roster)
    artifacts: tuple[Path, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    stage_seconds: dict[str, float] = field(default_factory=dict)
    error: str | None = None

    def advanced(self, state: JobState, **changes: object) -> JobRecord:
        return replace(self, state=state, updated_at=_now(), **changes)  # type: ignore[arg-type]


@runtime_checkable
class JobStore(Protocol):
    async def create(self, request: MeetingRequest) -> JobRecord: ...

    async def get(self, identifier: str) -> JobRecord: ...

    async def list(self, limit: int) -> tuple[JobRecord, ...]: ...

    async def save(self, record: JobRecord) -> JobRecord: ...


@dataclass(slots=True)
class InMemoryJobStore:
    records: dict[str, JobRecord] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    capacity: int = 512

    async def create(self, request: MeetingRequest) -> JobRecord:
        moment = _now()
        record = JobRecord(
            identifier=request.identifier,
            request=request,
            state=JobState.PENDING,
            created_at=moment,
            updated_at=moment,
        )
        self.records[record.identifier] = record
        self.order.append(record.identifier)
        while len(self.order) > self.capacity:
            self.records.pop(self.order.pop(0), None)
        return record

    async def get(self, identifier: str) -> JobRecord:
        record = self.records.get(identifier)
        if record is None:
            raise ArtifactNotFound(f"unknown job {identifier}")
        return record

    async def list(self, limit: int) -> tuple[JobRecord, ...]:
        selected = [self.records[key] for key in reversed(self.order) if key in self.records]
        return tuple(selected[:limit])

    async def save(self, record: JobRecord) -> JobRecord:
        self.records[record.identifier] = record
        return record


JobHandler = Callable[[JobRecord], Awaitable[JobRecord]]


@dataclass(slots=True)
class JobQueue:
    store: JobStore
    handler: JobHandler
    concurrency: int = 2
    _queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue, init=False)
    _workers: list[asyncio.Task[None]] = field(default_factory=list, init=False)

    async def start(self) -> None:
        if self._workers:
            return
        self._workers = [asyncio.create_task(self._worker()) for _ in range(max(1, self.concurrency))]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with_suppressed_cancellation = asyncio.gather(worker, return_exceptions=True)
            await with_suppressed_cancellation
        self._workers.clear()

    async def submit(self, request: MeetingRequest) -> JobRecord:
        record = await self.store.create(request)
        await self._queue.put(record.identifier)
        return record

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def _worker(self) -> None:
        while True:
            identifier = await self._queue.get()
            try:
                record = await self.store.get(identifier)
                await self.store.save(record.advanced(JobState.TRANSCRIBING))
                completed = await self.handler(record)
                await self.store.save(completed)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                try:
                    failed = await self.store.get(identifier)
                    await self.store.save(failed.advanced(JobState.FAILED, error=str(error)))
                except ArtifactNotFound:
                    pass
            finally:
                self._queue.task_done()
