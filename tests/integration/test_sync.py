"""Offline sync: exactly-once push, ordered account-scoped pull.

All assertions about "what really happened" read canonical state through the
``admin`` fixture connection, not through the API under test.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import uuid
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.sync.cursor import encode_cursor
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

pytestmark = pytest.mark.integration

Q1, Q1_CORRECT = SEED_QUESTIONS_FR[0]
Q2, Q2_CORRECT = SEED_QUESTIONS_FR[1]


async def push(client: httpx.AsyncClient, token: str, ops: list[dict[str, Any]]) -> httpx.Response:
    return await client.post("/v1/sync/push", json={"ops": ops}, headers=bearer(token))


async def pull(client: httpx.AsyncClient, token: str, **params: Any) -> httpx.Response:
    return await client.get("/v1/sync/pull", params=params, headers=bearer(token))


async def counts(admin: asyncpg.Pool, learner: uuid.UUID) -> dict[str, int]:
    row = await admin.fetchrow(
        "SELECT (SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1) AS attempts,"
        " (SELECT count(*) FROM app.sync_receipts WHERE learner_id = $1) AS receipts,"
        " (SELECT count(*) FROM app.account_change_feed WHERE learner_id = $1) AS changes,"
        " (SELECT count(*) FROM app.lesson_progress WHERE learner_id = $1) AS progress,"
        " COALESCE((SELECT current_version FROM app.account_sync_state WHERE learner_id = $1), 0) AS version",
        learner,
    )
    return dict(row)


# ------------------------------------------------------------------ happy path
async def test_push_then_pull_round_trip(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    ops = [answer_op(Q1, Q1_CORRECT), answer_op(Q2, "d"), completed_op(SEED_REV_FR)]
    response = await push(client, tokens["student_a"], ops)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["op_id"] for r in body["results"]] == [op["op_id"] for op in ops]
    assert [r["status"] for r in body["results"]] == ["accepted"] * 3
    assert [r["replayed"] for r in body["results"]] == [False] * 3
    assert body["results"][0]["result"]["is_correct"] is True
    assert body["results"][0]["result"]["score"] == 1
    assert body["results"][1]["result"]["is_correct"] is False
    assert body["results"][1]["result"]["score"] == 0
    assert body["results"][2]["result"]["lesson_id"] == str(SEED_LESSON)
    assert [r["result"]["change_version"] for r in body["results"]] == [1, 2, 3]
    assert body["server_version"] == 3 and body["canon_version"] == "mep-canon-1"

    pulled = (await pull(client, tokens["student_a"])).json()
    assert [c["version"] for c in pulled["changes"]] == [1, 2, 3]
    assert [c["entity_type"] for c in pulled["changes"]] == [
        "practice_attempt",
        "practice_attempt",
        "lesson_progress",
    ]
    assert [c["data"]["op_id"] for c in pulled["changes"]] == [op["op_id"] for op in ops]
    assert pulled["changes"][0]["entity_id"] == body["results"][0]["result"]["attempt_id"]
    assert pulled["has_more"] is False and pulled["server_version"] == 3

    again = (await pull(client, tokens["student_a"], cursor=pulled["next_cursor"])).json()
    assert again["changes"] == [] and again["next_cursor"] == pulled["next_cursor"]

    assert await counts(admin, STUDENT_A) == {
        "attempts": 2,
        "receipts": 3,
        "changes": 3,
        "progress": 1,
        "version": 3,
    }
    stored = await admin.fetch(
        "SELECT score, scoring_version FROM app.practice_attempts WHERE learner_id = $1 ORDER BY accepted_at, score DESC",
        STUDENT_A,
    )
    assert sorted(float(r["score"]) for r in stored) == [0.0, 1.0]
    assert {r["scoring_version"] for r in stored} == {"mcq-v1"}


async def test_score_and_identity_in_the_request_are_never_trusted(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """A wrong answer stays wrong whatever the client claims; nobody else is touched."""
    cheat_fields = [
        {"score": 1},
        {"is_correct": True},
        {"learner_id": str(STUDENT_B)},
        {"user_id": str(STUDENT_B)},
    ]
    ops = []
    for extra in cheat_fields:
        op = answer_op(Q1, "a")  # wrong choice
        op["payload"].update(extra)
        ops.append(op)
    top_level = answer_op(Q1, "a")
    response = await client.post(
        "/v1/sync/push",
        headers=bearer(tokens["student_a"]),
        json={"ops": [top_level], "learner_id": str(STUDENT_B)},
    )
    assert response.status_code == 422  # unknown envelope field
    op_level = {**answer_op(Q1, "a"), "learner_id": str(STUDENT_B)}
    assert (await push(client, tokens["student_a"], [op_level])).status_code == 422

    body = (await push(client, tokens["student_a"], ops)).json()
    assert [(r["status"], r["code"]) for r in body["results"]] == [
        ("rejected", "invalid_payload")
    ] * 4

    honest = (await push(client, tokens["student_a"], [answer_op(Q1, "a")])).json()
    assert honest["results"][0]["result"]["score"] == 0
    assert await counts(admin, STUDENT_B) == {
        "attempts": 0,
        "receipts": 0,
        "changes": 0,
        "progress": 0,
        "version": 0,
    }
    assert await admin.fetchval("SELECT max(score) FROM app.practice_attempts") == 0


# ------------------------------------------------------------ idempotent retry
async def test_same_answer_sent_twice_creates_one_attempt(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op = answer_op(Q1, Q1_CORRECT)
    first = (await push(client, tokens["student_a"], [op])).json()["results"][0]
    second = (await push(client, tokens["student_a"], [op])).json()["results"][0]
    assert first["status"] == second["status"] == "accepted"
    assert (first["replayed"], second["replayed"]) == (False, True)
    assert second["result"] == first["result"]
    assert await counts(admin, STUDENT_A) == {
        "attempts": 1,
        "receipts": 1,
        "changes": 1,
        "progress": 0,
        "version": 1,
    }


async def test_retry_with_different_json_spelling_is_still_the_same_operation(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op_id = str(uuid.uuid4())
    first = {
        "op_id": op_id,
        "kind": "practice_answer",
        "client_recorded_at": "2026-11-21T08:00:00Z",
        "payload": {"question_revision_id": str(Q1), "response": {"choice_id": Q1_CORRECT}},
    }
    retry = {
        "payload": {"response": {"choice_id": Q1_CORRECT}, "question_revision_id": str(Q1).upper()},
        "client_recorded_at": "2026-11-23T19:30:00-05:00",
        "kind": "practice_answer",
        "op_id": op_id.upper(),
    }
    assert (await push(client, tokens["student_a"], [first])).json()["results"][0][
        "replayed"
    ] is False
    again = (await push(client, tokens["student_a"], [retry])).json()["results"][0]
    assert (again["status"], again["replayed"]) == ("accepted", True)
    assert (await counts(admin, STUDENT_A))["attempts"] == 1
    # the first accepted submission's display timestamp is kept
    stored = await admin.fetchval("SELECT client_recorded_at::text FROM app.practice_attempts")
    assert stored.startswith("2026-11-21 08:00:00")


async def test_twenty_concurrent_identical_retries(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op = answer_op(Q1, Q1_CORRECT)
    responses = await asyncio.gather(*(push(client, tokens["student_a"], [op]) for _ in range(20)))
    assert [r.status_code for r in responses] == [200] * 20
    results = [r.json()["results"][0] for r in responses]
    assert {r["status"] for r in results} == {"accepted"}
    assert sum(1 for r in results if not r["replayed"]) == 1, "exactly one request did the work"
    assert len({json.dumps(r["result"], sort_keys=True) for r in results}) == 1, (
        "all saw the same result"
    )
    assert await counts(admin, STUDENT_A) == {
        "attempts": 1,
        "receipts": 1,
        "changes": 1,
        "progress": 0,
        "version": 1,
    }


async def test_twenty_concurrent_identical_lesson_completions(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op = completed_op(SEED_REV_FR)
    responses = await asyncio.gather(*(push(client, tokens["student_a"], [op]) for _ in range(20)))
    assert [r.status_code for r in responses] == [200] * 20
    assert sum(1 for r in responses if not r.json()["results"][0]["replayed"]) == 1
    assert await counts(admin, STUDENT_A) == {
        "attempts": 0,
        "receipts": 1,
        "changes": 1,
        "progress": 1,
        "version": 1,
    }


# ------------------------------------------------------------------- conflict
async def test_same_op_id_with_different_body_conflicts_without_side_effects(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op_id = uuid.uuid4()
    original = answer_op(Q1, "a", op_id)  # wrong answer
    assert (await push(client, tokens["student_a"], [original])).json()["results"][0][
        "status"
    ] == "accepted"
    before = await counts(admin, STUDENT_A)

    for changed in (
        answer_op(Q1, Q1_CORRECT, op_id),  # "fix" the answer under the same op_id
        answer_op(Q2, "a", op_id),  # another question
        completed_op(SEED_REV_FR, op_id),
    ):  # another kind
        response = await push(client, tokens["student_a"], [changed])
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert (result["status"], result["code"], result["replayed"], result["result"]) == (
            "conflict",
            "op_id_reused_with_different_payload",
            False,
            None,
        )

    assert await counts(admin, STUDENT_A) == before
    row = await admin.fetchrow(
        "SELECT response ->> 'choice_id' AS choice, score FROM app.practice_attempts"
    )
    assert (row["choice"], float(row["score"])) == ("a", 0.0), "the original attempt is untouched"
    # and the original still replays cleanly afterwards
    replay = (await push(client, tokens["student_a"], [original])).json()["results"][0]
    assert (replay["status"], replay["replayed"]) == ("accepted", True)


# ------------------------------------------------- ACK lost after the commit
class DropResponse:
    """ASGI wrapper: lets the application finish (and COMMIT), then loses the reply,
    exactly like a phone whose connection dies while the server is answering."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.completed = 0

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        async def black_hole(message: Any) -> None:
            return None

        await self.app(scope, receive, black_hole)
        self.completed += 1
        raise ConnectionResetError("simulated: response lost on the way to the client")


async def test_commit_succeeds_but_ack_is_lost_then_retry_is_exactly_once(
    app: FastAPI, client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    batch = [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)]
    lossy = DropResponse(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=lossy), base_url="http://api.test"
    ) as flaky:
        with pytest.raises(ConnectionResetError):
            await flaky.post(
                "/v1/sync/push", json={"ops": batch}, headers=bearer(tokens["student_a"])
            )
    assert lossy.completed == 1

    # The client knows nothing, but the server really committed:
    committed = await counts(admin, STUDENT_A)
    assert committed == {"attempts": 1, "receipts": 2, "changes": 2, "progress": 1, "version": 2}

    # The client retries the SAME batch (same op_ids) on a working connection.
    retry = (await push(client, tokens["student_a"], batch)).json()
    assert [(r["status"], r["replayed"]) for r in retry["results"]] == [("accepted", True)] * 2
    assert retry["results"][0]["result"]["is_correct"] is True
    assert await counts(admin, STUDENT_A) == committed, "retry changed nothing"
    assert [c["version"] for c in (await pull(client, tokens["student_a"])).json()["changes"]] == [
        1,
        2,
    ]


async def test_failed_transaction_applies_nothing(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the server fails BEFORE commit, the whole batch is rolled back and a retry applies it once."""
    from edu_api.sync import service

    real = service._current_version
    calls = {"n": 0}

    async def boom(conn: Any, learner_id: uuid.UUID) -> int:
        calls["n"] += 1
        raise RuntimeError("simulated crash after the operations ran but before COMMIT")

    monkeypatch.setattr(service, "_current_version", boom)
    batch = [answer_op(Q1, Q1_CORRECT), answer_op(Q2, Q2_CORRECT)]
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        failed = await http.post(
            "/v1/sync/push", json={"ops": batch}, headers=bearer(tokens["student_a"])
        )
    assert failed.status_code == 500 and failed.json()["error"]["code"] == "internal_error"
    assert calls["n"] == 1
    assert await counts(admin, STUDENT_A) == {
        "attempts": 0,
        "receipts": 0,
        "changes": 0,
        "progress": 0,
        "version": 0,
    }

    monkeypatch.setattr(service, "_current_version", real)
    retry = (await push(client, tokens["student_a"], batch)).json()
    assert [(r["status"], r["replayed"]) for r in retry["results"]] == [("accepted", False)] * 2
    assert (await counts(admin, STUDENT_A))["attempts"] == 2


# ------------------------------------- two students, two devices, concurrently
async def test_two_students_two_devices_concurrent_sync(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    per_device = 12
    sent: dict[str, list[str]] = {"student_a": [], "student_b": []}
    jobs = []
    for who, questions in (("student_a", SEED_QUESTIONS_FR), ("student_b", SEED_QUESTIONS_HT)):
        for device in range(2):
            for n in range(per_device):
                question, correct = questions[(n + device) % 5]
                op = answer_op(question, correct if n % 2 else "a")
                sent[who].append(op["op_id"])
                # one op per request => maximum interleaving between devices and accounts
                jobs.append(push(client, tokens[who], [op]))
    # each device also retries a few of its operations in the same storm
    retried_a = sent["student_a"][:5]
    responses = await asyncio.gather(*jobs)
    assert {r.status_code for r in responses} == {200}
    assert {r.json()["results"][0]["status"] for r in responses} == {"accepted"}

    for who, learner in (("student_a", STUDENT_A), ("student_b", STUDENT_B)):
        versions = [
            r["version"]
            for r in await admin.fetch(
                "SELECT version FROM app.account_change_feed WHERE learner_id = $1 ORDER BY version",
                learner,
            )
        ]
        assert versions == list(range(1, 2 * per_device + 1)), f"{who}: versions must be gap-free"
        assert (await counts(admin, learner)) == {
            "attempts": 2 * per_device,
            "receipts": 2 * per_device,
            "changes": 2 * per_device,
            "progress": 0,
            "version": 2 * per_device,
        }

        # pull in small pages; everything pulled belongs to this account, in order
        seen: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"limit": 7, **({"cursor": cursor} if cursor else {})}
            page = (await pull(client, tokens[who], **params)).json()
            seen.extend(page["changes"])
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        assert [c["version"] for c in seen] == versions
        assert {c["data"]["op_id"] for c in seen} == set(sent[who])
        other = "student_b" if who == "student_a" else "student_a"
        assert not {c["data"]["op_id"] for c in seen} & set(sent[other]), "no cross-account leakage"

    assert retried_a  # (kept for readability of the scenario above)


async def test_same_op_id_from_two_accounts_is_independent(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    shared = uuid.uuid4()
    a, b = await asyncio.gather(
        push(client, tokens["student_a"], [answer_op(Q1, Q1_CORRECT, shared)]),
        push(client, tokens["student_b"], [answer_op(Q2, "b", shared)]),
    )
    assert a.json()["results"][0]["status"] == b.json()["results"][0]["status"] == "accepted"
    assert (await counts(admin, STUDENT_A))["attempts"] == 1
    assert (await counts(admin, STUDENT_B))["attempts"] == 1


# ---------------------------------------------------------------- pull / cursor
async def test_pull_pagination_cursor_and_reset_rules(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    ops = [answer_op(q, c) for q, c in SEED_QUESTIONS_FR]
    await push(client, tokens["student_a"], ops)
    await push(client, tokens["student_b"], [answer_op(SEED_QUESTIONS_HT[0][0], "b")])

    first = (await pull(client, tokens["student_a"], limit=2)).json()
    second = (await pull(client, tokens["student_a"], limit=2, cursor=first["next_cursor"])).json()
    third = (await pull(client, tokens["student_a"], limit=2, cursor=second["next_cursor"])).json()
    assert [[c["version"] for c in page["changes"]] for page in (first, second, third)] == [
        [1, 2],
        [3, 4],
        [5],
    ]
    assert [page["has_more"] for page in (first, second, third)] == [True, True, False]
    # re-reading from an old cursor is harmless and deterministic
    assert (
        await pull(client, tokens["student_a"], limit=2, cursor=first["next_cursor"])
    ).json() == second

    # B's view is only B's
    b_view = (await pull(client, tokens["student_b"])).json()
    assert len(b_view["changes"]) == 1 and b_view["server_version"] == 1

    # A cursor from another account, garbage, or "ahead of the server" => 410 reset
    for bad in (b_view["next_cursor"], "garbage", encode_cursor(STUDENT_A, 999)):
        response = await pull(client, tokens["student_a"], cursor=bad)
        assert response.status_code == 410, bad
        assert response.json()["error"]["code"] == "sync_cursor_invalid"
    # ... and the documented recovery works: pull again with no cursor
    assert len((await pull(client, tokens["student_a"])).json()["changes"]) == 5

    for params in ({"limit": 0}, {"limit": 201}, {"limit": "many"}, {"cursor": "x" * 500}):
        assert (await pull(client, tokens["student_a"], **params)).status_code == 422, params


async def test_empty_account_pull(client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    body = (await pull(client, tokens["student_a"])).json()
    assert body["changes"] == [] and body["server_version"] == 0 and body["has_more"] is False
    assert (await pull(client, tokens["student_a"], cursor=body["next_cursor"])).status_code == 200


async def test_tombstones_are_delivered(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """No operation creates tombstones yet, but the feed and the API must carry them."""
    first = (await push(client, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])).json()
    attempt_id = first["results"][0]["result"]["attempt_id"]
    async with (
        admin.acquire() as conn,
        conn.transaction(),
    ):  # fixture role acting as a future server process
        await conn.execute(
            "UPDATE app.account_sync_state SET current_version = 2 WHERE learner_id = $1", STUDENT_A
        )
        await conn.execute(
            "INSERT INTO app.account_change_feed (learner_id, version, entity_type, entity_id, change_data, is_tombstone) "
            "VALUES ($1, 2, 'practice_attempt', $2, '{\"reason\": \"synthetic test tombstone\"}', true)",
            STUDENT_A,
            uuid.UUID(attempt_id),
        )
    changes = (await pull(client, tokens["student_a"])).json()["changes"]
    assert [(c["version"], c["is_tombstone"], c["entity_id"]) for c in changes] == [
        (1, False, attempt_id),
        (2, True, attempt_id),
    ]
    assert (await pull(client, tokens["student_b"])).json()["changes"] == []


# --------------------------------------- revision provenance after re-publication
async def test_completion_keeps_pointing_at_the_revision_that_was_studied(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    lesson = await publish_new_lesson(admin)
    lesson_id, rev1, q_rev1 = lesson["lesson_id"], lesson["revision_id"], lesson["question_ids"][0]
    token = tokens["student_a"]

    done = (await push(client, token, [completed_op(rev1)])).json()["results"][0]
    assert done["result"]["lesson_revision_id"] == str(rev1)

    # Staff publish revision 2 and retire the old pack.
    rev2, _ = await create_revision(admin, lesson_id, revision=2, title="Synthetic test lesson r2")
    await approve_revision(admin, rev2)
    await release_pack(admin, lesson["pack_key"], rev2, pack_revision=2)

    served = (
        await client.get(f"/v1/lessons/{lesson_id}", params={"locale": "fr"}, headers=bearer(token))
    ).json()
    assert served["revision_id"] == str(rev2) and served["revision"] == 2, (
        "new readers get revision 2"
    )

    stored = await admin.fetchrow(
        "SELECT last_revision_id, completed_at FROM app.lesson_progress WHERE learner_id = $1 AND lesson_id = $2",
        STUDENT_A,
        lesson_id,
    )
    assert stored["last_revision_id"] == rev1, "history still points at revision 1"

    # A phone that was offline still holds revision 1: its late work is accepted ...
    late = (await push(client, token, [answer_op(q_rev1, "b")])).json()["results"][0]
    assert late["status"] == "accepted" and late["result"]["is_correct"] is True
    assert (
        await admin.fetchval(
            "SELECT lesson_revision_id FROM app.practice_attempts WHERE id = $1",
            uuid.UUID(late["result"]["attempt_id"]),
        )
        == rev1
    )
    # ... and completing again against revision 2 does not rewrite history.
    again = (await push(client, token, [completed_op(rev2)])).json()["results"][0]
    assert again["result"]["already_completed"] is True
    assert again["result"]["lesson_revision_id"] == str(rev1)
    after = await admin.fetchrow(
        "SELECT last_revision_id, completed_at FROM app.lesson_progress WHERE learner_id = $1 AND lesson_id = $2",
        STUDENT_A,
        lesson_id,
    )
    assert dict(after) == dict(stored)


# ------------------------------------------------------------- invalid batches
async def test_empty_and_malformed_batches(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    headers = bearer(tokens["student_a"])
    empty = await client.post("/v1/sync/push", json={"ops": []}, headers=headers)
    assert (empty.status_code, empty.json()["error"]["code"]) == (422, "empty_batch")

    cases: list[Any] = [
        {},
        {"ops": "nope"},
        {"ops": [{"kind": "practice_answer", "payload": {}}]},
        {"ops": [{"op_id": "not-a-uuid", "kind": "practice_answer", "payload": {}}]},
        {"ops": [{"op_id": str(uuid.uuid4()), "kind": "practice_answer", "payload": "text"}]},
        {"ops": [{"op_id": str(uuid.uuid4()), "kind": "k" * 41, "payload": {}}]},
        {"ops": [{**answer_op(Q1, "a"), "client_recorded_at": "yesterday"}]},
        {
            "ops": [{**answer_op(Q1, "a"), "client_recorded_at": "2026-11-21T10:00:00"}]
        },  # no timezone
        [1, 2, 3],
    ]
    for body in cases:
        response = await client.post("/v1/sync/push", json=body, headers=headers)
        assert response.status_code == 422, body
        error = response.json()["error"]
        assert error["code"] == "validation_error" and error["details"], body
        assert all(set(item) == {"loc", "msg", "type"} for item in error["details"]), body
        assert "yesterday" not in response.text, "submitted values are not echoed back"

    not_json = await client.post(
        "/v1/sync/push",
        content=b"{not json",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert not_json.status_code == 422

    duplicate = answer_op(Q1, "a")
    response = await push(client, tokens["student_a"], [duplicate, duplicate])
    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "duplicate_op_id_in_batch",
    )
    assert await counts(admin, STUDENT_A) == {
        "attempts": 0,
        "receipts": 0,
        "changes": 0,
        "progress": 0,
        "version": 0,
    }


async def test_batch_and_body_size_limits(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    headers = bearer(tokens["student_a"])
    fifty = [answer_op(SEED_QUESTIONS_FR[n % 5][0], "a") for n in range(50)]
    ok = await push(client, tokens["student_a"], fifty)
    assert ok.status_code == 200 and len(ok.json()["results"]) == 50
    assert len(json.dumps({"ops": fifty}).encode()) < 20 * 1024, (
        "a full batch fits the 20 KB budget uncompressed"
    )

    fifty_one = [answer_op(Q1, "a") for _ in range(51)]
    too_many = await push(client, tokens["student_a"], fifty_one)
    assert (too_many.status_code, too_many.json()["error"]["code"]) == (413, "batch_too_large")

    huge = json.dumps({"ops": [answer_op(Q1, "a")], "pad": "x" * 30_000}).encode()
    too_big = await client.post(
        "/v1/sync/push", content=huge, headers={**headers, "Content-Type": "application/json"}
    )
    assert (too_big.status_code, too_big.json()["error"]["code"]) == (413, "payload_too_large")
    assert too_big.json()["error"]["request_id"] == too_big.headers["x-request-id"]

    assert (await counts(admin, STUDENT_A))["attempts"] == 50, "rejected requests applied nothing"


async def test_gzip_bodies_and_decompression_bombs(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    headers = {
        **bearer(tokens["student_a"]),
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
    }
    body = gzip.compress(json.dumps({"ops": [answer_op(Q1, Q1_CORRECT)]}).encode())
    accepted = await client.post("/v1/sync/push", content=body, headers=headers)
    assert accepted.status_code == 200 and accepted.json()["results"][0]["status"] == "accepted"

    bomb = gzip.compress(b'{"ops": [], "pad": "' + b"a" * 5_000_000 + b'"}')
    assert len(bomb) < 20 * 1024, "the bomb is tiny on the wire"
    exploded = await client.post("/v1/sync/push", content=bomb, headers=headers)
    assert (exploded.status_code, exploded.json()["error"]["code"]) == (413, "payload_too_large")

    broken = await client.post(
        "/v1/sync/push", content=b"\x1f\x8b not really gzip", headers=headers
    )
    assert broken.status_code == 400
    other = await client.post(
        "/v1/sync/push", content=b"{}", headers={**headers, "Content-Encoding": "br"}
    )
    assert other.status_code == 415
    assert (await counts(admin, STUDENT_A))["attempts"] == 1


async def test_mixed_batch_reports_every_operation(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    numeric = await publish_new_lesson(admin, questions=(("numeric", "b"),))
    ops = [
        answer_op(Q1, Q1_CORRECT),  # fine
        {"op_id": str(uuid.uuid4()), "kind": "award_points", "payload": {"points": 1000}},
        {
            "op_id": str(uuid.uuid4()),
            "kind": "practice_answer",
            "payload": {"question_revision_id": str(Q1), "response": {"text": "7"}},
        },  # unsupported answer type
        answer_op(uuid.uuid4(), "a"),  # unknown question
        completed_op(uuid.uuid4()),  # unknown lesson revision
        answer_op(Q1, "zzz"),  # choice not offered
        answer_op(numeric["question_ids"][0], "b"),  # published, but not multiple choice
        completed_op(SEED_REV_HT),  # fine
    ]
    response = await push(client, tokens["student_a"], ops)
    assert response.status_code == 200
    results = response.json()["results"]
    assert [(r["status"], r["code"]) for r in results] == [
        ("accepted", None),
        ("rejected", "unsupported_kind"),
        ("rejected", "invalid_payload"),
        ("rejected", "content_not_available"),
        ("rejected", "content_not_available"),
        ("rejected", "invalid_choice"),
        ("rejected", "unsupported_question_kind"),
        ("accepted", None),
    ]
    assert [r["op_id"] for r in results] == [op["op_id"] for op in ops], "nothing silently dropped"
    # only real work advanced the version; content rejections are durable receipts
    assert await counts(admin, STUDENT_A) == {
        "attempts": 1,
        "receipts": 6,
        "changes": 2,
        "progress": 1,
        "version": 2,
    }
    retry = (await push(client, tokens["student_a"], ops)).json()["results"]
    assert [(r["status"], r["code"]) for r in retry] == [(r["status"], r["code"]) for r in results]
    assert [r["replayed"] for r in retry] == [True, False, False, True, True, True, True, True]
    assert (await counts(admin, STUDENT_A))["version"] == 2
