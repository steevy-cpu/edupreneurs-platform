"""Thin, typed access to the ``ops.*`` job-queue functions.

The worker logs in as ``edu_worker_login`` (member of ``edu_worker`` only). That
role holds no table privilege: these five function calls are everything it can
do to the queue.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg


@dataclass(frozen=True)
class Job:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    #: 1 for the first attempt. A retried job has a higher number.
    attempt: int
    max_attempts: int
    lease_until: datetime


def plain_postgres_url(url: str) -> str:
    """Accept the SQLAlchemy-style URL written to ``.env`` as well as a plain one."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


class JobQueue:
    """All queue operations of one worker process, over one connection pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def session_kind(self) -> str:
        return str(await self._pool.fetchval("SELECT ops.session_kind()"))

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        run_after: datetime | None = None,
        max_attempts: int = 5,
    ) -> uuid.UUID:
        job_id: uuid.UUID = await self._pool.fetchval(
            "SELECT ops.enqueue_job($1, $2::jsonb, $3, $4, $5)",
            kind,
            json.dumps(payload or {}),
            idempotency_key,
            run_after,
            max_attempts,
        )
        return job_id

    async def claim(
        self, worker_id: str, kinds: list[str], limit: int, lease_seconds: int
    ) -> list[Job]:
        rows = await self._pool.fetch(
            "SELECT job_id, kind, payload, attempt, max_attempts, lease_until "
            "FROM ops.claim_jobs($1, $2::text[], $3, $4)",
            worker_id,
            kinds,
            limit,
            lease_seconds,
        )
        return [
            Job(
                id=row["job_id"],
                kind=row["kind"],
                payload=json.loads(row["payload"]),
                attempt=row["attempt"],
                max_attempts=row["max_attempts"],
                lease_until=row["lease_until"],
            )
            for row in rows
        ]

    async def heartbeat(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        return bool(
            await self._pool.fetchval(
                "SELECT ops.heartbeat_job($1, $2, $3)", job_id, worker_id, lease_seconds
            )
        )

    async def complete(self, job_id: uuid.UUID, worker_id: str) -> bool:
        return bool(await self._pool.fetchval("SELECT ops.complete_job($1, $2)", job_id, worker_id))

    async def fail(self, job_id: uuid.UUID, worker_id: str, error_class: str) -> str | None:
        status: str | None = await self._pool.fetchval(
            "SELECT ops.fail_job($1, $2, $3)", job_id, worker_id, error_class
        )
        return status
