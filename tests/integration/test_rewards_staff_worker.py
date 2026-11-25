# ruff: noqa: F811
"""Worker reconciliation and audited admin corrections through the REAL login roles.

``edu_worker_login`` and ``edu_staff_login`` are the database logins a worker /
the staff side of the API would use. The pgTAP file 195 covers the rules in
detail; these tests prove them over real connections, including the audit
attribution that only a real login can show (``actor_kind``).
"""

from __future__ import annotations

import json
import uuid

import asyncpg
import httpx
import pytest

from tests.helpers import (
    SEED_QUESTIONS_FR,
    SEED_REV_FR,
    STUDENT_A,
    STUDENT_B,
    answer_op,
    bearer,
    completed_op,
)
from tests.rewards_fixtures import (  # noqa: F401  (fixtures are used by name)
    assert_balance_matches_ledger,
    clean_rewards,
    ledger_total,
    off,
    on,
    push,
    rewards_app,
    rewards_off_app,
    summary,
    unexamined,
)
from tests.staff_fixtures import make_staff, staff_url, worker_url  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_rewards")]

Q1, Q1_CORRECT = SEED_QUESTIONS_FR[0]
ACTOR = "SELECT set_config('edu.actor_id', $1, true)"


async def test_worker_login_heals_unexamined_operations_and_nothing_else(
    off: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    await push(off, tokens["student_a"], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)])
    await push(off, tokens["student_b"], [answer_op(Q1, Q1_CORRECT)])
    assert await unexamined(admin, STUDENT_A) == 2 and await unexamined(admin, STUDENT_B) == 1

    worker = await asyncpg.connect(worker_url(local_env))
    try:
        assert await worker.fetchval("SELECT session_user::text") == "edu_worker_login"
        report = json.loads(await worker.fetchval("SELECT rewards.reconcile_batch(50, 200)"))
        assert (report["examined"], report["gold"]) == (3, 40)
        again = json.loads(await worker.fetchval("SELECT rewards.reconcile_batch(50, 200)"))
        assert (again["learners"], again["examined"], again["gold"]) == (0, 0, 0)

        for statement in (
            "SELECT count(*) FROM rewards.ledger",
            "SELECT count(*) FROM rewards.balances",
            "UPDATE rewards.balances SET balance = 1000",
            "SELECT rewards.rebuild_balance('a0000000-0000-4000-8000-000000000001')",
            "SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000001')",
            "SELECT rewards.reverse_entry(gen_random_uuid(), 'test_correction')",
            "SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 50, 'support_goodwill', gen_random_uuid())",
            "SELECT rewards.award_for_operation(gen_random_uuid())",
            "SELECT count(*) FROM app.sync_receipts",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await worker.execute(statement)
    finally:
        await worker.close()

    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35
    assert await assert_balance_matches_ledger(admin, STUDENT_B) == 5
    assert await unexamined(admin, STUDENT_A) == 0 and await unexamined(admin, STUDENT_B) == 0


async def test_admin_adjustment_and_reversal_are_audited_and_visible_to_the_learner(
    on: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    local_env: dict[str, str],
    make_staff,  # type: ignore[no-untyped-def]
) -> None:
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)])
    boss = await make_staff("admin")
    editor = await make_staff("editor")
    lesson_row = await admin.fetchval(
        "SELECT id FROM rewards.ledger WHERE learner_id = $1 AND source_kind = 'lesson_first_completed'",
        STUDENT_A,
    )
    adjustment_id = uuid.uuid4()
    adjust = "SELECT rewards.staff_adjust($1, $2, $3, $4)"

    staff = await asyncpg.connect(staff_url(local_env))
    try:
        assert await staff.fetchval("SELECT session_user::text") == "edu_staff_login"
        # Not an admin (an editor, a learner, nobody): refused, nothing written.
        for actor in (str(editor.user_id), str(STUDENT_A), ""):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with staff.transaction():
                    await staff.execute(ACTOR, actor)
                    await staff.fetchval(adjust, STUDENT_A, 50, "support_goodwill", uuid.uuid4())
        # An admin, but with free text instead of a reason code, or too much Gold.
        for amount, reason in ((50, "the learner asked nicely"), (500, "support_goodwill")):
            with pytest.raises(asyncpg.InvalidParameterValueError):
                async with staff.transaction():
                    await staff.execute(ACTOR, str(boss.user_id))
                    await staff.fetchval(adjust, STUDENT_A, amount, reason, uuid.uuid4())
        assert await ledger_total(admin, STUDENT_A) == (3, 35)

        async with staff.transaction():
            await staff.execute(ACTOR, str(boss.user_id))
            first = json.loads(
                await staff.fetchval(adjust, STUDENT_A, 50, "support_goodwill", adjustment_id)
            )
        async with staff.transaction():  # the same request retried
            await staff.execute(ACTOR, str(boss.user_id))
            retry = json.loads(
                await staff.fetchval(adjust, STUDENT_A, 50, "support_goodwill", adjustment_id)
            )
        assert (first["balance"], first["replayed"]) == (85, False)
        assert (retry["balance"], retry["replayed"], retry["ledger_id"]) == (
            85,
            True,
            first["ledger_id"],
        )
        async with staff.transaction():
            await staff.execute(ACTOR, str(boss.user_id))
            reversal = json.loads(
                await staff.fetchval(
                    "SELECT rewards.staff_reverse_entry($1, 'content_error')", lesson_row
                )
            )
        assert (reversal["amount"], reversal["balance"]) == (-20, 65)
        # The staff login itself still cannot read or write the tables.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await staff.execute("SELECT count(*) FROM rewards.ledger")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await staff.execute("SELECT rewards.reconcile_batch(10, 10)")
    finally:
        await staff.close()

    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 65
    events = await admin.fetch(
        "SELECT action, actor_id, actor_kind, outcome, target_kind, target_id, details "
        "FROM app.audit_events WHERE action LIKE 'rewards_ledger.%' AND actor_id = $1 ORDER BY created_at",
        boss.user_id,
    )
    assert [(e["action"], e["actor_kind"], e["outcome"]) for e in events] == [
        ("rewards_ledger.adjust", "staff", "allowed"),
        ("rewards_ledger.reverse", "staff", "allowed"),
    ], "one event per accepted action; the retry and the refusals wrote none"
    adjust_details = json.loads(events[0]["details"])
    assert adjust_details == {
        "learner_id": str(STUDENT_A),
        "adjustment_id": str(adjustment_id),
        "amount": 50,
        "reason_code": "support_goodwill",
    }
    assert str(events[0]["target_id"]) == first["ledger_id"]
    assert json.loads(events[1]["details"])["reversed_ledger_id"] == str(lesson_row)

    # The learner sees both corrections in their own ledger, without the admin's identity.
    page = (await on.get("/v1/rewards/ledger", headers=bearer(tokens["student_a"]))).json()
    assert [(e["kind"], e["source"], e["amount"]) for e in page["entries"][:2]] == [
        ("reversal", "reversal", -20),
        ("adjustment", "adjustment", 50),
    ]
    assert page["balance"] == 65
    assert str(boss.user_id) not in json.dumps(page)
    assert "reason" not in json.dumps(page) and "actor" not in json.dumps(page)
    body = await summary(on, tokens["student_a"])
    assert (body["balance"], body["lifetime_earned"]) == (65, 85)
    assert await ledger_total(admin, STUDENT_B) == (0, 0)
