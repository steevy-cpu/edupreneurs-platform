"""Independent-review fixes (final verification 2026-11-25): LB-1 minimum cohort size and
snapshot-only rank/size, LB-2 refresh vs withdraw/erase (two real connections), LB-3 timing
at 5 000 members, LB-4 cohort flag."""

# ruff: noqa: F811 — fixtures are imported from tests/leaderboard_fixtures.py and requested by
# parameter name, which pyflakes reads as a redefinition.

from __future__ import annotations

import asyncio
import statistics
import time
import uuid

import asyncpg
import httpx
import pytest

from tests.helpers import SEED_QUESTIONS_FR, STUDENT_A, STUDENT_B, answer_op
from tests.leaderboard_fixtures import (  # noqa: F401  (fixtures are used by name)
    clean_leaderboard,
    enroll,
    lb,
    lb_only,
    leaderboard_app,
    leaderboard_only_app,
    make_cohort,
    me,
    push,
    refresh,
    set_min_cohort,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_leaderboard")]

Q1, Q1_OK = SEED_QUESTIONS_FR[0]
Q2, Q2_OK = SEED_QUESTIONS_FR[1]
CLOSED_WEEK = "2026-03-02"


async def _two_members(
    lb: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> uuid.UUID:
    assert (await push(lb, tokens["student_a"], [answer_op(Q1, Q1_OK)])).status_code == 200
    assert (
        await push(lb, tokens["student_b"], [answer_op(Q1, Q1_OK), answer_op(Q2, Q2_OK)])
    ).status_code == 200
    cohort = await make_cohort(admin)
    await enroll(admin, cohort, STUDENT_A)
    await enroll(admin, cohort, STUDENT_B)
    return cohort


# ------------------------------------------------------------------ LB-4: cohort flag
async def test_cohort_block_needs_the_cohorts_flag(
    lb: httpx.AsyncClient,
    lb_only: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    await set_min_cohort(admin, 1)
    cohort = await _two_members(lb, admin, tokens)
    await refresh(admin, cohort, "all")
    b = tokens["student_b"]
    # Both flags on: the cohort block (own pseudonym, rank, size).
    both = await me(lb, b, "all")
    assert both["cohort"]["rank"] == 1 and both["cohort"]["size"] == 2
    # Only EDU_LEADERBOARD_ENABLED: own Gold, and no cohort block at all.
    only = await me(lb_only, b, "all")
    assert only["gold"] == both["gold"] == 10
    assert only["cohort"] is None
    assert "pseudonym" not in str(only) and str(cohort) not in str(only)


# ------------------------------------------------------------------ LB-1 through the API
async def test_a_cohort_below_the_default_floor_shows_no_rank_and_no_size(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    cohort = await _two_members(lb, admin, tokens)
    assert await admin.fetchval("SELECT min_cohort_size FROM leaderboard.config") == 5
    await refresh(admin, cohort, "all")
    seen = await me(lb, tokens["student_b"], "all")
    assert seen["gold"] == 10, "the caller keeps the own Gold"
    assert seen["cohort"]["pseudonym"]
    assert (seen["cohort"]["rank"], seen["cohort"]["size"]) == (None, None)
    assert await admin.fetchval("SELECT count(*) FROM leaderboard.snapshots") == 0
    # Boundary: exactly K members is enough.
    await set_min_cohort(admin, 2)
    await refresh(admin, cohort, "all")
    seen = await me(lb, tokens["student_b"], "all")
    assert (seen["cohort"]["rank"], seen["cohort"]["size"]) == (1, 2)
    await set_min_cohort(admin, 3)
    assert (await me(lb, tokens["student_b"], "all"))["cohort"]["size"] is None, "fails closed"


async def test_another_members_withdrawal_is_invisible_until_the_refresh(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    await set_min_cohort(admin, 2)
    cohort = await _two_members(lb, admin, tokens)
    await refresh(admin, cohort, "all")
    a, b = tokens["student_a"], tokens["student_b"]
    before = await me(lb, a, "all")
    assert (before["cohort"]["rank"], before["cohort"]["size"]) == (2, 2)
    assert await admin.fetchval("SELECT leaderboard.withdraw($1, $2)", cohort, STUDENT_B) is True
    # B's own data disappears at once ...
    gone = await me(lb, b, "all")
    assert (gone["gold"], gone["cohort"]) == (10, None)
    # ... and A's answer is byte-for-byte what it was.
    assert await me(lb, a, "all") == before
    await refresh(admin, cohort, "all")
    after = (await me(lb, a, "all"))["cohort"]
    assert (after["rank"], after["size"]) == (None, None), "1 member left: below the floor"


async def test_a_closed_week_returns_the_frozen_gold(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """LB-7. Needs a ledger row in a closed week: written as the owner, triggers off."""
    await set_min_cohort(admin, 1)
    cohort = await make_cohort(admin)
    await enroll(admin, cohort, STUDENT_A)

    async def award(amount: int, code: str) -> None:
        async with admin.acquire() as conn, conn.transaction():
            await conn.execute("SET LOCAL session_replication_role = replica")
            await conn.execute(
                "INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, "
                "rule_version, source_kind, source_op_id, achievement_code, accepted_at, "
                "accepted_day) VALUES ($1, 'award', $2, 'achievement_first_lesson', 1, "
                "'achievement', gen_random_uuid(), $3, timestamptz '2026-03-04 15:00+00', "
                "date '2026-03-04')",
                STUDENT_A,
                amount,
                code,
            )

    await award(7, "lbfix_first")
    await refresh(admin, cohort, CLOSED_WEEK)
    await award(50, "lbfix_late")
    seen = await me(lb, tokens["student_a"], CLOSED_WEEK)
    assert seen["closed"] is True and seen["cohort"]["frozen"] is True
    assert seen["gold"] == seen["cohort"]["snapshot_gold"] == 7, "frozen figure, not 57"
    assert (await me(lb, tokens["student_a"], "all"))["gold"] == 57, "open period: live"


# ------------------------------------------------------------------ LB-2: two real connections
async def _blocked_until_commit(
    admin: asyncpg.Pool, cohort: uuid.UUID, period: str, writer_sql: str, *args: object
) -> tuple[object, int]:
    """Refresh in connection 1 (uncommitted), run ``writer_sql`` in connection 2; it must WAIT.
    Returns (writer result, snapshot rows left for STUDENT_A afterwards)."""
    async with admin.acquire() as conn1, admin.acquire() as conn2:
        tx = conn1.transaction()
        await tx.start()
        await conn1.fetchval("SELECT leaderboard.refresh_snapshot($1, $2)", cohort, period)
        writer = asyncio.create_task(conn2.fetchval(writer_sql, *args))
        await asyncio.sleep(0.7)
        assert not writer.done(), "the withdrawal/erasure must wait for the in-flight refresh"
        await tx.commit()
        result = await asyncio.wait_for(writer, 10)
    left = await admin.fetchval(
        "SELECT count(*) FROM leaderboard.snapshots WHERE learner_id = $1", STUDENT_A
    )
    return result, left


@pytest.mark.parametrize("period", ["all", CLOSED_WEEK])
async def test_a_withdrawal_during_a_refresh_is_never_resurrected(
    admin: asyncpg.Pool, period: str
) -> None:
    await set_min_cohort(admin, 1)
    cohort = await make_cohort(admin)
    await enroll(admin, cohort, STUDENT_A)
    await enroll(admin, cohort, STUDENT_B)
    changed, left = await _blocked_until_commit(
        admin, cohort, period, "SELECT leaderboard.withdraw($1, $2)", cohort, STUDENT_A
    )
    assert changed is True
    assert left == 0, "no snapshot row of the withdrawn learner survives (frozen week included)"
    # B is unaffected; a later refresh of the open period does not bring A back either.
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM leaderboard.snapshots WHERE learner_id = $1", STUDENT_B
        )
        == 1
    )
    if period == "all":
        await refresh(admin, cohort, "all")
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM leaderboard.snapshots WHERE learner_id = $1", STUDENT_A
            )
            == 0
        )


async def test_an_erasure_during_a_refresh_waits_instead_of_failing(
    admin: asyncpg.Pool,
) -> None:
    await set_min_cohort(admin, 1)
    cohort = await make_cohort(admin)
    await enroll(admin, cohort, STUDENT_A)
    await enroll(admin, cohort, STUDENT_B)
    result, left = await _blocked_until_commit(
        admin, cohort, "all", "SELECT leaderboard.erase_learner($1)::text", STUDENT_A
    )
    assert '"memberships": 1' in str(result) and '"snapshots": 1' in str(result)
    assert left == 0


# ------------------------------------------------------------------ LB-3: 5 000 members
async def test_my_standing_and_refresh_at_5000_members(
    admin: asyncpg.Pool, capsys: pytest.CaptureFixture[str]
) -> None:
    """Synthetic cohort of 5 000, 4 ledger rows each, all written and rolled back in one
    transaction. The measured times are printed (``pytest -s``) and recorded in the lane doc."""
    async with admin.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute("GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE")
            await conn.execute("SET LOCAL session_replication_role = replica")
            await conn.execute(
                """
                CREATE TEMP TABLE lb_ids AS
                SELECT n, ('3d000000-0000-4000-8000-' || lpad(to_hex(n), 12, '0'))::uuid AS id
                FROM generate_series(1, 5000) n;
                INSERT INTO auth.users (instance_id, id, aud, role, email)
                SELECT '00000000-0000-0000-0000-000000000000', id, 'authenticated',
                       'authenticated', 't3d.' || n || '@edupreneur.test' FROM lb_ids;
                INSERT INTO app.learner_profiles (user_id) SELECT id FROM lb_ids;
                INSERT INTO leaderboard.cohorts (id, kind, code)
                VALUES ('3e000000-0000-4000-8000-000000000001', 'school', 'synthetic-big');
                INSERT INTO leaderboard.memberships
                    (cohort_id, learner_id, opted_in_at, pseudonym_id, pseudonym_suffix)
                SELECT '3e000000-0000-4000-8000-000000000001', id, now(),
                       ((n - 1) % 576 + 1)::smallint, ((n - 1) / 576)::smallint FROM lb_ids;
                INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code,
                    rule_version, source_kind, source_op_id, achievement_code, accepted_at,
                    accepted_day)
                SELECT i.id, 'award', 1 + (i.n * k) % 40, 'achievement_first_lesson', 1,
                       'achievement', gen_random_uuid(), 'lbbig_' || k, now(),
                       rewards.haiti_day(now())
                FROM lb_ids i CROSS JOIN generate_series(1, 4) k;
                ANALYZE rewards.ledger; ANALYZE leaderboard.memberships;
                """
            )
            started = time.perf_counter()
            result = await conn.fetchval(
                "SELECT leaderboard.refresh_snapshot('3e000000-0000-4000-8000-000000000001', 'all')"
            )
            refresh_s = time.perf_counter() - started
            assert '"members": 5000' in str(result)
            await conn.execute("ANALYZE leaderboard.snapshots")

            actor = await conn.fetchval("SELECT id FROM lb_ids WHERE n = 2500")
            timings: list[float] = []
            answer = None
            for _ in range(7):
                await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(actor))
                await conn.execute("SET LOCAL ROLE edu_api")
                started = time.perf_counter()
                answer = await conn.fetchval("SELECT leaderboard.my_standing('all')")
                timings.append(time.perf_counter() - started)
                await conn.execute("RESET ROLE")
            assert answer is not None and '"size": 5000' in answer
            median_ms = statistics.median(timings) * 1000
            worst_ms = max(timings) * 1000
            with capsys.disabled():
                print(
                    f"\n[LB-3] 5000 members: my_standing median {median_ms:.1f} ms, "
                    f"worst {worst_ms:.1f} ms; refresh_snapshot {refresh_s * 1000:.0f} ms"
                )
            # Measured ~1 ms (constant work); the pre-fix read, which re-ranked every visible row,
            # measured 77-105 ms on the same data. 30 ms keeps ~25x headroom and still fails
            # a return to O(cohort) work (the review measured 3 s on a colder, larger data set).
            assert worst_ms < 30, f"my_standing took {worst_ms:.0f} ms at 5000 members"
            assert refresh_s < 5, f"refresh took {refresh_s:.1f} s at 5000 members"
        finally:
            await tx.rollback()
