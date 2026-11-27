"""The background worker (B2): leasing, retry after a crash, dead-lettering,
idempotent enqueue — against the real local database, with real processes
where a crash has to be real."""

# ruff: noqa: F811  (fixtures imported from tests.staff_fixtures are requested by name)
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from edu_worker import Job, JobQueue, Worker
from edu_worker.handlers import default_handlers, noop, test_handlers
from tests.helpers import STUDENT_A
from tests.staff_fixtures import staff_app, staff_settings, worker_url  # noqa: F401

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
async def empty_queue(admin: asyncpg.Pool) -> AsyncIterator[None]:
    await admin.execute("DELETE FROM app.background_jobs")
    yield
    await admin.execute("DELETE FROM app.background_jobs")


@pytest.fixture
async def pool(local_env: dict[str, str]) -> AsyncIterator[asyncpg.Pool]:
    """Connections as the real worker login."""
    created = await asyncpg.create_pool(worker_url(local_env), min_size=1, max_size=10, timeout=10)
    yield created
    await created.close()


@pytest.fixture
def queue(pool: asyncpg.Pool) -> JobQueue:
    return JobQueue(pool)


async def job_row(admin: asyncpg.Pool, job_id: uuid.UUID) -> dict[str, Any]:
    row = await admin.fetchrow(
        "SELECT status, attempts, max_attempts, leased_by, lease_until, error_class, run_after, "
        "run_after - now() AS wait FROM app.background_jobs WHERE id = $1",
        job_id,
    )
    assert row is not None
    return dict(row)


async def make_due(admin: asyncpg.Pool, job_id: uuid.UUID) -> None:
    """Skip the backoff of one job (instead of waiting for it)."""
    await admin.execute("UPDATE app.background_jobs SET run_after = now() WHERE id = $1", job_id)


async def wait_for(condition: Any, seconds: float = 10.0) -> None:
    """Poll the database until ``condition()`` holds (it changes in another process)."""
    async with asyncio.timeout(seconds):
        while not await condition():  # noqa: ASYNC110
            await asyncio.sleep(0.05)


# ------------------------------------------------------------------ the login
async def test_the_worker_login_is_a_worker_and_nothing_else(
    queue: JobQueue, pool: asyncpg.Pool
) -> None:
    assert await queue.session_kind() == "worker"
    assert await pool.fetchval("SELECT session_user") == "edu_worker_login"
    for statement in (
        "SELECT * FROM app.background_jobs",
        "UPDATE app.background_jobs SET status = 'completed'",
        "DELETE FROM app.background_jobs",
        "SELECT ops.job_backoff(1)",
        "SELECT staff.actor_roles()",
        "CREATE TEMP TABLE t (x int)",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await pool.execute(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT ops.enqueue_job('noop')",
        "SELECT * FROM ops.claim_jobs('w-api', ARRAY['noop'], 1, 30)",
        "SELECT ops.heartbeat_job(gen_random_uuid(), 'w-api', 30)",
        "SELECT ops.complete_job(gen_random_uuid(), 'w-api')",
        "SELECT ops.fail_job(gen_random_uuid(), 'w-api', 'X')",
        "SELECT * FROM app.background_jobs",
        "INSERT INTO app.background_jobs (kind) VALUES ('noop')",
    ],
)
async def test_the_student_api_cannot_touch_jobs(
    app, statement: str, queue: JobQueue, admin: asyncpg.Pool
) -> None:  # type: ignore[no-untyped-def]
    job_id = await queue.enqueue("noop")
    with pytest.raises(DBAPIError) as caught:
        async with app.state.db.transaction(STUDENT_A) as conn:
            await conn.execute(text(statement))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement
    assert (await job_row(admin, job_id))["status"] == "queued"
    assert await admin.fetchval("SELECT count(*) FROM app.background_jobs") == 1


async def test_the_staff_api_may_enqueue_but_not_work_the_queue(
    staff_app, admin: asyncpg.Pool
) -> None:  # type: ignore[no-untyped-def]
    async with staff_app.state.staff_db.transaction(None) as conn:
        job_id = (
            await conn.execute(text("SELECT ops.enqueue_job('noop', '{}', 'from-staff')"))
        ).scalar_one()
    assert (await job_row(admin, job_id))["status"] == "queued"
    for statement in (
        "SELECT * FROM ops.claim_jobs('w-staff', ARRAY['noop'], 1, 30)",
        f"SELECT ops.complete_job('{job_id}', 'w-staff')",
        f"SELECT ops.fail_job('{job_id}', 'w-staff', 'X')",
    ):
        with pytest.raises(DBAPIError) as caught:
            async with staff_app.state.staff_db.transaction(None) as conn:
                await conn.execute(text(statement))
        assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement


# ------------------------------------------------------------ idempotent enqueue
async def test_enqueue_is_idempotent_per_key_even_under_concurrency(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    key = f"welcome:{uuid.uuid4()}"
    ids = await asyncio.gather(
        *(queue.enqueue("noop", {"n": n}, idempotency_key=key) for n in range(40))
    )
    assert len(set(ids)) == 1
    assert await admin.fetchval("SELECT count(*) FROM app.background_jobs") == 1
    # still the same job after it ran: a key is spent once
    (claimed,) = await queue.claim("w-idem", ["noop"], 10, 30)
    assert claimed.id == ids[0] and await queue.complete(claimed.id, "w-idem")
    assert await queue.enqueue("noop", idempotency_key=key) == ids[0]
    assert await queue.claim("w-idem", ["noop"], 10, 30) == []
    # without a key every call is a new job
    assert await queue.enqueue("noop") != await queue.enqueue("noop")


# ----------------------------------------------------------- concurrent claimers
async def test_concurrent_claimers_never_lease_the_same_job(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    total = 300
    await asyncio.gather(*(queue.enqueue("noop", {"n": n}) for n in range(total)))

    async def claimer(name: str) -> list[uuid.UUID]:
        mine: list[uuid.UUID] = []
        while True:
            jobs = await queue.claim(name, ["noop"], 7, 60)
            if not jobs:
                return mine
            mine.extend(job.id for job in jobs)
            await asyncio.sleep(0)

    results = await asyncio.gather(*(claimer(f"w-claim-{n}") for n in range(8)))
    everything = [job_id for mine in results for job_id in mine]
    assert len(everything) == total, "every job was leased"
    assert len(set(everything)) == total, "no job was leased twice"
    assert sum(1 for mine in results if mine) >= 2, "the work really was shared between claimers"
    rows = await admin.fetch("SELECT status, attempts, leased_by FROM app.background_jobs")
    assert {(row["status"], row["attempts"]) for row in rows} == {("leased", 1)}
    owner = {row["leased_by"] for row in rows}
    assert owner == {f"w-claim-{n}" for n, mine in enumerate(results) if mine}


# ---------------------------------------------------------------- a killed worker
async def test_a_killed_workers_job_is_retried_exactly_once(
    queue: JobQueue, admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    """A real worker process takes the job and is killed with SIGKILL in the
    middle of it. Its lease runs out; a second worker runs the job once."""
    job_id = await queue.enqueue("test_sleep", {"seconds": 60})
    environment = {**os.environ, "EDU_WORKER_DATABASE_URL": local_env["EDU_WORKER_DATABASE_URL"]}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "edu_worker", "--kinds", "test_sleep", "--test-handlers",
        "--lease-seconds", "2", "--poll-interval", "0.1",
        cwd=ROOT, env=environment,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    try:

        async def leased() -> bool:
            return (await job_row(admin, job_id))["status"] == "leased"

        await wait_for(leased, seconds=20)
        first = await job_row(admin, job_id)
        assert first["attempts"] == 1 and first["leased_by"]
        # the victim renews its lease while it lives
        await asyncio.sleep(1.5)
        renewed = await job_row(admin, job_id)
        assert renewed["lease_until"] > first["lease_until"]
        process.send_signal(signal.SIGKILL)
        assert await process.wait() == -signal.SIGKILL
    finally:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()

    after_kill = await job_row(admin, job_id)
    assert (after_kill["status"], after_kill["attempts"], after_kill["leased_by"]) == (
        "leased",
        1,
        first["leased_by"],
    ), "a crash leaves the lease in place; nothing cleans up"

    runs: list[int] = []

    async def survivor_handler(job: Job) -> None:
        runs.append(job.attempt)

    survivor = Worker(queue, {"test_sleep": survivor_handler}, lease_seconds=5, poll_interval=0.1)
    # while the dead worker's lease is still valid, nobody else gets the job
    assert await queue.claim("w-impatient", ["test_sleep"], 1, 5) == []
    claimed = await asyncio.wait_for(survivor.run(max_jobs=1), timeout=15)

    assert claimed == 1 and runs == [2], "run once more, as attempt 2"
    final = await job_row(admin, job_id)
    assert (final["status"], final["attempts"], final["leased_by"]) == ("completed", 2, None)
    # the dead worker's identity can do nothing to the job any more
    assert await queue.complete(job_id, first["leased_by"]) is False
    assert await queue.fail(job_id, first["leased_by"], "Zombie") is None
    assert await queue.heartbeat(job_id, first["leased_by"], 30) is False
    # and nobody runs it a third time
    await asyncio.sleep(0.3)
    assert await queue.claim("w-late", ["test_sleep"], 10, 5) == []
    idle = Worker(queue, {"test_sleep": survivor_handler}, poll_interval=0.05)
    assert await asyncio.wait_for(idle.run(exit_when_idle=True), timeout=5) == 0
    assert runs == [2] and (await job_row(admin, job_id))["attempts"] == 2
    assert await admin.fetchval("SELECT count(*) FROM app.background_jobs") == 1


async def test_a_worker_that_lost_its_lease_stops_and_reports_nothing(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    """A stalled (not dead) worker: its lease is taken over while its handler
    still runs. The heartbeat notices, the handler is cancelled, no result is written."""
    job_id = await queue.enqueue("test_sleep", {"seconds": 30})
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow(job: Job) -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stalled = Worker(
        queue, {"test_sleep": slow}, worker_id="w-stalled", lease_seconds=1, poll_interval=0.05
    )
    task = asyncio.create_task(stalled.run(max_jobs=1))
    await asyncio.wait_for(started.wait(), timeout=5)
    # somebody else takes the job over (lease forced to "expired" instead of waiting)
    await admin.execute(
        "UPDATE app.background_jobs SET lease_until = now() - interval '1 second' WHERE id = $1",
        job_id,
    )
    (taken,) = await queue.claim("w-thief", ["test_sleep"], 1, 60)
    assert (taken.id, taken.attempt) == (job_id, 2)
    await asyncio.wait_for(cancelled.wait(), timeout=5)
    await asyncio.wait_for(task, timeout=5)
    assert (stalled.completed, stalled.failed, stalled.lost) == (0, 0, 1)
    row = await job_row(admin, job_id)
    assert (row["status"], row["leased_by"], row["attempts"]) == ("leased", "w-thief", 2)


# ------------------------------------------------------- failures and dead letter
async def test_a_failing_job_is_retried_with_backoff_and_then_dead_lettered(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    job_id = await queue.enqueue("test_fail", {"lesson_id": str(uuid.uuid4())}, max_attempts=3)
    audit_before = await admin.fetchval(
        "SELECT count(*) FROM app.audit_events WHERE action = 'job.dead'"
    )
    worker = Worker(queue, test_handlers(), poll_interval=0.05)

    expected_wait = {1: 5, 2: 10}
    for attempt in (1, 2, 3):
        assert await asyncio.wait_for(worker.run(max_jobs=1), timeout=10) == 1
        row = await job_row(admin, job_id)
        assert row["attempts"] == attempt and row["error_class"] == "RuntimeError"
        if attempt < 3:
            assert row["status"] == "queued" and row["leased_by"] is None
            assert (
                expected_wait[attempt] - 2 < row["wait"].total_seconds() <= expected_wait[attempt]
            )
            # not claimable before the backoff has passed
            assert await queue.claim("w-early", ["test_fail"], 1, 5) == []
            await make_due(admin, job_id)
    assert (await job_row(admin, job_id))["status"] == "dead"
    assert worker.failed == 3 and worker.completed == 0

    await make_due(admin, job_id)
    assert await queue.claim("w-after", ["test_fail"], 10, 5) == [], "a dead job is never run again"
    events = await admin.fetch(
        "SELECT actor_kind, actor_id, target_id, outcome, details::text AS details FROM app.audit_events "
        "WHERE action = 'job.dead' AND target_id = $1",
        job_id,
    )
    assert len(events) == 1
    assert (
        await admin.fetchval("SELECT count(*) FROM app.audit_events WHERE action = 'job.dead'")
        == audit_before + 1
    )
    event = events[0]
    assert (event["actor_kind"], event["actor_id"], event["outcome"]) == ("worker", None, "error")
    assert "RuntimeError" in event["details"] and "test_fail" in event["details"]
    # the exception MESSAGE and the payload are stored nowhere
    stored = await admin.fetchval(
        "SELECT row_to_json(j)::text FROM app.background_jobs j WHERE id = $1", job_id
    )
    assert "synthetic failure" not in stored and "synthetic failure" not in event["details"]
    assert "lesson_id" not in event["details"]


async def test_a_lease_that_runs_out_on_the_last_attempt_is_dead_not_looping(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    job_id = await queue.enqueue("noop", max_attempts=1)
    (job,) = await queue.claim("w-gone", ["noop"], 1, 1)
    assert job.attempt == job.max_attempts == 1
    await asyncio.sleep(1.2)  # a real expiry, on the database clock
    assert await queue.claim("w-next", ["noop"], 10, 30) == []
    row = await job_row(admin, job_id)
    assert (row["status"], row["error_class"], row["attempts"]) == ("dead", "LeaseExpired", 1)
    assert await queue.complete(job_id, "w-gone") is False


# ------------------------------------------------------------------- the runner
async def test_the_runner_respects_its_concurrency_bound_and_finishes_everything(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    total, bound = 24, 3
    running = 0
    peak = 0
    seen: list[uuid.UUID] = []

    async def counted(job: Job) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        seen.append(job.id)
        running -= 1

    ids = await asyncio.gather(*(queue.enqueue("noop", {"n": n}) for n in range(total)))
    await queue.enqueue("unhandled_kind")  # no handler here: must stay untouched
    worker = Worker(queue, {"noop": counted}, concurrency=bound, poll_interval=0.02)
    claimed = await asyncio.wait_for(worker.run(exit_when_idle=True), timeout=30)

    assert claimed == total and worker.completed == total and worker.failed == 0
    assert sorted(seen) == sorted(ids) and peak == bound
    states = await admin.fetch("SELECT kind, status, attempts FROM app.background_jobs")
    assert {(r["kind"], r["status"], r["attempts"]) for r in states} == {
        ("noop", "completed", 1),
        ("unhandled_kind", "queued", 0),
    }


async def test_a_graceful_stop_lets_the_running_job_finish_and_claims_nothing_new(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def held(job: Job) -> None:
        started.set()
        await release.wait()

    first = await queue.enqueue("noop")
    worker = Worker(queue, {"noop": held}, concurrency=1, poll_interval=0.05)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), timeout=5)
    second = await queue.enqueue("noop")
    worker.stop()
    await asyncio.sleep(0.3)
    assert not task.done(), "stop() waits for the running handler"
    release.set()
    assert await asyncio.wait_for(task, timeout=5) == 1
    assert (await job_row(admin, first))["status"] == "completed"
    assert (await job_row(admin, second))["status"] == "queued", (
        "nothing new was claimed after stop()"
    )
    assert (await job_row(admin, second))["attempts"] == 0


async def test_shutdown_after_the_grace_period_abandons_the_job_like_a_crash(
    queue: JobQueue, admin: asyncpg.Pool
) -> None:
    started = asyncio.Event()

    async def endless(job: Job) -> None:
        started.set()
        await asyncio.sleep(60)

    job_id = await queue.enqueue("noop")
    worker = Worker(
        queue, {"noop": endless}, lease_seconds=60, poll_interval=0.05, grace_seconds=0.2
    )
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), timeout=5)
    worker.stop()
    assert await asyncio.wait_for(task, timeout=5) == 1
    row = await job_row(admin, job_id)
    assert (row["status"], row["attempts"], row["leased_by"]) == ("leased", 1, worker.worker_id)
    assert (worker.completed, worker.failed, worker.lost) == (0, 0, 1)


async def test_the_command_line_worker_runs_noop_jobs_and_exits(
    queue: JobQueue, admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    ids = [await queue.enqueue("noop") for _ in range(5)]
    environment = {**os.environ, "EDU_WORKER_DATABASE_URL": local_env["EDU_WORKER_DATABASE_URL"]}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "edu_worker", "--kinds", "noop", "--exit-when-idle", "--poll-interval", "0.1",
        cwd=ROOT, env=environment,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, output.decode()
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.background_jobs WHERE status = 'completed' AND id = ANY($1::uuid[])",
            ids,
        )
        == 5
    )
    assert (
        local_env["EDU_WORKER_DATABASE_URL"].split("@")[0].split(":")[-1] not in output.decode()
    ), "the worker never prints its database password"

    # pointed at a login that is not a worker login, it refuses to start
    wrong = {**os.environ, "EDU_WORKER_DATABASE_URL": local_env["EDU_STAFF_DATABASE_URL"]}
    refused = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "edu_worker", "--kinds", "noop", "--exit-when-idle",
        cwd=ROOT, env=wrong, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    message, _ = await asyncio.wait_for(refused.communicate(), timeout=30)
    assert refused.returncode != 0 and b"not a worker login" in message


def test_production_handlers_are_only_the_noop() -> None:
    assert default_handlers() == {"noop": noop}
    assert set(test_handlers()) == {"test_sleep", "test_fail"}
    with pytest.raises(ValueError, match="at least one handler"):
        Worker(None, {})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="concurrency"):
        Worker(None, {"noop": noop}, concurrency=0)  # type: ignore[arg-type]
