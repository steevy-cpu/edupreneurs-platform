"""Final verification QA5-R1 / QA5-R2 regression tests for the rewards hook.

R1: the reward step runs inside the learner's push transaction (sync row lock
held), so ANY blocking inside it must cost a few hundred ms at most, once per
push, and the caller's own timeouts must be back afterwards.
R2: a rule switched on while a push was examining the (then off) rule must not
leave a permanent ``no_active_rule`` decision behind.
"""

# ruff: noqa: F811 — fixtures are imported from tests/rewards_fixtures.py and requested by
# parameter name, which pyflakes reads as a redefinition.

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from edu_api.rewards.hook import batch_award_hook
from tests.conftest import publish_new_lesson
from tests.helpers import SEED_QUESTIONS_FR, STUDENT_A, answer_op
from tests.rewards_fixtures import (  # noqa: F401  (fixtures are used by name)
    assert_balance_matches_ledger,
    clean_rewards,
    ledger_total,
    off,
    on,
    push,
    rewards_app,
    rewards_off_app,
    unexamined,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_rewards")]

Q1, Q1_CORRECT = SEED_QUESTIONS_FR[0]
QUESTION_GOLD = 5


@pytest.fixture
async def other(local_env: dict[str, str]) -> AsyncIterator[asyncpg.Connection]:
    """A second real connection (database owner) used to hold locks."""
    conn = await asyncpg.connect(local_env["LOCAL_ADMIN_DATABASE_URL"])
    yield conn
    await conn.close()


async def _ten_op_push_under_lock(
    on: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    other: asyncpg.Connection,
    lock_sql: str,
    *lock_args: uuid.UUID,
) -> None:
    # A first push creates the learner's balance row, so there is a row to lock.
    first = await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])
    assert first.status_code == 200
    assert await ledger_total(admin, STUDENT_A) == (1, QUESTION_GOLD)

    lesson = await publish_new_lesson(admin, questions=(("mcq", "b"),) * 10)
    ops = [answer_op(q, "b") for q in lesson["question_ids"]]

    transaction = other.transaction()
    await transaction.start()
    try:
        await other.execute(lock_sql, *lock_args)
        started = time.monotonic()
        response = await push(on, tokens["student_a"], ops)
        elapsed = time.monotonic() - started
    finally:
        await transaction.rollback()

    assert response.status_code == 200, response.text
    assert elapsed < 1.5, f"push took {elapsed:.2f}s behind a foreign lock in the reward step"
    body = response.json()
    assert [r["status"] for r in body["results"]] == ["accepted"] * 10
    assert set(body) == {"results", "server_version", "canon_version"}
    # Every learning operation committed; the unpaid ones are healed later, once.
    assert await unexamined(admin, STUDENT_A) >= 1
    assert await ledger_total(admin, STUDENT_A) == (1, QUESTION_GOLD)
    await admin.fetchval("SELECT rewards.reconcile_batch(20, 200)")
    assert await unexamined(admin, STUDENT_A) == 0
    healed = await ledger_total(admin, STUDENT_A)
    answers = await admin.fetchval(
        "SELECT count(*) FROM rewards.ledger WHERE learner_id = $1 "
        "AND source_kind = 'question_first_correct'",
        STUDENT_A,
    )
    assert answers == 11, "each of the 11 correct answers paid exactly once"
    # (achievement bonuses crossed by the 10-correct milestone are part of the total)
    await admin.fetchval("SELECT rewards.reconcile_batch(20, 200)")
    assert await ledger_total(admin, STUDENT_A) == healed, "a second reconcile awards nothing"
    await assert_balance_matches_ledger(admin, STUDENT_A)


async def test_ddl_lock_on_a_rewards_table_cannot_stall_a_push(
    on: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    other: asyncpg.Connection,
) -> None:
    await _ten_op_push_under_lock(
        on, tokens, admin, other, "LOCK TABLE rewards.processed_operations IN ACCESS EXCLUSIVE MODE"
    )


async def test_row_lock_on_the_balance_cannot_stall_a_push(
    on: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    other: asyncpg.Connection,
) -> None:
    await _ten_op_push_under_lock(
        on,
        tokens,
        admin,
        other,
        "SELECT 1 FROM rewards.balances WHERE learner_id = $1 FOR UPDATE",
        STUDENT_A,
    )


_TIMEOUTS = text(
    "SELECT current_setting('lock_timeout') AS lt, current_setting('statement_timeout') AS st"
)


@pytest.mark.parametrize("actor", [STUDENT_A, None], ids=["success", "failure"])
async def test_transaction_timeouts_are_restored_after_the_hook(
    rewards_app: FastAPI, actor: uuid.UUID | None
) -> None:
    """Success path (actor set) and error path (no actor: the SQL function raises)."""
    db = rewards_app.state.db
    hook = batch_award_hook(250, 500)
    async with db.transaction(actor) as conn:
        before = (await conn.execute(_TIMEOUTS)).one()
        await hook(conn, STUDENT_A, uuid.uuid4())
        after = (await conn.execute(_TIMEOUTS)).one()
        assert tuple(after) == tuple(before)
        assert tuple(before) == ("5s", "5s")  # the engine's normal values, not 250ms/500ms


async def test_a_rule_switched_on_during_a_push_is_never_stuck_on_no_active_rule(
    off: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    local_env: dict[str, str],
) -> None:
    """QA5-R2. The operator's switch (not yet committed) and a push that examines the
    still-off rule interleave: the push records its decision and commits around the
    switch's commit. Whatever the order, reconcile must pay the operation afterwards."""
    # Accepted with the flag OFF: no reward step ran, the op awaits its first examination.
    op = answer_op(Q1, Q1_CORRECT)
    assert (await push(off, tokens["student_a"], [op])).status_code == 200
    assert await unexamined(admin, STUDENT_A) == 1

    url = local_env["LOCAL_ADMIN_DATABASE_URL"]
    switcher = await asyncpg.connect(url)
    pusher = await asyncpg.connect(url)
    try:
        await admin.execute(
            "UPDATE rewards.rules SET is_active = false WHERE code = 'question_first_correct'"
        )
        op_id = uuid.UUID(op["op_id"])
        sw = switcher.transaction()
        await sw.start()
        await switcher.execute(
            "SELECT rewards.set_active_rule_version('question_first_correct', 1)"
        )
        # The push examines the operation while the switch is still uncommitted.
        pu = pusher.transaction()
        await pu.start()
        examine = asyncio.ensure_future(
            pusher.fetchval("SELECT rewards.apply_operation($1, $2)", STUDENT_A, op_id)
        )
        await asyncio.wait([examine], timeout=0.7)  # fixed code: waits for the switch here
        await sw.commit()  # the switch commits (and has forgotten what it could see)
        await asyncio.wait_for(examine, 10)
        await pu.commit()  # the push commits just after the switch
    finally:
        await switcher.close()
        await pusher.close()

    try:
        await admin.fetchval("SELECT rewards.reconcile_batch(20, 200)")
        stuck = await admin.fetchval(
            "SELECT count(*) FROM rewards.processed_operations WHERE outcome = 'no_active_rule'"
        )
        assert stuck == 0, "a stale no_active_rule decision survived the rule switch"
        assert await unexamined(admin, STUDENT_A) == 0
        assert await ledger_total(admin, STUDENT_A) == (1, QUESTION_GOLD)
        await assert_balance_matches_ledger(admin, STUDENT_A)
    finally:
        # Leave the rule live whatever happened above (this call also heals stale rows).
        await admin.execute("SELECT rewards.set_active_rule_version('question_first_correct', 1)")
