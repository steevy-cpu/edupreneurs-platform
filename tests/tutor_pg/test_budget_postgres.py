"""The budget guarantees, checked on a real PostgreSQL with real concurrent transactions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace

import asyncpg
import pytest
from sqlalchemy import text

from edu_api.db.session import Database
from edu_api.tutor.budget import UsageOutcome
from edu_api.tutor.errors import (
    DuplicateRequest,
    GlobalBudgetExhausted,
    LearnerDailyLimitReached,
    LearnerMonthlyLimitReached,
    RequestInProgress,
    TooManyConcurrentRequests,
    TutorBusy,
    TutorError,
    TutorPaused,
)
from edu_api.tutor.pg_store import PostgresUsageStore

A = uuid.UUID("d0000000-0000-4000-8000-00000000000a")
B = uuid.UUID("d0000000-0000-4000-8000-00000000000b")
STAFF = uuid.UUID("e0000000-0000-4000-8000-000000000001")


def spent(amount: int, *, counts: bool = True, outcome: str = "answered") -> UsageOutcome:
    return UsageOutcome(
        spent_micro=amount,
        input_tokens=120,
        output_tokens=60,
        attempts=1,
        outcome=outcome,
        counts_as_request=counts,
        provider="mock",
        model="mock/jude-deterministic-v1",
        price_version="synthetic-2026-11",
        prompt_version="jude-tutor.v1",
        lesson_revision_id=uuid.UUID("c1000000-0000-4000-8000-0000000000f1"),
    )


async def global_totals(owner: asyncpg.Pool) -> tuple[int, int]:
    row = await owner.fetchrow(
        "SELECT COALESCE(sum(spent_micro), 0) AS spent, COALESCE(sum(reserved_micro), 0) AS held "
        "FROM tutor.budget_counters WHERE scope = 'global'"
    )
    return int(row["spent"]), int(row["held"])


async def test_reserve_settle_and_usage_round_trip(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    reservation = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    assert reservation.reserved_micro == 400
    usage = await store.learner_usage(A)
    assert (usage.day_requests, usage.day_micro, usage.daily_requests_limit) == (1, 400, 5)
    await store.settle(reservation, spent(120))
    usage = await store.learner_usage(A)
    assert (usage.day_requests, usage.day_micro, usage.month_micro) == (1, 120, 120)
    assert await global_totals(owner) == (120, 0)
    row = await owner.fetchrow("SELECT * FROM tutor.usage_requests")
    assert (row["status"], row["spent_micro"], row["outcome"], row["attempts"]) == (
        "settled",
        120,
        "answered",
        1,
    )
    assert row["prompt_version"] == "jude-tutor.v1" and row["finished_at"] is not None


async def test_settlement_is_idempotent(store: PostgresUsageStore, owner: asyncpg.Pool) -> None:
    reservation = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    await store.settle(reservation, spent(120))
    await store.settle(reservation, spent(999))
    await store.release(reservation, outcome="late")
    assert await global_totals(owner) == (120, 0)
    assert (await store.learner_usage(A)).day_requests == 1


async def test_duplicate_keys_are_refused_and_charged_once(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    key = uuid.uuid4()
    reservation = await store.reserve(learner_id=A, request_key=key, estimate_micro=400)
    with pytest.raises(RequestInProgress):
        await store.reserve(learner_id=A, request_key=key, estimate_micro=400)
    await store.settle(reservation, spent(100))
    with pytest.raises(DuplicateRequest):
        await store.reserve(learner_id=A, request_key=key, estimate_micro=400)
    assert await owner.fetchval("SELECT count(*) FROM tutor.usage_requests") == 1
    assert await global_totals(owner) == (100, 0)
    # The same key from another learner is a different request.
    await store.reserve(learner_id=B, request_key=key, estimate_micro=10)


async def test_released_request_costs_nothing_and_may_retry_with_the_same_key(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    key = uuid.uuid4()
    reservation = await store.reserve(learner_id=A, request_key=key, estimate_micro=400)
    await store.release(reservation, outcome="tutor_provider_unavailable")
    usage = await store.learner_usage(A)
    assert (usage.day_requests, usage.day_micro) == (0, 0)
    again = await store.reserve(learner_id=A, request_key=key, estimate_micro=300)
    assert again.id == reservation.id and again.reserved_micro == 300
    assert await global_totals(owner) == (0, 300)


async def test_each_limit_refuses_with_its_own_error(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    with pytest.raises(LearnerDailyLimitReached):
        await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=1001)
    await owner.execute("UPDATE tutor.policy SET learner_daily_micro = 100000")
    with pytest.raises(LearnerMonthlyLimitReached):
        await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=3001)
    await owner.execute("UPDATE tutor.policy SET learner_monthly_micro = 100000")
    with pytest.raises(GlobalBudgetExhausted):
        await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=10001)

    await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=1)
    await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=1)
    with pytest.raises(TooManyConcurrentRequests):
        await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=1)
    await owner.execute("UPDATE tutor.policy SET max_concurrent_global = 2")
    with pytest.raises(TutorBusy):
        await store.reserve(learner_id=B, request_key=uuid.uuid4(), estimate_micro=1)
    # Refusals hold nothing.
    assert await global_totals(owner) == (0, 2)


async def test_daily_number_of_requests_is_enforced(store: PostgresUsageStore) -> None:
    for _ in range(5):
        reservation = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=10)
        await store.settle(reservation, spent(10))
    with pytest.raises(LearnerDailyLimitReached):
        await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=10)
    # A failed request costs money but gives the question back.
    assert (await store.learner_usage(B)).day_requests == 0
    reservation = await store.reserve(learner_id=B, request_key=uuid.uuid4(), estimate_micro=10)
    await store.settle(reservation, spent(7, counts=False, outcome="tutor_provider_timeout"))
    usage = await store.learner_usage(B)
    assert (usage.day_requests, usage.day_micro) == (0, 7)


async def test_kill_switch_refuses_and_is_audited(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    assert await store.is_paused() is False
    await owner.execute("SELECT tutor.set_paused(true, $1)", STAFF)
    assert await store.is_paused() is True
    with pytest.raises(TutorPaused):
        await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=1)
    assert await owner.fetchval("SELECT count(*) FROM tutor.usage_requests") == 0
    audit = await owner.fetchrow("SELECT actor_id, action, details FROM tutor.admin_audit")
    assert (audit["actor_id"], audit["action"]) == (STAFF, "tutor.kill_switch.set")


async def test_schema_starts_paused_with_zero_limits(tutor_database_url: str) -> None:
    """Applying the proposal must enable nothing by itself."""
    fresh = f"jude_tutor_fresh_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(tutor_database_url)
    try:
        await admin.execute(f'CREATE DATABASE "{fresh}"')
        from .conftest import PRELUDE, PROPOSAL, _with_database

        conn = await asyncpg.connect(_with_database(tutor_database_url, fresh))
        try:
            await conn.execute(PRELUDE.read_text(encoding="utf-8"))
            await conn.execute(PROPOSAL.read_text(encoding="utf-8"))
            row = await conn.fetchrow("SELECT * FROM tutor.policy")
            assert row["paused"] is True
            assert row["global_monthly_micro"] == 0 and row["learner_daily_requests"] == 0
        finally:
            await conn.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{fresh}" WITH (FORCE)')
        await admin.close()


# --- concurrency: the reason this lives in the database ---------------------------------------
async def test_concurrent_reservations_never_exceed_the_global_ceiling(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    """60 learners reserve at the same moment; the ceiling fits exactly 11."""
    each, ceiling, learners = 900, 10_000, 60

    async def one(index: int) -> str:
        try:
            await store.reserve(
                learner_id=uuid.UUID(int=index + 1), request_key=uuid.uuid4(), estimate_micro=each
            )
        except TutorError as exc:
            return exc.code
        return "reserved"

    results = await asyncio.gather(*(one(i) for i in range(learners)))
    assert results.count("reserved") == ceiling // each == 11
    assert results.count("tutor_budget_exhausted") == learners - 11
    spent_total, held = await global_totals(owner)
    assert spent_total == 0 and held == 11 * each <= ceiling
    assert await owner.fetchval("SELECT count(*) FROM tutor.usage_requests") == 11


async def test_concurrent_reserve_and_settle_keep_the_books_exact(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    """Reserve and settle interleaved across many learners: counters equal the ledger."""
    await owner.execute(
        "UPDATE tutor.policy SET global_monthly_micro = 6000, learner_daily_micro = 100000, "
        "learner_monthly_micro = 100000, learner_daily_requests = 1000"
    )

    async def worker(index: int) -> int:
        learner = uuid.UUID(int=1000 + index % 15)  # 15 learners, several requests each
        try:
            reservation = await store.reserve(
                learner_id=learner, request_key=uuid.uuid4(), estimate_micro=500
            )
        except TutorError:
            return 0
        await asyncio.sleep(0)
        await store.settle(reservation, spent(173))
        return 173

    charged = sum(await asyncio.gather(*(worker(i) for i in range(120))))
    spent_total, held = await global_totals(owner)
    assert held == 0
    assert spent_total == charged <= 6000
    ledger = await owner.fetchval(
        "SELECT COALESCE(sum(spent_micro), 0) FROM tutor.usage_requests WHERE status = 'settled'"
    )
    assert ledger == charged
    # Every counter row agrees with the ledger rows it summarises.
    mismatches = await owner.fetchval(
        """
        SELECT count(*) FROM tutor.budget_counters c
        WHERE c.scope = 'learner' AND c.period_kind = 'month'
          AND c.spent_micro <> (SELECT COALESCE(sum(u.spent_micro), 0) FROM tutor.usage_requests u
                                WHERE u.learner_id = c.learner_id AND u.usage_month = c.period_start)
        """
    )
    assert mismatches == 0
    assert (
        await owner.fetchval("SELECT count(*) FROM tutor.budget_counters WHERE reserved_micro <> 0")
        == 0
    )


async def test_the_same_request_sent_many_times_at_once_is_admitted_once(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    key = uuid.uuid4()

    async def one() -> str:
        try:
            await store.reserve(learner_id=A, request_key=key, estimate_micro=100)
        except TutorError as exc:
            return exc.code
        return "reserved"

    results = await asyncio.gather(*(one() for _ in range(25)))
    assert results.count("reserved") == 1
    assert results.count("tutor_request_in_progress") == 24
    assert await global_totals(owner) == (0, 100)


async def test_per_learner_concurrency_holds_under_a_burst(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    async def one() -> str:
        try:
            await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=10)
        except TutorError as exc:
            return exc.code
        return "reserved"

    results = await asyncio.gather(*(one() for _ in range(20)))
    assert results.count("reserved") == 2  # max_concurrent_per_learner
    assert results.count("tutor_too_many_requests") == 18


# --- isolation and privilege -------------------------------------------------------------------
async def test_one_learner_cannot_settle_or_release_anothers_reservation(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    reservation = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    forged = replace(reservation, learner_id=B)
    await store.settle(forged, spent(0))
    await store.release(forged, outcome="forged")
    assert await owner.fetchval("SELECT status FROM tutor.usage_requests") == "reserved"
    assert await global_totals(owner) == (0, 400)
    assert (await store.learner_usage(B)).day_micro == 0


async def test_the_api_role_cannot_read_or_write_any_tutor_table(database: Database) -> None:
    for statement in (
        "SELECT * FROM tutor.usage_requests",
        "SELECT * FROM tutor.budget_counters",
        "SELECT * FROM tutor.policy",
        "UPDATE tutor.policy SET paused = false",
        "INSERT INTO tutor.budget_counters (scope, period_kind, period_start) "
        "VALUES ('global', 'month', '2026-01-01')",
        "DELETE FROM tutor.admin_audit",
        "SELECT tutor.set_paused(false, NULL)",
        "SELECT tutor.erase_learner(gen_random_uuid(), NULL)",
        "SELECT tutor.expire_stale(10)",
        "SELECT tutor._lock_counter('global', gen_random_uuid(), 'month', '2026-01-01')",
    ):
        with pytest.raises(Exception, match="permission denied"):
            async with database.transaction(A) as conn:
                await conn.execute(text(statement))


async def test_budget_functions_need_an_authenticated_learner(database: Database) -> None:
    with pytest.raises(Exception, match="no authenticated learner"):
        async with database.transaction(None) as conn:
            await conn.execute(text("SELECT * FROM tutor.reserve(gen_random_uuid(), 1)"))


async def test_budget_functions_refuse_a_weaker_isolation_guarantee(database: Database) -> None:
    with pytest.raises(Exception, match="READ COMMITTED"):
        async with database.engine.connect() as raw:
            conn = await raw.execution_options(isolation_level="REPEATABLE READ")
            async with conn.begin():
                await conn.execute(
                    text("SELECT set_config('edu.actor_id', :a, true)"), {"a": str(A)}
                )
                await conn.execute(text("SELECT * FROM tutor.reserve(gen_random_uuid(), 1)"))


# --- expiry, erasure, retention, schema shape -----------------------------------------------------
async def test_unsettled_reservations_expire_and_are_charged_in_full(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    reservation = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    assert await owner.fetchval("SELECT tutor.expire_stale()") == 0
    await owner.execute("UPDATE tutor.usage_requests SET expires_at = now() - interval '1 second'")
    assert await owner.fetchval("SELECT tutor.expire_stale()") == 1
    row = await owner.fetchrow("SELECT status, spent_micro, outcome FROM tutor.usage_requests")
    assert tuple(row) == ("expired", 400, "expired_unsettled")
    assert await global_totals(owner) == (400, 0)
    await store.settle(reservation, spent(1))  # too late: history is not rewritten
    assert await global_totals(owner) == (400, 0)


async def test_a_learners_own_stale_reservation_is_charged_on_their_next_request(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute("UPDATE tutor.policy SET max_concurrent_per_learner = 1")
    key = uuid.uuid4()
    await store.reserve(learner_id=A, request_key=key, estimate_micro=400)
    await owner.execute("UPDATE tutor.usage_requests SET expires_at = now() - interval '1 second'")
    await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=100)  # slot is free
    assert await global_totals(owner) == (400, 100)
    with pytest.raises(DuplicateRequest):
        await store.reserve(learner_id=A, request_key=key, estimate_micro=100)


async def test_erasing_a_learner_removes_their_rows_and_keeps_the_totals(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    done = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    await store.settle(done, spent(250))
    await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=100)
    other = await store.reserve(learner_id=B, request_key=uuid.uuid4(), estimate_micro=50)
    await store.settle(other, spent(50))

    assert await owner.fetchval("SELECT tutor.erase_learner($1, $2)", A, STAFF) == 2
    assert (
        await owner.fetchval("SELECT count(*) FROM tutor.usage_requests WHERE learner_id = $1", A)
        == 0
    )
    assert (
        await owner.fetchval("SELECT count(*) FROM tutor.budget_counters WHERE learner_id = $1", A)
        == 0
    )
    assert await global_totals(owner) == (250 + 100 + 50, 0)
    assert (await store.learner_usage(B)).day_micro == 50
    audit = await owner.fetchval("SELECT details::text FROM tutor.admin_audit")
    assert str(A) not in audit


async def test_retention_purge_and_append_only_prices(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    old = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=10)
    await store.settle(old, spent(10))
    await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=10)
    await owner.execute("UPDATE tutor.usage_requests SET created_at = now() - interval '40 days'")
    recent = await store.reserve(learner_id=B, request_key=uuid.uuid4(), estimate_micro=10)
    await store.settle(recent, spent(10))
    purged = await owner.fetchval(
        "SELECT tutor.purge_older_than(now() - interval '30 days', $1)", STAFF
    )
    assert purged == 1  # the old finished row; the old in-flight row and the recent row stay
    assert await owner.fetchval("SELECT count(*) FROM tutor.usage_requests") == 2

    await owner.execute(
        "INSERT INTO tutor.price_versions (price_version, model, input_micro_per_mtok, "
        "output_micro_per_mtok) VALUES ('synthetic-2026-11', 'mock/jude', 500000, 1500000) "
        "ON CONFLICT DO NOTHING"
    )
    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await owner.execute("UPDATE tutor.price_versions SET input_micro_per_mtok = 1")
    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await owner.execute("DELETE FROM tutor.price_versions")


async def test_no_column_can_hold_conversation_text(owner: asyncpg.Pool) -> None:
    columns = await owner.fetch(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'tutor' ORDER BY 1, 2"
    )
    names = {(c["table_name"], c["column_name"]) for c in columns}
    assert {t for t, _ in names} == {
        "admin_audit",
        "budget_counters",
        "policy",
        "price_versions",
        "usage_requests",
    }
    for table, column in names:
        for forbidden in ("message", "question", "answer", "transcript", "content", "body"):
            assert forbidden not in column, (table, column)
    # Every text column of the ledger is constrained to a short code shape.
    free_text = [
        c["column_name"]
        for c in columns
        if c["table_name"] == "usage_requests" and c["data_type"] == "text"
    ]
    assert sorted(free_text) == [
        "model",
        "outcome",
        "price_version",
        "prompt_version",
        "provider",
        "status",
    ]
    for value in ("Pourquoi on soustrait 5 des deux côtés ?", "x" * 61, "Has Spaces"):
        with pytest.raises(asyncpg.CheckViolationError):
            await owner.execute(
                "INSERT INTO tutor.usage_requests (learner_id, request_key, status, usage_day, "
                "usage_month, reserved_micro, expires_at, outcome) VALUES "
                "(gen_random_uuid(), gen_random_uuid(), 'settled', current_date, current_date, "
                "0, now(), $1)",
                value,
            )
