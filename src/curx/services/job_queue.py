from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


class IngestionJobQueue(Protocol):
    async def enqueue(self, job_id: UUID) -> None: ...

    async def close(self) -> None: ...


class ArqIngestionJobQueue:
    def __init__(self, redis_url: str) -> None:
        self._redis_settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> ArqRedis:
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is None:
                self._pool = await create_pool(self._redis_settings)
        return self._pool

    async def enqueue(self, job_id: UUID) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(
            "process_ingestion_job",
            str(job_id),
            _job_id=f"ingestion:{job_id}",
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


class InlineIngestionJobQueue:
    def __init__(self, runner: Callable[[UUID], None]) -> None:
        self._runner = runner
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, job_id: UUID) -> None:
        task = asyncio.create_task(asyncio.to_thread(self._runner, job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


class RecordingIngestionJobQueue:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    async def enqueue(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)

    async def close(self) -> None:
        return None

