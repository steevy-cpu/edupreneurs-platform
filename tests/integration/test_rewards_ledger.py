"""Gold ledger integrity through the REAL push path (real Auth tokens, real PostgreSQL).

Every assertion about "what was really awarded" reads the ledger as the
database owner (``admin``), not through the API under test. After every
scenario the invariant ``sum(ledger) == balance`` is checked.
"""

# ruff: noqa: F811 — fixtures are imported from tests/rewards_fixtures.py and requested by
# parameter name, which pyflakes reads as a redefinition.

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from tests.conftest import approve_revision, create_revision, publish_new_lesson, release_pack
from tests.helpers import (
    SEED_LESSON,
    SEED_QUESTIONS_FR,
    SEED_QUESTIONS_HT,
    SEED_REV_FR,
    SEED_REV_HT,
    STUDENT_A,
    STUDENT_B,
    answer_op,
    bearer,
    completed_op,
)
from tests.rewards_fixtures import (  # noqa: F401  (fixtures are used by name)
    assert_balance_matches_ledger,
    clean_rewards,
    ledger_rows,
    ledger_total,
    off,
    on,
    push,
    rewards_app,
    rewards_off_app,
    summary,
    unexamined,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_rewards")]

Q1, Q1_CORRECT = SEED_QUESTIONS_FR[0]
Q2, Q2_CORRECT = SEED_QUESTIONS_FR[1]
Q3, Q3_CORRECT = SEED_QUESTIONS_FR[2]
Q1_HT, Q1_HT_CORRECT = SEED_QUESTIONS_HT[0]

#: Synthetic placeholder amounts seeded by the migration (BLOCKED_BY_OWNER PO-09).
QUESTION_GOLD = 5
LESSON_GOLD = 20
FIRST_LESSON_BONUS = 10
TEN_CORRECT_BONUS = 15

Q1_KEY = f"q:{SEED_LESSON}:addition"
LESSON_KEY = f"l:{SEED_LESSON}"


def keys(rows: list[asyncpg.Record]) -> list[str]:
    return sorted(row["source_key"] for row in rows)


# ------------------------------------------------------------- the basic award
async def test_first_correct_answer_and_first_completion_earn_gold(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    ops = [answer_op(Q1, Q1_CORRECT), answer_op(Q2, "d"), completed_op(SEED_REV_FR)]
    response = await push(on, tokens["student_a"], ops)
    assert response.status_code == 200, response.text
    assert [r["status"] for r in response.json()["results"]] == ["accepted"] * 3

    rows = await ledger_rows(admin, STUDENT_A)
    assert keys(rows) == sorted([Q1_KEY, LESSON_KEY, "a:first_lesson_completed"])
    by_key = {row["source_key"]: row for row in rows}
    assert by_key[Q1_KEY]["amount"] == QUESTION_GOLD
    assert str(by_key[Q1_KEY]["source_op_id"]) == ops[0]["op_id"]
    assert by_key[LESSON_KEY]["amount"] == LESSON_GOLD
    assert str(by_key[LESSON_KEY]["source_op_id"]) == ops[2]["op_id"]
    assert by_key["a:first_lesson_completed"]["amount"] == FIRST_LESSON_BONUS
    assert all(row["entry_kind"] == "award" and row["rule_version"] == 1 for row in rows)
    # The day on every row is the Haiti date of SERVER acceptance.
    server_day = await admin.fetchval("SELECT rewards.haiti_day(now())")
    assert {row["accepted_day"] for row in rows} == {server_day}

    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35
    assert await ledger_total(admin, STUDENT_B) == (0, 0), "nobody else earned anything"
    assert await unexamined(admin, STUDENT_A) == 0


async def test_push_response_is_identical_with_the_flag_on_and_off(
    on: httpx.AsyncClient, off: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """Old apps keep working: the push response has no rewards field at all."""

    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shape(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            return [shape(item) for item in value]
        return type(value).__name__

    def batch() -> list[dict[str, Any]]:
        return [
            answer_op(Q1, Q1_CORRECT),
            answer_op(Q2, "d"),
            answer_op(Q3, "zz"),
            completed_op(SEED_REV_FR),
        ]

    with_rewards = (await push(on, tokens["student_a"], batch())).json()
    without = (await push(off, tokens["student_b"], batch())).json()
    assert shape(with_rewards) == shape(without)
    assert set(with_rewards) == {"results", "server_version", "canon_version"}
    assert "gold" not in str(with_rewards) and "reward" not in str(with_rewards)


# ------------------------------------------------- replays, reuse, two devices
async def test_replay_of_the_same_op_awards_once(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    batch = [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)]
    first = await push(on, tokens["student_a"], batch)
    before = await ledger_rows(admin, STUDENT_A)
    for _ in range(3):
        again = (await push(on, tokens["student_a"], batch)).json()
        assert [(r["status"], r["replayed"]) for r in again["results"]] == [("accepted", True)] * 2
    assert first.status_code == 200
    assert await ledger_rows(admin, STUDENT_A) == before, "replays changed nothing"
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35


async def test_op_id_reuse_with_a_different_payload_earns_nothing(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op_id = uuid.uuid4()
    assert (await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT, op_id)])).json()[
        "results"
    ][0]["status"] == "accepted"
    # Same op id, now claiming a correct answer to ANOTHER question and a completion.
    for forged in (answer_op(Q2, Q2_CORRECT, op_id), completed_op(SEED_REV_FR, op_id)):
        result = (await push(on, tokens["student_a"], [forged])).json()["results"][0]
        assert (result["status"], result["code"]) == (
            "conflict",
            "op_id_reused_with_different_payload",
        )
    assert keys(await ledger_rows(admin, STUDENT_A)) == [Q1_KEY]
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == QUESTION_GOLD


async def test_same_correct_answer_from_two_devices_awards_once(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    device_1 = answer_op(Q1, Q1_CORRECT)
    device_2 = answer_op(Q1, Q1_CORRECT)  # different op id
    other_locale = answer_op(Q1_HT, Q1_HT_CORRECT)  # same lesson + question key, Creole revision
    for op in (device_1, device_2, other_locale):
        result = (await push(on, tokens["student_a"], [op])).json()["results"][0]
        assert (result["status"], result["replayed"]) == ("accepted", False)
    rows = await ledger_rows(admin, STUDENT_A)
    assert keys(rows) == [Q1_KEY]
    assert str(rows[0]["source_op_id"]) == device_1["op_id"], "the FIRST accepted answer earned it"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1", STUDENT_A
        )
        == 3
    ), "all three attempts are kept as learning history"
    outcomes = await admin.fetch(
        "SELECT outcome FROM rewards.processed_operations WHERE learner_id = $1 ORDER BY processed_at, outcome",
        STUDENT_A,
    )
    assert sorted(o["outcome"] for o in outcomes) == ["awarded", "duplicate", "duplicate"]
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == QUESTION_GOLD


async def test_a_newer_revision_of_the_same_question_does_not_pay_again(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    lesson = await publish_new_lesson(admin)
    first = (
        await push(on, tokens["student_a"], [answer_op(lesson["question_ids"][0], "b")])
    ).json()["results"][0]
    assert first["status"] == "accepted" and first["result"]["is_correct"] is True

    revision_2, questions_2 = await create_revision(admin, lesson["lesson_id"], revision=2)
    await approve_revision(admin, revision_2)
    await release_pack(admin, lesson["pack_key"], revision_2, pack_revision=2)
    second = (await push(on, tokens["student_a"], [answer_op(questions_2[0], "b")])).json()[
        "results"
    ][0]
    assert second["status"] == "accepted" and second["result"]["is_correct"] is True
    assert second["result"]["question_revision_id"] != first["result"]["question_revision_id"]

    assert keys(await ledger_rows(admin, STUDENT_A)) == [f"q:{lesson['lesson_id']}:q1"]
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == QUESTION_GOLD


# -------------------------------------------- wrong, correct after wrong, rejected
async def test_wrong_only_earns_nothing_and_correct_after_wrong_earns_once(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    for _ in range(3):
        await push(on, tokens["student_a"], [answer_op(Q1, "a")])
    assert await ledger_total(admin, STUDENT_A) == (0, 0), "wrong answers earn nothing"
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 0
    # ... but they are learning activity: the day counts for the streak.
    assert (await summary(on, tokens["student_a"]))["streak"]["current_days"] == 1

    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])
    await push(on, tokens["student_a"], [answer_op(Q1, "a")])
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])
    assert keys(await ledger_rows(admin, STUDENT_A)) == [Q1_KEY]
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == QUESTION_GOLD


async def test_rejected_and_invalid_operations_earn_nothing(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    draft_lesson = await admin.fetchval(
        "SELECT q.id FROM app.question_revisions q JOIN app.lesson_revisions lr ON lr.id = q.lesson_revision_id "
        "WHERE lr.status <> 'approved' LIMIT 1"
    )
    ops: list[dict[str, Any]] = [
        answer_op(Q1, "zz"),  # a choice that is not offered
        answer_op(uuid.uuid4(), "a"),  # unknown question
        completed_op(uuid.uuid4()),  # unknown lesson revision
        {"op_id": str(uuid.uuid4()), "kind": "award_gold", "payload": {"amount": 1000}},
        # The device tries to attach an amount to a real, correct answer.
        {
            "op_id": str(uuid.uuid4()),
            "kind": "practice_answer",
            "payload": {
                "question_revision_id": str(Q2),
                "response": {"choice_id": Q2_CORRECT},
                "gold": 1000,
            },
        },
    ]
    if draft_lesson is not None:
        ops.append(answer_op(draft_lesson, "b"))
    results = (await push(on, tokens["student_a"], ops)).json()["results"]
    assert {r["status"] for r in results} == {"rejected"}, results
    assert await ledger_total(admin, STUDENT_A) == (0, 0)
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM rewards.processed_operations WHERE learner_id = $1", STUDENT_A
        )
        == 0
    )
    body = await summary(on, tokens["student_a"])
    assert (body["balance"], body["streak"]["current_days"], body["achievements"]) == (0, 0, [])


async def test_repeated_completion_earns_once(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    for revision in (SEED_REV_FR, SEED_REV_HT, SEED_REV_FR, SEED_REV_HT):
        result = (await push(on, tokens["student_a"], [completed_op(revision)])).json()["results"][
            0
        ]
        assert result["status"] == "accepted"
    assert keys(await ledger_rows(admin, STUDENT_A)) == sorted(
        [LESSON_KEY, "a:first_lesson_completed"]
    )
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == LESSON_GOLD + FIRST_LESSON_BONUS


# ------------------------------------------------------------------ concurrency
async def test_twenty_concurrent_pushes_of_the_same_batch_award_exactly_once(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    batch = [
        answer_op(Q1, Q1_CORRECT),
        answer_op(Q2, Q2_CORRECT),
        answer_op(Q3, "a"),
        completed_op(SEED_REV_FR),
    ]
    responses = await asyncio.gather(*(push(on, tokens["student_a"], batch) for _ in range(20)))
    assert [r.status_code for r in responses] == [200] * 20
    fresh = sum(
        1
        for response in responses
        for result in response.json()["results"]
        if not result["replayed"]
    )
    assert fresh == 4, "each operation was applied by exactly one of the twenty requests"

    rows = await ledger_rows(admin, STUDENT_A)
    assert keys(rows) == sorted(
        [Q1_KEY, f"q:{SEED_LESSON}:multiplication", LESSON_KEY, "a:first_lesson_completed"]
    )
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 40
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM rewards.processed_operations WHERE learner_id = $1", STUDENT_A
        )
        == 4
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM rewards.achievement_awards WHERE learner_id = $1", STUDENT_A
        )
        == 2
    )


async def test_two_devices_race_on_the_same_question_with_different_op_ids(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    ops = [answer_op(Q1, Q1_CORRECT) for _ in range(12)] + [
        completed_op(SEED_REV_FR) for _ in range(8)
    ]
    responses = await asyncio.gather(*(push(on, tokens["student_a"], [op]) for op in ops))
    assert [r.status_code for r in responses] == [200] * 20
    assert keys(await ledger_rows(admin, STUDENT_A)) == sorted(
        [Q1_KEY, LESSON_KEY, "a:first_lesson_completed"]
    )
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35
    assert await unexamined(admin, STUDENT_A) == 0


async def test_reconcile_and_rebuild_are_safe_while_pushes_are_running(
    on: httpx.AsyncClient,
    off: httpx.AsyncClient,
    rewards_app: FastAPI,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    """Hook, lazy reconcile (summary), direct reconcile, the batch reconcile and
    balance rebuilds all running at once for one learner must still produce
    each award exactly once and a balance equal to the ledger."""
    lesson = await publish_new_lesson(admin, questions=(("mcq", "b"),) * 12)
    questions = lesson["question_ids"]

    # Phase 1 — rewards switched off: six correct answers and a completion sync with no award.
    backlog = [answer_op(q, "b") for q in questions[:6]] + [completed_op(lesson["revision_id"])]
    assert (await push(off, tokens["student_a"], backlog)).status_code == 200
    assert await ledger_total(admin, STUDENT_A) == (0, 0)
    assert await unexamined(admin, STUDENT_A) == 7

    # Phase 2 — everything at once.
    new_batch = [answer_op(q, "b") for q in questions[6:]]

    async def reconcile_through_the_api_role() -> int:
        async with rewards_app.state.db.transaction(STUDENT_A) as conn:
            outcome = (
                await conn.execute(text("SELECT rewards.reconcile_learner(3) AS o"))
            ).scalar_one()
        return int(outcome["examined"])

    jobs: list[Any] = []
    jobs += [push(on, tokens["student_a"], backlog) for _ in range(5)]  # replays -> hook
    jobs += [push(on, tokens["student_a"], new_batch) for _ in range(5)]
    jobs += [on.get("/v1/rewards/summary", headers=bearer(tokens["student_a"])) for _ in range(6)]
    jobs += [reconcile_through_the_api_role() for _ in range(4)]
    jobs += [admin.fetchval("SELECT rewards.rebuild_balance($1)", STUDENT_A) for _ in range(4)]
    jobs += [admin.fetchval("SELECT rewards.reconcile_batch(10, 5)") for _ in range(2)]
    outcomes = await asyncio.gather(*jobs, return_exceptions=True)
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    assert not failures, failures
    assert all(o.status_code == 200 for o in outcomes if isinstance(o, httpx.Response)), [
        o.text for o in outcomes if isinstance(o, httpx.Response) and o.status_code != 200
    ]

    # Anything a bounded reconcile left over is finished here.
    while (await summary(on, tokens["student_a"]))["up_to_date"] is False:
        pass

    rows = await ledger_rows(admin, STUDENT_A)
    expected = sorted(
        [f"q:{lesson['lesson_id']}:q{n}" for n in range(1, 13)]
        + [f"l:{lesson['lesson_id']}", "a:first_lesson_completed", "a:ten_correct_answers"]
    )
    assert keys(rows) == expected
    total = 12 * QUESTION_GOLD + LESSON_GOLD + FIRST_LESSON_BONUS + TEN_CORRECT_BONUS
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == total
    assert await unexamined(admin, STUDENT_A) == 0
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM rewards.processed_operations WHERE learner_id = $1", STUDENT_A
        )
        == 13
    ), "13 accepted operations, each examined exactly once"
    # A rebuild from the ledger alone agrees with the trigger-maintained balance.
    rebuilt = await admin.fetchval("SELECT rewards.rebuild_balance($1)", STUDENT_A)
    assert '"corrected": false' in rebuilt
    assert (await summary(on, tokens["student_a"]))["balance"] == total


async def test_two_learners_do_not_block_or_mix(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    jobs = []
    for _ in range(5):
        jobs.append(push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)]))
        jobs.append(push(on, tokens["student_b"], [answer_op(Q1_HT, Q1_HT_CORRECT)]))
        jobs.append(push(on, tokens["student_b"], [completed_op(SEED_REV_HT)]))
    assert {r.status_code for r in await asyncio.gather(*jobs)} == {200}
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 5
    assert await assert_balance_matches_ledger(admin, STUDENT_B) == 35


# ------------------------------------------------------------------------ caps
async def test_per_lesson_cap_bounds_farming(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """Placeholder rule: 5 Gold per question, at most 100 Gold per lesson."""
    lesson = await publish_new_lesson(admin, questions=(("mcq", "b"),) * 25)
    batch = [answer_op(q, "b") for q in lesson["question_ids"]]
    results = (await push(on, tokens["student_a"], batch)).json()["results"]
    assert [r["status"] for r in results] == ["accepted"] * 25, "learning is never capped"

    question_gold = await admin.fetchval(
        "SELECT sum(amount) FROM rewards.ledger WHERE learner_id = $1 AND lesson_id = $2 "
        "AND source_kind = 'question_first_correct'",
        STUDENT_A,
        lesson["lesson_id"],
    )
    assert question_gold == 100
    outcomes = await admin.fetch(
        "SELECT outcome, count(*) AS n FROM rewards.processed_operations WHERE learner_id = $1 GROUP BY outcome",
        STUDENT_A,
    )
    assert {o["outcome"]: o["n"] for o in outcomes} == {"awarded": 20, "capped_lesson": 5}
    # Retrying the capped operations, or answering the capped questions again, does not get around the cap.
    await push(on, tokens["student_a"], batch)
    await push(on, tokens["student_a"], [answer_op(q, "b") for q in lesson["question_ids"][20:]])
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 100 + TEN_CORRECT_BONUS


async def test_concurrent_reconcilers_cannot_overshoot_a_cap_or_examine_an_operation_twice(
    on: httpx.AsyncClient,
    off: httpx.AsyncClient,
    rewards_app: FastAPI,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    """Reconcile does not hold the sync lock, so several reconcilers (and the
    push hook) really do race for the same learner. The per-learner rewards
    lock must keep the cap exact and every operation examined once."""
    lesson = await publish_new_lesson(admin, questions=(("mcq", "b"),) * 25)
    backlog = [answer_op(q, "b") for q in lesson["question_ids"]]
    assert (await push(off, tokens["student_a"], backlog)).status_code == 200
    assert await unexamined(admin, STUDENT_A) == 25

    async def reconcile(limit: int) -> None:
        async with rewards_app.state.db.transaction(STUDENT_A) as conn:
            await conn.execute(text("SELECT rewards.reconcile_learner(:n)"), {"n": limit})

    jobs: list[Any] = [reconcile(4) for _ in range(8)]
    jobs += [admin.fetchval("SELECT rewards.reconcile_batch(5, 3)") for _ in range(3)]
    jobs += [push(on, tokens["student_a"], backlog[10:20]) for _ in range(3)]  # hook on replays
    jobs += [on.get("/v1/rewards/summary", headers=bearer(tokens["student_a"])) for _ in range(4)]
    outcomes = await asyncio.gather(*jobs, return_exceptions=True)
    assert not [o for o in outcomes if isinstance(o, BaseException)], outcomes
    while (await summary(on, tokens["student_a"]))["up_to_date"] is False:
        pass

    assert await unexamined(admin, STUDENT_A) == 0
    outcomes_by_kind = await admin.fetch(
        "SELECT outcome, count(*) AS n FROM rewards.processed_operations WHERE learner_id = $1 GROUP BY outcome",
        STUDENT_A,
    )
    assert {o["outcome"]: o["n"] for o in outcomes_by_kind} == {"awarded": 20, "capped_lesson": 5}
    question_gold = await admin.fetchval(
        "SELECT sum(amount) FROM rewards.ledger WHERE learner_id = $1 AND lesson_id = $2 "
        "AND source_kind = 'question_first_correct'",
        STUDENT_A,
        lesson["lesson_id"],
    )
    assert question_gold == 100, "the per-lesson cap held under concurrency"
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 100 + TEN_CORRECT_BONUS


# ------------------------------------------------- hook off / hook failing
async def test_reconcile_heals_operations_synced_while_the_hook_was_off(
    on: httpx.AsyncClient, off: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    batch = [answer_op(Q1, Q1_CORRECT), answer_op(Q2, "d"), completed_op(SEED_REV_FR)]
    assert (await push(off, tokens["student_a"], batch)).status_code == 200
    assert await ledger_total(admin, STUDENT_A) == (0, 0), "flag off: nothing is awarded"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM rewards.processed_operations WHERE learner_id = $1", STUDENT_A
        )
        == 0
    ), "flag off: the rewards schema is not touched at all"
    receipts = await admin.fetch(
        "SELECT op_id, created_at FROM app.sync_receipts WHERE learner_id = $1", STUDENT_A
    )

    body = await summary(on, tokens["student_a"])
    assert (body["balance"], body["up_to_date"]) == (35, True)
    rows = await ledger_rows(admin, STUDENT_A)
    assert keys(rows) == sorted([Q1_KEY, LESSON_KEY, "a:first_lesson_completed"])
    accepted_at = {r["op_id"]: r["created_at"] for r in receipts}
    stored = await admin.fetch(
        "SELECT source_op_id, accepted_at FROM rewards.ledger WHERE learner_id = $1", STUDENT_A
    )
    assert all(row["accepted_at"] == accepted_at[row["source_op_id"]] for row in stored), (
        "healed awards keep the instant the server accepted the operation"
    )
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35
    # Idempotent: reading again, replaying the batch with the hook on — nothing more.
    await summary(on, tokens["student_a"])
    await push(on, tokens["student_a"], batch)
    assert await ledger_rows(admin, STUDENT_A) == rows


async def test_reward_failure_does_not_fail_the_learning_operation(
    on: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A real database error inside the award step: the savepoint is rolled
    back, the learning operations commit, the response is the normal one."""
    batch = [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)]
    await admin.execute("REVOKE EXECUTE ON FUNCTION rewards.award_for_operation(uuid) FROM edu_api")
    try:
        with caplog.at_level(logging.ERROR, logger="edu_api.rewards"):
            response = await push(on, tokens["student_a"], batch)
    finally:
        await admin.execute(
            "GRANT EXECUTE ON FUNCTION rewards.award_for_operation(uuid) TO edu_api"
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(r["status"], r["replayed"]) for r in body["results"]] == [("accepted", False)] * 2
    assert body["server_version"] == 2

    # The learning data is durably there ...
    state = await admin.fetchrow(
        "SELECT (SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1) AS attempts,"
        " (SELECT count(*) FROM app.sync_receipts WHERE learner_id = $1 AND result_code = 'accepted') AS receipts,"
        " (SELECT count(*) FROM app.lesson_progress WHERE learner_id = $1 AND completed_at IS NOT NULL) AS completed,"
        " (SELECT count(*) FROM app.account_change_feed WHERE learner_id = $1) AS changes",
        STUDENT_A,
    )
    assert dict(state) == {"attempts": 1, "receipts": 2, "completed": 1, "changes": 2}
    # ... the reward is not, and the failure was logged once per operation without payload data.
    assert await ledger_total(admin, STUDENT_A) == (0, 0)
    lines = [r.getMessage() for r in caplog.records if "rewards_award_failed" in r.getMessage()]
    assert len(lines) == 1, "after the first failure the rest of the batch skips the reward step"
    assert all("sqlstate=42501" in line and str(STUDENT_A) in line for line in lines)

    # Healing: a retry of the same batch (hook working again) awards it ...
    retry = (await push(on, tokens["student_a"], batch)).json()
    assert [(r["status"], r["replayed"]) for r in retry["results"]] == [("accepted", True)] * 2
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35


async def test_a_busy_rewards_lock_cannot_stall_a_push(
    on: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    local_env: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Security review M1. Another session sits on the learner's rewards lock
    (a slow worker batch, an erasure, or a hostile session squatting on the
    advisory key). The push holds the learner's SYNC lock, so it must not queue
    behind that: it waits ~200 ms once, then the whole batch commits unrewarded."""
    import time

    lesson = await publish_new_lesson(admin, questions=(("mcq", "b"),) * 10)
    batch = [answer_op(q, "b") for q in lesson["question_ids"]]
    second_device = [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)]

    squatter = await asyncpg.connect(
        local_env["EDU_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    transaction = squatter.transaction()
    await transaction.start()
    try:
        # Exactly what a session with only the API login can do (advisory locks are PUBLIC).
        await squatter.execute(
            "SELECT pg_advisory_xact_lock(54050, hashtext($1::text))", str(STUDENT_A)
        )
        await push(on, tokens["student_b"], [answer_op(Q1, "a")])  # warm the pool
        with caplog.at_level(logging.WARNING, logger="edu_api.rewards"):
            started = time.monotonic()
            first, second = await asyncio.gather(
                push(on, tokens["student_a"], batch), push(on, tokens["student_a"], second_device)
            )
            elapsed = time.monotonic() - started
        assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
        assert [r["status"] for r in first.json()["results"]] == ["accepted"] * 10
        assert [r["status"] for r in second.json()["results"]] == ["accepted"] * 2
        # Two pushes, one bounded wait each (~0.2 s), not 12 x 5 s.
        assert elapsed < 1.5, f"pushes took {elapsed:.2f}s behind a held rewards lock"
        deferred = [
            r.getMessage() for r in caplog.records if "rewards_award_deferred" in r.getMessage()
        ]
        assert len(deferred) == 2, "one line per batch, not one per operation"
        assert await ledger_total(admin, STUDENT_A) == (0, 0)
        assert await unexamined(admin, STUDENT_A) == 12
        # The other learner is not affected at all.
        other = await push(on, tokens["student_b"], [answer_op(Q1, Q1_CORRECT)])
        assert other.status_code == 200
        assert await ledger_total(admin, STUDENT_B) == (1, QUESTION_GOLD)
        # The worker batch skips the busy learner instead of waiting behind the lock.
        report = await admin.fetchval("SELECT rewards.reconcile_batch(20, 200)")
        assert '"skipped": 1' in report and '"examined": 0' in report
    finally:
        await transaction.rollback()
        await squatter.close()

    # Lock released: reconciliation awards every operation exactly once.
    while (await summary(on, tokens["student_a"]))["up_to_date"] is False:
        pass
    expected = (
        10 * QUESTION_GOLD + QUESTION_GOLD + LESSON_GOLD + FIRST_LESSON_BONUS + TEN_CORRECT_BONUS
    )
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == expected
    assert await unexamined(admin, STUDENT_A) == 0
    await push(on, tokens["student_a"], batch + second_device)  # replays change nothing
    await summary(on, tokens["student_a"])
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == expected


async def test_a_failed_award_is_also_healed_by_reconcile_without_a_retry(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    await admin.execute("REVOKE EXECUTE ON FUNCTION rewards.award_for_operation(uuid) FROM edu_api")
    try:
        response = await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])
    finally:
        await admin.execute(
            "GRANT EXECUTE ON FUNCTION rewards.award_for_operation(uuid) TO edu_api"
        )
    assert response.status_code == 200
    assert await ledger_total(admin, STUDENT_A) == (0, 0)
    assert (await summary(on, tokens["student_a"]))["balance"] == QUESTION_GOLD
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == QUESTION_GOLD


async def test_a_failing_transaction_awards_nothing(
    on: httpx.AsyncClient,
    rewards_app: FastAPI,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gold commits atomically with the operation: if the push transaction
    rolls back after the award step ran, the award is gone too."""
    from edu_api.sync import service

    async def boom(conn: Any, learner_id: uuid.UUID) -> int:
        raise RuntimeError("simulated crash after the award step but before COMMIT")

    real = service._current_version
    monkeypatch.setattr(service, "_current_version", boom)
    batch = [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)]
    transport = httpx.ASGITransport(app=rewards_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        failed = await http.post(
            "/v1/sync/push", json={"ops": batch}, headers=bearer(tokens["student_a"])
        )
    assert failed.status_code == 500
    assert await ledger_total(admin, STUDENT_A) == (0, 0)
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 0
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM rewards.processed_operations WHERE learner_id = $1", STUDENT_A
        )
        == 0
    )

    monkeypatch.setattr(service, "_current_version", real)
    assert (await push(on, tokens["student_a"], batch)).status_code == 200
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35


# ------------------------------------------------------ rebuild, reversal, erase
async def test_rebuild_from_scratch_equals_the_running_balance(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    await push(
        on,
        tokens["student_a"],
        [answer_op(Q1, Q1_CORRECT), answer_op(Q2, Q2_CORRECT), completed_op(SEED_REV_FR)],
    )
    running = await assert_balance_matches_ledger(admin, STUDENT_A)
    assert running == 40

    await admin.execute("DELETE FROM rewards.balances WHERE learner_id = $1", STUDENT_A)
    assert (await summary(on, tokens["student_a"]))["balance"] == 0, "control: the cache is gone"
    await admin.fetchval("SELECT rewards.rebuild_balance($1)", STUDENT_A)
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == running
    assert (await summary(on, tokens["student_a"]))["balance"] == running

    await admin.execute(
        "UPDATE rewards.balances SET balance = 7, lifetime_earned = 7 WHERE learner_id = $1",
        STUDENT_A,
    )
    await admin.fetchval("SELECT rewards.rebuild_balance($1)", STUDENT_A)
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == running


async def test_a_correction_is_a_reversal_row_and_shows_in_the_api(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)])
    lesson_row = await admin.fetchval(
        "SELECT id FROM rewards.ledger WHERE learner_id = $1 AND source_kind = 'lesson_first_completed'",
        STUDENT_A,
    )
    await admin.fetchval("SELECT rewards.reverse_entry($1, 'test_correction')", lesson_row)
    body = await summary(on, tokens["student_a"])
    assert (body["balance"], body["lifetime_earned"]) == (15, 35)
    assert body["recent"][0]["kind"] == "reversal" and body["recent"][0]["amount"] == -LESSON_GOLD
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 15
    # The reversed thing cannot be earned again.
    await push(on, tokens["student_a"], [completed_op(SEED_REV_HT)])
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 15


async def test_erasure_is_not_undone_by_a_summary_or_a_reconcile(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """Security review L2. The orchestrator's contract: in ONE transaction call
    the hook (it keeps the learner's rewards lock until commit), remove the
    learner's receipts, commit. Requests racing with it recreate nothing."""
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)])
    await push(on, tokens["student_b"], [answer_op(Q1, Q1_CORRECT)])
    assert (await summary(on, tokens["student_a"]))["balance"] == 35

    async with admin.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        await conn.fetchval("SELECT rewards.erase_learner($1)", STUDENT_A)
        # While the erasure is still open: a summary (lazy reconcile) and a
        # retried push arrive for the same learner.
        racing = [
            asyncio.create_task(on.get("/v1/rewards/summary", headers=bearer(tokens["student_a"])))
            for _ in range(3)
        ]
        await asyncio.sleep(0.3)
        await conn.execute(
            "TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, "
            "app.lesson_progress, app.account_sync_state"
        )
        await transaction.commit()
    responses = await asyncio.gather(*racing)
    assert [r.status_code for r in responses] == [200] * 3
    # A request that read before the commit may still show the old balance
    # (the erasure was not committed yet); none may show anything else.
    assert {r.json()["balance"] for r in responses} <= {0, 35}

    for _ in range(2):
        body = await summary(on, tokens["student_a"])
        assert (body["balance"], body["recent"], body["achievements"]) == (0, [], [])
        assert body["streak"]["longest_days"] == 0 and body["up_to_date"] is True
    assert await admin.fetchval("SELECT rewards.reconcile_batch(20, 200)") is not None
    for table in (
        "ledger",
        "balances",
        "processed_operations",
        "activity_days",
        "streak_state",
        "achievement_awards",
    ):
        assert (
            await admin.fetchval(
                f"SELECT count(*) FROM rewards.{table} WHERE learner_id = $1", STUDENT_A
            )
            == 0
        ), table


async def test_receipts_left_behind_after_erasure_are_re_derived_as_documented(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """The other half of the contract, stated honestly: the hook alone is not an
    account deletion. If the caller leaves accepted receipts in place, the next
    reconcile rebuilds the rewards from them — exactly once, never doubled."""
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)])
    await admin.fetchval("SELECT rewards.erase_learner($1)", STUDENT_A)
    assert await ledger_total(admin, STUDENT_A) == (0, 0)
    assert (await summary(on, tokens["student_a"]))["balance"] == 35
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35


async def test_erasure_hook_removes_every_rewards_row_of_one_learner(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    for token in ("student_a", "student_b"):
        await push(on, tokens[token], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)])
    assert (await summary(on, tokens["student_a"]))["balance"] == 35

    # The account orchestrator erases the learning rows first (otherwise a
    # later reconcile would faithfully re-derive the rewards), then calls the hook.
    await admin.execute(
        "TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, "
        "app.lesson_progress, app.account_sync_state"
    )
    report = await admin.fetchval("SELECT rewards.erase_learner($1)", STUDENT_A)
    assert '"schema": "rewards"' in report and '"ledger": 3' in report

    for table in (
        "ledger",
        "balances",
        "processed_operations",
        "activity_days",
        "streak_state",
        "achievement_awards",
    ):
        assert (
            await admin.fetchval(
                f"SELECT count(*) FROM rewards.{table} WHERE learner_id = $1", STUDENT_A
            )
            == 0
        ), table
    erased = await summary(on, tokens["student_a"])
    assert (erased["balance"], erased["lifetime_earned"], erased["achievements"]) == (0, 0, [])
    assert erased["recent"] == [] and erased["streak"]["longest_days"] == 0
    assert await assert_balance_matches_ledger(admin, STUDENT_B) == 35, "B is untouched"
