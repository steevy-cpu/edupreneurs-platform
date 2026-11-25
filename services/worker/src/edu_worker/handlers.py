"""Handler registry. A handler is ``async def handler(job: Job) -> None``; it
raises to fail the attempt. Handlers must be idempotent."""

from __future__ import annotations

import asyncio

from edu_worker.queue import Job
from edu_worker.runner import Handler


async def noop(job: Job) -> None:
    """Does nothing, successfully. Proves the plumbing end to end."""


async def _test_sleep(job: Job) -> None:
    await asyncio.sleep(min(float(job.payload.get("seconds", 1)), 60.0))


async def _test_fail(job: Job) -> None:
    raise RuntimeError("synthetic failure requested by a test job")


def default_handlers() -> dict[str, Handler]:
    """What a production worker would run today: only the no-op."""
    return {"noop": noop}


def test_handlers() -> dict[str, Handler]:
    """Extra kinds for the test-suite. Never enabled unless asked for."""
    return {"test_sleep": _test_sleep, "test_fail": _test_fail}


test_handlers.__test__ = False  # type: ignore[attr-defined]  # not a pytest test
