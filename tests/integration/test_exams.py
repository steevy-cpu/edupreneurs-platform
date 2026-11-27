"""ExamHub-01 over HTTP: catalog -> attempt -> answers -> server scoring -> explanation -> history.

Synthetic exams only, created through the real publication guards. The properties that matter:
the answer key never reaches the client before it may, a learner only ever sees their own
attempts, the score comes from the server, and a timed attempt ends on the server's clock.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import httpx
import pytest

from tests.helpers import EDITOR, REVIEWER, bearer

pytestmark = pytest.mark.integration

# Values that only the key or the explanation contain (a null `answer_key` FIELD is not a leak).
SECRETS = ("SECRET-EXPLANATION", "SECRET-MODEL-ANSWER", "correct_choice_id", "model_answer")
CHOICES = '{"choices": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}]}'


@pytest.fixture(autouse=True)
async def clean_exam_state(admin: asyncpg.Pool) -> None:
    await admin.execute(
        "TRUNCATE app.exam_answers, app.exam_attempts, app.exam_questions, app.exams CASCADE"
    )


async def create_exam(
    admin: asyncpg.Pool, *, publish: bool = True, with_ht: bool = True, duration: int = 30
) -> dict[str, Any]:
    """A synthetic exam: two multiple-choice questions (1 and 2 points) and one open question in
    French, one multiple-choice question in Creole. Published through the real guards."""
    exam_id, tag = uuid.uuid4(), uuid.uuid4().hex[:10]
    source_id = await admin.fetchval(
        "INSERT INTO app.content_sources (source_title, rights_status) VALUES ($1, 'cleared') RETURNING id",
        f"Synthetic exam source {tag}",
    )
    await admin.execute(
        """
        INSERT INTO app.exams (id, slug, grade_id, subject_id, series, exam_type, session_year,
                               duration_minutes, titles, source_id, created_by)
        VALUES ($1, $2, (SELECT id FROM app.grades ORDER BY sort_order LIMIT 1),
                (SELECT id FROM app.subjects ORDER BY slug LIMIT 1), 'SMP', 'model', 2026, $3,
                '{"fr": "Examen synthétique", "ht": "Egzamen sentetik"}', $4, $5)
        """,
        exam_id,
        f"synthetic-exam-{tag}",
        duration,
        source_id,
        EDITOR,
    )
    rows = [
        ("fr", 1, "mcq", 1, '{"text": "2 + 2 = ?"}', CHOICES, '{"correct_choice_id": "b"}', "SECRET-EXPLANATION-1"),
        ("fr", 2, "mcq", 2, '{"text": "1 + 2 = ?"}', CHOICES, '{"correct_choice_id": "a"}', "SECRET-EXPLANATION-2"),
        ("fr", 3, "open", 0, '{"text": "Explique."}', '{"max_chars": 4000}',
         '{"model_answer": "SECRET-MODEL-ANSWER"}', "SECRET-EXPLANATION-3"),
    ]  # fmt: skip
    if with_ht:
        rows.append(("ht", 1, "mcq", 1, '{"text": "2 + 2 = ?"}', CHOICES, '{"correct_choice_id": "b"}', "SECRET-EXPLANATION-HT"))  # fmt: skip
    questions: dict[tuple[str, int], uuid.UUID] = {}
    for locale, position, kind, points, prompt, spec, key, explanation in rows:
        questions[(locale, position)] = await admin.fetchval(
            """
            INSERT INTO app.exam_questions (exam_id, locale, position, kind, points, prompt,
                                            response_spec, answer_key, explanation)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb) RETURNING id
            """,
            exam_id, locale, position, kind, points, prompt, spec, key,
            json.dumps({"text": explanation}),
        )  # fmt: skip
    if publish:
        await admin.execute(
            "UPDATE app.exams SET status = 'published', approved_by = $2 WHERE id = $1",
            exam_id,
            REVIEWER,
        )
    return {"id": exam_id, "q": questions}


async def start(
    client: httpx.AsyncClient, token: str, exam_id: uuid.UUID, mode: str, locale: str = "fr"
) -> httpx.Response:
    return await client.post(
        f"/v1/exams/{exam_id}/attempts",
        json={"mode": mode, "locale": locale},
        headers=bearer(token),
    )


async def answer(
    client: httpx.AsyncClient,
    token: str,
    attempt_id: str,
    question_id: uuid.UUID,
    response: dict[str, Any],
) -> httpx.Response:
    return await client.post(
        f"/v1/exam-attempts/{attempt_id}/answers",
        json={"question_id": str(question_id), "response": response},
        headers=bearer(token),
    )


def assert_no_secret(response: httpx.Response) -> None:
    for secret in SECRETS:
        assert secret not in response.text, f"{secret!r} leaked in {response.request.url}"


# --- the flag ------------------------------------------------------------------------------
async def test_feature_is_off_by_default(
    client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    exam = await create_exam(admin)
    auth = bearer(tokens["student_a"])
    assert (await client.get("/v1/exams", params={"locale": "fr"}, headers=auth)).status_code == 404
    assert (
        await client.get(f"/v1/exams/{exam['id']}", params={"locale": "fr"}, headers=auth)
    ).status_code == 404
    assert (await start(client, tokens["student_a"], exam["id"], "practice")).status_code == 404
    assert (await client.get("/v1/exam-attempts", headers=auth)).status_code == 404
    assert await admin.fetchval("SELECT count(*) FROM app.exam_attempts") == 0


async def test_routes_need_a_token(exam_client: httpx.AsyncClient, admin: asyncpg.Pool) -> None:
    exam = await create_exam(admin)
    assert (await exam_client.get("/v1/exams", params={"locale": "fr"})).status_code == 401
    assert (
        await exam_client.post(f"/v1/exams/{exam['id']}/attempts", json={"mode": "practice"})
    ).status_code == 401
    assert (await exam_client.get("/v1/exam-attempts")).status_code == 401


# --- catalog ---------------------------------------------------------------------------------
async def test_catalog_lists_only_published_exams_in_the_language(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    published = await create_exam(admin)
    draft = await create_exam(admin, publish=False)
    french_only = await create_exam(admin, with_ht=False)
    auth = bearer(tokens["student_a"])

    fr = await exam_client.get("/v1/exams", params={"locale": "fr"}, headers=auth)
    assert fr.status_code == 200
    assert_no_secret(fr)
    ids = {e["id"] for e in fr.json()["exams"]}
    assert ids == {str(published["id"]), str(french_only["id"])}
    assert str(draft["id"]) not in ids
    entry = next(e for e in fr.json()["exams"] if e["id"] == str(published["id"]))
    assert (entry["question_count"], entry["max_points"], entry["duration_minutes"]) == (3, 3, 30)
    assert (entry["title"], entry["series"], entry["exam_type"]) == (
        "Examen synthétique",
        "SMP",
        "model",
    )

    ht = (await exam_client.get("/v1/exams", params={"locale": "ht"}, headers=auth)).json()
    assert [e["id"] for e in ht["exams"]] == [str(published["id"])]
    assert (ht["exams"][0]["title"], ht["exams"][0]["question_count"]) == ("Egzamen sentetik", 1)

    assert (
        await exam_client.get("/v1/exams", params={"locale": "fr", "series": "SES"}, headers=auth)
    ).json()["exams"] == []
    assert (
        await exam_client.get(
            "/v1/exams", params={"locale": "fr", "exam_type": "nonsense"}, headers=auth
        )
    ).status_code == 422

    assert (
        await exam_client.get(f"/v1/exams/{draft['id']}", params={"locale": "fr"}, headers=auth)
    ).status_code == 404
    assert (
        await exam_client.get(
            f"/v1/exams/{french_only['id']}", params={"locale": "ht"}, headers=auth
        )
    ).status_code == 404
    detail = await exam_client.get(
        f"/v1/exams/{published['id']}", params={"locale": "fr"}, headers=auth
    )
    assert detail.status_code == 200 and "questions" not in detail.json()


# --- practice -----------------------------------------------------------------------------------
async def test_practice_flow_scores_on_the_server_and_reveals_after_answering(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    exam = await create_exam(admin)
    token = tokens["student_a"]

    started = await start(exam_client, token, exam["id"], "practice")
    assert started.status_code == 200
    assert_no_secret(started)  # questions arrive without key or explanation
    body = started.json()
    attempt_id = body["attempt"]["id"]
    assert [q["position"] for q in body["questions"]] == [1, 2, 3]
    assert set(body["questions"][0]) == {
        "id",
        "position",
        "kind",
        "points",
        "prompt",
        "response_spec",
    }
    assert body["attempt"]["mode"] == "practice" and body["attempt"]["expires_at"] is None
    assert body["attempt"]["counts_as_exam_score"] is False and body["resumed"] is False

    right = await answer(exam_client, token, attempt_id, exam["q"][("fr", 1)], {"choice_id": "b"})
    assert right.status_code == 200
    assert right.json() == {
        "recorded": True,
        "feedback_available": True,
        "is_correct": True,
        "answer_key": {"correct_choice_id": "b"},
        "explanation": {"text": "SECRET-EXPLANATION-1"},
    }
    again = await answer(exam_client, token, attempt_id, exam["q"][("fr", 1)], {"choice_id": "a"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_answered"

    wrong = await answer(exam_client, token, attempt_id, exam["q"][("fr", 2)], {"choice_id": "b"})
    assert wrong.json()["is_correct"] is False and wrong.json()["answer_key"] == {
        "correct_choice_id": "a"
    }

    # While the attempt is open only the answered questions are revealed.
    open_detail = (
        await exam_client.get(f"/v1/exam-attempts/{attempt_id}", headers=bearer(token))
    ).json()
    assert [i["revealed"] for i in open_detail["items"]] == [True, True, False]
    assert (
        open_detail["items"][2]["answer_key"] is None
        and open_detail["items"][2]["explanation"] is None
    )

    essay = await answer(
        exam_client, token, attempt_id, exam["q"][("fr", 3)], {"text": "ma réponse"}
    )
    assert essay.status_code == 200 and essay.json()["is_correct"] is None
    assert essay.json()["answer_key"] == {"model_answer": "SECRET-MODEL-ANSWER"}

    finished = await exam_client.post(
        f"/v1/exam-attempts/{attempt_id}/finish", headers=bearer(token)
    )
    assert finished.status_code == 200
    result = finished.json()
    assert (
        result["attempt"]["status"],
        result["attempt"]["score_points"],
        result["attempt"]["max_points"],
    ) == ("finished", 1, 3)
    assert [i["points_awarded"] for i in result["items"]] == [1, 0, 0]
    assert all(i["revealed"] and i["explanation"] for i in result["items"])

    repeat = await exam_client.post(f"/v1/exam-attempts/{attempt_id}/finish", headers=bearer(token))
    assert repeat.json()["attempt"] == result["attempt"]  # idempotent
    late = await answer(exam_client, token, attempt_id, exam["q"][("fr", 1)], {"choice_id": "b"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "attempt_closed"

    history = (await exam_client.get("/v1/exam-attempts", headers=bearer(token))).json()["attempts"]
    assert [a["id"] for a in history] == [attempt_id] and history[0]["score_points"] == 1


async def test_invalid_answers_are_rejected(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    exam = await create_exam(admin)
    token = tokens["student_a"]
    attempt_id = (await start(exam_client, token, exam["id"], "practice")).json()["attempt"]["id"]
    q1 = exam["q"][("fr", 1)]
    for response in ({"choice_id": "zz"}, {"choice_id": 5}, {"text": "x"}, {}):
        bad = await answer(exam_client, token, attempt_id, q1, response)
        assert bad.status_code == 422, response
    assert (
        await answer(exam_client, token, attempt_id, exam["q"][("fr", 3)], {"text": ""})
    ).status_code == 422
    assert (
        await answer(exam_client, token, attempt_id, exam["q"][("fr", 3)], {"text": "x" * 4001})
    ).status_code == 422
    # A question of the Creole version, or an unknown one, is not part of this attempt.
    assert (
        await answer(exam_client, token, attempt_id, exam["q"][("ht", 1)], {"choice_id": "b"})
    ).status_code == 404
    assert (
        await answer(exam_client, token, attempt_id, uuid.uuid4(), {"choice_id": "b"})
    ).status_code == 404
    # The client cannot send a verdict, a score or a time.
    forged = await exam_client.post(
        f"/v1/exam-attempts/{attempt_id}/answers",
        json={
            "question_id": str(q1),
            "response": {"choice_id": "a"},
            "is_correct": True,
            "score": 100,
        },
        headers=bearer(token),
    )
    assert forged.status_code == 422
    assert (await start(exam_client, token, exam["id"], "graded")).status_code == 422
    assert await admin.fetchval("SELECT count(*) FROM app.exam_answers") == 0


# --- isolation -------------------------------------------------------------------------------------
async def test_a_learner_only_sees_their_own_attempts(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    exam = await create_exam(admin)
    a, b = tokens["student_a"], tokens["student_b"]
    attempt_id = (await start(exam_client, a, exam["id"], "practice")).json()["attempt"]["id"]
    await answer(exam_client, a, attempt_id, exam["q"][("fr", 1)], {"choice_id": "b"})

    assert (
        await exam_client.get(f"/v1/exam-attempts/{attempt_id}", headers=bearer(b))
    ).status_code == 404
    assert (
        await answer(exam_client, b, attempt_id, exam["q"][("fr", 2)], {"choice_id": "a"})
    ).status_code == 404
    assert (
        await exam_client.post(f"/v1/exam-attempts/{attempt_id}/finish", headers=bearer(b))
    ).status_code == 404
    assert (await exam_client.get("/v1/exam-attempts", headers=bearer(b))).json()["attempts"] == []
    # Nothing B did changed A's attempt.
    mine = (await exam_client.get(f"/v1/exam-attempts/{attempt_id}", headers=bearer(a))).json()
    assert (
        mine["attempt"]["status"] == "in_progress"
        and [i["response"] for i in mine["items"]][1] is None
    )


async def test_unpublished_or_missing_exams_cannot_be_started(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    draft = await create_exam(admin, publish=False)
    french_only = await create_exam(admin, with_ht=False)
    token = tokens["student_a"]
    assert (await start(exam_client, token, draft["id"], "practice")).status_code == 404
    assert (await start(exam_client, token, french_only["id"], "practice", "ht")).status_code == 404
    assert (await start(exam_client, token, uuid.uuid4(), "timed")).status_code == 404
    assert await admin.fetchval("SELECT count(*) FROM app.exam_attempts") == 0


# --- timed ---------------------------------------------------------------------------------------------
async def test_timed_attempt_reveals_nothing_until_finished_and_ends_on_the_server_clock(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    exam = await create_exam(admin, duration=30)
    token = tokens["student_a"]

    started = (await start(exam_client, token, exam["id"], "timed")).json()
    attempt_id = started["attempt"]["id"]
    assert (
        started["attempt"]["expires_at"] is not None
        and started["attempt"]["counts_as_exam_score"] is True
    )
    resumed = (await start(exam_client, token, exam["id"], "timed")).json()
    assert resumed["resumed"] is True and resumed["attempt"]["id"] == attempt_id
    assert await admin.fetchval("SELECT count(*) FROM app.exam_attempts") == 1

    first = await answer(exam_client, token, attempt_id, exam["q"][("fr", 1)], {"choice_id": "a"})
    assert first.json() == {
        "recorded": True, "feedback_available": False, "is_correct": None, "answer_key": None, "explanation": None,
    }  # fmt: skip
    assert_no_secret(first)
    changed = await answer(exam_client, token, attempt_id, exam["q"][("fr", 1)], {"choice_id": "b"})
    assert changed.status_code == 200  # a timed answer may be changed before finishing
    await answer(exam_client, token, attempt_id, exam["q"][("fr", 2)], {"choice_id": "a"})

    open_detail = await exam_client.get(f"/v1/exam-attempts/{attempt_id}", headers=bearer(token))
    assert_no_secret(open_detail)
    for item in open_detail.json()[
        "items"
    ]:  # no key, explanation, verdict or points while the clock runs
        assert (item["revealed"], item["answer_key"], item["explanation"], item["is_correct"], item["points_awarded"]) == (
            False, None, None, None, 0,
        )  # fmt: skip
    assert open_detail.json()["attempt"]["score_points"] is None

    # The server clock passes the deadline: question 1 was answered in time, question 2 too late.
    await admin.execute(
        "UPDATE app.exam_attempts SET started_at = now() - interval '40 minutes', "
        "expires_at = now() - interval '10 minutes' WHERE id = $1",
        uuid.UUID(attempt_id),
    )
    await admin.execute(
        "UPDATE app.exam_answers SET answered_at = now() - interval '20 minutes' "
        "WHERE attempt_id = $1 AND question_id = $2",
        uuid.UUID(attempt_id), exam["q"][("fr", 1)],
    )  # fmt: skip
    too_late = await answer(
        exam_client, token, attempt_id, exam["q"][("fr", 3)], {"text": "trop tard"}
    )
    assert too_late.status_code == 409 and too_late.json()["error"]["code"] == "attempt_expired"

    closed = (
        await exam_client.post(f"/v1/exam-attempts/{attempt_id}/finish", headers=bearer(token))
    ).json()
    assert (
        closed["attempt"]["status"],
        closed["attempt"]["score_points"],
        closed["attempt"]["max_points"],
    ) == ("expired", 1, 3)
    assert closed["attempt"]["finished_at"] == closed["attempt"]["expires_at"]
    assert all(i["revealed"] for i in closed["items"])
    assert closed["items"][2]["response"] is None  # the late answer was never stored

    fresh = (await start(exam_client, token, exam["id"], "timed")).json()
    assert fresh["resumed"] is False and fresh["attempt"]["id"] != attempt_id


async def test_finishing_an_expired_attempt_marks_it_expired(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    exam = await create_exam(admin)
    token = tokens["student_a"]
    attempt_id = (await start(exam_client, token, exam["id"], "timed")).json()["attempt"]["id"]
    await admin.execute(
        "UPDATE app.exam_attempts SET started_at = now() - interval '2 hours', "
        "expires_at = now() - interval '1 hour' WHERE id = $1",
        uuid.UUID(attempt_id),
    )
    result = (
        await exam_client.post(f"/v1/exam-attempts/{attempt_id}/finish", headers=bearer(token))
    ).json()
    assert (result["attempt"]["status"], result["attempt"]["score_points"]) == ("expired", 0)


async def test_creole_version(
    exam_client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    exam = await create_exam(admin)
    token = tokens["student_a"]
    started = (await start(exam_client, token, exam["id"], "practice", "ht")).json()
    assert started["attempt"]["locale"] == "ht" and len(started["questions"]) == 1
    ok = await answer(
        exam_client, token, started["attempt"]["id"], exam["q"][("ht", 1)], {"choice_id": "b"}
    )
    assert ok.json()["is_correct"] is True


# --- contract ------------------------------------------------------------------------------------------
def test_contract_question_schema_has_no_key(exam_app: Any) -> None:
    schemas = exam_app.openapi()["components"]["schemas"]
    assert set(schemas["ExamQuestion"]["properties"]) == {
        "id",
        "position",
        "kind",
        "points",
        "prompt",
        "response_spec",
    }
    assert set(schemas["SubmitAnswerRequest"]["properties"]) == {"question_id", "response"}
    assert schemas["SubmitAnswerRequest"]["additionalProperties"] is False
