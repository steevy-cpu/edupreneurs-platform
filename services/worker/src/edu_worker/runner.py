"""The worker loop: claim, run, heartbeat, complete or fail — with a bound on
concurrency and a graceful stop.

Guarantees and their limits (see the migration for the database side):

* A job is leased to one worker at a time. While a handler runs, its lease is
  renewed. If renewal reports that the lease was lost, the handler is cancelled
  and nothing is reported for that job.
* A crash needs no clean-up: the lease runs out and another worker takes the job
  again. Handlers must therefore be idempotent (delivery is at-least-once).
* ``stop()`` is graceful: no new job is claimed, running handlers finish (up to
  ``grace_seconds``); whatever is still running after that is cancelled and
  left to lease expiry, exactly like a crash.
* Only the exception CLASS of a failed handler is stored. Messages may contain
  personal data and never leave the process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import socket
from collections.abc import Awaitable, Callable, Mapping

from edu_worker.queue import Job, JobQueue

logger = logging.getLogger("edu_worker")

Handler = Callable[[Job], Awaitable[None]]


def new_worker_id() -> str:
    """Unique per process: it is the fencing token of every lease this process takes."""
    host = "".join(c if c.isalnum() else "-" for c in socket.gethostname())[:40] or "host"
    return f"{host}:{os.getpid()}:{secrets.token_hex(6)}"


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        handlers: Mapping[str, Handler],
        *,
        worker_id: str | None = None,
        concurrency: int = 4,
        lease_seconds: int = 60,
        poll_interval: float = 1.0,
        grace_seconds: float = 30.0,
    ) -> None:
        if not handlers:
            raise ValueError("at least one handler is required")
        if not 1 <= concurrency <= 64:
            raise ValueError("concurrency must be between 1 and 64")
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        self.queue = queue
        self.handlers = dict(handlers)
        self.worker_id = worker_id or new_worker_id()
        self.concurrency = concurrency
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.grace_seconds = grace_seconds
        self.completed = 0
        self.failed = 0
        self.lost = 0
        self._stop = asyncio.Event()
        self._running: set[asyncio.Task[None]] = set()

    def stop(self) -> None:
        """Ask the loop to finish: claim nothing new, let running jobs end."""
        self._stop.set()

    async def run(self, *, max_jobs: int | None = None, exit_when_idle: bool = False) -> int:
        """Work until ``stop()``, ``max_jobs`` claimed, or (optionally) an empty
        queue with nothing running. Returns the number of jobs claimed."""
        claimed = 0
        kinds = sorted(self.handlers)
        logger.info("worker %s started for kinds %s", self.worker_id, kinds)
        try:
            while not self._stop.is_set():
                free = self.concurrency - len(self._running)
                if max_jobs is not None:
                    free = min(free, max_jobs - claimed)
                jobs: list[Job] = []
                if free > 0:
                    jobs = await self.queue.claim(self.worker_id, kinds, free, self.lease_seconds)
                for job in jobs:
                    claimed += 1
                    task = asyncio.create_task(self._run_job(job), name=f"job-{job.id}")
                    self._running.add(task)
                    task.add_done_callback(self._running.discard)
                if max_jobs is not None and claimed >= max_jobs:
                    break
                if not jobs:
                    if exit_when_idle and not self._running:
                        break
                    await self._wait(self.poll_interval)
        finally:
            await self._drain()
            logger.info(
                "worker %s stopped: completed=%d failed=%d lost=%d",
                self.worker_id,
                self.completed,
                self.failed,
                self.lost,
            )
        return claimed

    async def _wait(self, seconds: float) -> None:
        """Sleep, but wake up at once on stop() or when a running job ends."""
        stop = asyncio.create_task(self._stop.wait())
        try:
            await asyncio.wait(
                {stop, *self._running}, timeout=seconds, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            stop.cancel()

    async def _drain(self) -> None:
        if not self._running:
            return
        _, pending = await asyncio.wait(set(self._running), timeout=self.grace_seconds)
        for task in pending:  # still running after the grace period: like a crash
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run_job(self, job: Job) -> None:
        handler = self.handlers[job.kind]
        work: asyncio.Future[None] = asyncio.ensure_future(handler(job))
        beat = asyncio.create_task(self._heartbeat(job, work), name=f"heartbeat-{job.id}")
        try:
            await work
        except asyncio.CancelledError:
            # Lease lost (heartbeat cancelled the handler) or shutdown after the
            # grace period: report nothing, the lease decides.
            work.cancel()
            self.lost += 1
            logger.warning("job %s (%s) abandoned on attempt %d", job.id, job.kind, job.attempt)
            return
        except Exception as exc:
            error_class = type(exc).__name__
            status = await self.queue.fail(job.id, self.worker_id, error_class)
            self.failed += 1
            # The class name only: exception messages can contain personal data.
            logger.warning(
                "job %s (%s) failed on attempt %d with %s -> %s",
                job.id,
                job.kind,
                job.attempt,
                error_class,
                status or "lease lost",
            )
            return
        finally:
            beat.cancel()
        if await self.queue.complete(job.id, self.worker_id):
            self.completed += 1
        else:
            self.lost += 1
            logger.warning("job %s (%s) finished after its lease was lost", job.id, job.kind)

    async def _heartbeat(self, job: Job, work: asyncio.Future[None]) -> None:
        interval = max(self.lease_seconds / 3, 0.2)
        while True:
            await asyncio.sleep(interval)
            try:
                still_mine = await self.queue.heartbeat(job.id, self.worker_id, self.lease_seconds)
            except Exception as exc:
                logger.warning("heartbeat for job %s failed: %s", job.id, type(exc).__name__)
                continue
            if not still_mine:
                work.cancel()
                return
