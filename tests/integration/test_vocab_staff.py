"""Word of the Day — the staff workflow over HTTP (/v1/staff/vocab).

Real tokens from the local Auth server, the real ``edu_staff_login`` pool, and
no direct SQL for any ACTION: the admin connection is used only to create
synthetic staff accounts (fixture) and to READ audit rows and states.
"""

# ruff: noqa: F811  (fixtures imported from tests.staff_fixtures are requested by name)
from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.main import create_app
from edu_api.routers import staff_vocab
from tests import vocab_fixtures
from tests.helpers import STUDENT_A, STUDENT_B, bearer
from tests.staff_fixtures import (  # noqa: F401  (fixtures are used by name)
    MakeStaff,
    build_staff_settings,
    dispose_app,
    make_staff,
    reset_denial_windows,
    staff_app,
    staff_client,
    staff_settings,
    staff_tokens,
)

clean_vocab = vocab_fixtures.clean_vocab

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_vocab")]

BASE = "/v1/staff/vocab"
NOBODY = str(uuid.UUID(int=0))
ANY = frozenset({"editor", "reviewer", "publisher", "admin"})
WRITE = frozenset({"editor", "admin"})
PUBLISH = frozenset({"publisher", "admin"})
CONTENT = {
    "term": "mot",
    "part_of_speech": "noun",
    "definition": "Définition synthétique.",
    "example": "Exemple synthétique.",
    "source_id": NOBODY,
}
AUDIO = {
    "object_key": "vocab/test/http.m4a",
    "byte_size": 2048,
    "sha256": "ab" * 32,
    "mime_type": "audio/mp4",
    "duration_ms": 900,
    "source_id": NOBODY,
}
#: THE ROUTE TABLE: method, template, a well-formed request, roles that may call it.
#: test_route_table_is_complete fails when a route exists that is not listed here.
ROUTES: list[tuple[str, str, dict[str, Any], frozenset[str]]] = [
    ("POST", "/sources", {"json": {"source_title": "Synthetic", "licence": "synthetic-test-only"}},
     frozenset({"editor", "publisher", "admin"})),
    ("PUT", "/sources/{source_id}/rights", {"json": {"rights_status": "cleared"}}, PUBLISH),
    ("POST", "/words", {"json": {"slug": "http-matrix-word"}}, WRITE),
    ("POST", "/words/{word_id}/revisions", {"json": {**CONTENT, "locale": "fr"}}, WRITE),
    ("PUT", "/revisions/{revision_id}", {"json": CONTENT}, WRITE),
    ("PUT", "/revisions/{revision_id}/audio", {"json": AUDIO}, WRITE),
    ("DELETE", "/revisions/{revision_id}/audio", {}, WRITE),
    ("POST", "/revisions/{revision_id}/submit", {}, WRITE),
    ("POST", "/revisions/{revision_id}/review", {"json": {"verdict": "approved"}},
     frozenset({"reviewer", "admin"})),
    ("GET", "/review-queue", {}, ANY),
    ("PUT", "/schedule/{haiti_date}", {"json": {"word_id": NOBODY}}, PUBLISH),
    ("DELETE", "/schedule/{haiti_date}", {}, PUBLISH),
    ("GET", "/calendar", {"params": {"from_date": "2030-01-01", "days": 7}}, ANY),
    ("POST", "/schedule/ensure", {"json": {"from_date": "2030-01-01", "days": 3}}, PUBLISH),
    ("POST", "/words/{word_id}/retire", {}, PUBLISH),
]  # fmt: skip
ROUTE_IDS = [f"{method} {template}" for method, template, _, _ in ROUTES]


def url(template: str) -> str:
    return BASE + re.sub(r"\{haiti_date\}", "2030-01-02", re.sub(r"\{\w+_id\}", NOBODY, template))


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code, response.text
    assert set(error) <= {"code", "message", "request_id", "details"}


async def audit(
    admin: asyncpg.Pool, actor: uuid.UUID, prefix: str = "vocab."
) -> list[dict[str, Any]]:
    rows = await admin.fetch(
        "SELECT actor_kind, action, target_kind, target_id, outcome, details FROM app.audit_events "
        "WHERE actor_id = $1 AND action LIKE $2 ORDER BY created_at, id",
        actor,
        prefix + "%",
    )
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


async def call(
    http: httpx.AsyncClient, token: str, method: str, path: str, **kw: Any
) -> httpx.Response:
    return await http.request(method, BASE + path, headers=bearer(token), **kw)


async def ok(
    http: httpx.AsyncClient, token: str, method: str, path: str, **kw: Any
) -> dict[str, Any]:
    response = await call(http, token, method, path, **kw)
    assert response.status_code == 200, (method, path, response.text)
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
async def full_client(local_env: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    """The API with BOTH the staff side and the learner flag switched on."""
    application: FastAPI = create_app(build_staff_settings(local_env, daily_word_enabled=True))
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http
    await dispose_app(application)
    await application.state.token_verifier._keys.aclose()


# ------------------------------------------------------------------ the route table
def test_route_table_is_complete() -> None:
    registered = {
        (method, route.path.removeprefix(BASE))  # type: ignore[attr-defined]
        for route in staff_vocab.router.routes
        for method in route.methods  # type: ignore[attr-defined]
    }
    assert registered == {(method, template) for method, template, _, _ in ROUTES}
    assert all(not route.include_in_schema for route in staff_vocab.router.routes)  # type: ignore[attr-defined]


# ------------------------------------------------------------------ learners are refused
@pytest.mark.parametrize(("method", "template", "request_kw", "_roles"), ROUTES, ids=ROUTE_IDS)
async def test_learner_token_is_refused_on_every_staff_vocab_route(
    staff_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    method: str,
    template: str,
    request_kw: dict[str, Any],
    _roles: frozenset[str],
) -> None:
    before = await admin.fetchval("SELECT count(*) FROM vocab.words") + await admin.fetchval(
        "SELECT count(*) FROM vocab.sources"
    )
    started = await admin.fetchval("SELECT clock_timestamp()")
    await reset_denial_windows(admin)
    # no token -> 401, whatever the body
    assert_error(
        await staff_client.request(method, url(template), **request_kw), 401, "unauthenticated"
    )
    for learner in ("student_a", "student_b"):
        response = await staff_client.request(
            method, url(template), headers=bearer(tokens[learner]), **request_kw
        )
        assert_error(response, 403, "forbidden")
        # even a malformed request does not get past the role gate
        malformed = await staff_client.request(
            method, url(template), headers=bearer(tokens[learner]), json={"unexpected": True}
        )
        assert malformed.status_code == 403, malformed.text
    # Refusals are audited (persisted rows are bounded per actor per minute: at least one each).
    denied = await admin.fetch(
        "SELECT actor_id, details FROM app.audit_events WHERE action = 'staff.access' "
        "AND outcome = 'denied' AND created_at >= $1",
        started,
    )
    assert {row["actor_id"] for row in denied} == {STUDENT_A, STUDENT_B}
    for row in denied:  # the template, never the raw URL
        assert json.loads(row["details"])["route"] == BASE + template
    after = await admin.fetchval("SELECT count(*) FROM vocab.words") + await admin.fetchval(
        "SELECT count(*) FROM vocab.sources"
    )
    assert after == before
    # Staff side not configured (the default app): nothing is reachable at all.
    off = await client.request(
        method, url(template), headers=bearer(tokens["editor"]), **request_kw
    )
    assert_error(off, 503, "staff_unavailable")


# ------------------------------------------------------------------ role matrix
async def test_role_matrix_editor_reviewer_publisher_admin(
    staff_client: httpx.AsyncClient, staff_tokens: dict[str, str], make_staff: MakeStaff
) -> None:
    role_tokens = {
        "editor": staff_tokens["editor"],
        "reviewer": staff_tokens["reviewer"],
        "publisher": (await make_staff("publisher")).token,
        "admin": (await make_staff("admin")).token,
    }
    outcomes: dict[str, dict[str, int]] = {}
    for method, template, request_kw, allowed in ROUTES:
        row = outcomes.setdefault(f"{method} {template}", {})
        for role, token in role_tokens.items():
            kw = dict(request_kw)
            if template == "/words":  # a fresh slug per caller, so "allowed" is visible as 200
                kw = {"json": {"slug": f"http-matrix-{role}"}}
            response = await staff_client.request(
                method, url(template), headers=bearer(token), **kw
            )
            row[role] = response.status_code
            if role in allowed:
                assert response.status_code != 403, (method, template, role, response.text)
                assert response.status_code in (200, 404, 409), (
                    method,
                    template,
                    role,
                    response.text,
                )
            else:
                assert_error(response, 403, "forbidden")
    # Spot checks that "allowed" really reached the database function.
    assert outcomes["POST /words"] == {
        "editor": 200,
        "reviewer": 403,
        "publisher": 403,
        "admin": 200,
    }
    assert outcomes["GET /review-queue"] == dict.fromkeys(role_tokens, 200)
    assert outcomes["POST /schedule/ensure"] == {
        "editor": 403,
        "reviewer": 403,
        "publisher": 200,
        "admin": 200,
    }
    assert outcomes["POST /revisions/{revision_id}/review"] == {
        "editor": 403, "reviewer": 404, "publisher": 403, "admin": 404,
    }  # fmt: skip


async def test_deactivated_role_is_refused(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, admin: asyncpg.Pool
) -> None:
    from tests.staff_fixtures import set_role_active

    publisher = await make_staff("publisher")
    assert (await call(staff_client, publisher.token, "GET", "/review-queue")).status_code == 200
    await set_role_active(admin, publisher.user_id, "publisher", False)
    assert_error(
        await call(staff_client, publisher.token, "GET", "/review-queue"), 403, "forbidden"
    )
    assert_error(
        await call(staff_client, publisher.token, "POST", "/schedule/ensure",
                   json={"from_date": "2030-01-01", "days": 3}),
        403, "forbidden",
    )  # fmt: skip


# ------------------------------------------------------------------ reviewer != author
async def test_author_cannot_review_own_word_over_http(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, admin: asyncpg.Pool
) -> None:
    both = await make_staff("editor", "reviewer")  # one person holding BOTH roles
    publisher = await make_staff("publisher")
    source = (await ok(staff_client, both.token, "POST", "/sources",
                       json={"source_title": "Synthetic test source", "licence": "synthetic-test-only"}))["id"]  # fmt: skip
    await ok(
        staff_client,
        publisher.token,
        "PUT",
        f"/sources/{source}/rights",
        json={"rights_status": "cleared"},
    )
    word = (await ok(staff_client, both.token, "POST", "/words", json={"slug": "http-own-word"}))[
        "id"
    ]
    revision = (await ok(staff_client, both.token, "POST", f"/words/{word}/revisions",
                         json={**CONTENT, "locale": "fr", "source_id": source}))["id"]  # fmt: skip
    await ok(staff_client, both.token, "POST", f"/revisions/{revision}/submit")

    for verdict in ("approved", "rejected"):
        refused = await call(
            staff_client,
            both.token,
            "POST",
            f"/revisions/{revision}/review",
            json={"verdict": verdict},
        )
        assert_error(refused, 409, "vocab_rule_violation")
        assert refused.json()["error"]["message"] == "Author cannot review own word"
    assert (
        await admin.fetchval(
            "SELECT status FROM vocab.word_revisions WHERE id = $1", uuid.UUID(revision)
        )
        == "in_review"
    )
    assert await admin.fetchval("SELECT count(*) FROM vocab.reviews") == 0
    assert not [
        e for e in await audit(admin, both.user_id) if e["action"] == "vocab.revision.review"
    ]


# ------------------------------------------------------------------ the whole journey
async def test_http_journey_draft_review_schedule_learner_reads_it(
    full_client: httpx.AsyncClient,
    staff_tokens: dict[str, str],
    tokens: dict[str, str],
    make_staff: MakeStaff,
    admin: asyncpg.Pool,
) -> None:
    http = full_client
    editor, reviewer = staff_tokens["editor"], staff_tokens["reviewer"]
    publisher = await make_staff("publisher")
    learner = bearer(tokens["student_a"])
    started = await admin.fetchval("SELECT clock_timestamp()")
    await reset_denial_windows(admin)

    # Nothing yet for the learner.
    assert (
        await http.get("/v1/daily-word", params={"locale": "fr"}, headers=learner)
    ).status_code == 404

    # 1. editor: source, word, French + Creole drafts, recording metadata, edit, submit
    source = (await ok(http, editor, "POST", "/sources",
                       json={"source_title": "Synthetic journey source", "licence": "synthetic-test-only"}))["id"]  # fmt: skip
    word = (await ok(http, editor, "POST", "/words", json={"slug": "http-journey"}))["id"]
    fr = (await ok(http, editor, "POST", f"/words/{word}/revisions",
                   json={**CONTENT, "locale": "fr", "term": "VOYAGE", "source_id": source}))["id"]  # fmt: skip
    ht = (await ok(http, editor, "POST", f"/words/{word}/revisions",
                   json={**CONTENT, "locale": "ht", "term": "VWAYAJ", "gloss": "voyage", "source_id": source}))["id"]  # fmt: skip
    await ok(http, editor, "PUT", f"/revisions/{fr}",
             json={**CONTENT, "term": "VOYAGE", "pronunciation": "vwa-yaj", "source_id": source})  # fmt: skip
    audio = (
        await ok(http, editor, "PUT", f"/revisions/{fr}/audio", json={**AUDIO, "source_id": source})
    )["id"]
    await ok(http, editor, "POST", f"/revisions/{fr}/submit")
    await ok(http, editor, "POST", f"/revisions/{ht}/submit")
    # frozen after submission
    frozen = await call(
        http,
        editor,
        "PUT",
        f"/revisions/{fr}",
        json={**CONTENT, "term": "APRES", "source_id": source},
    )
    assert_error(frozen, 409, "vocab_rule_violation")

    # 2. the queue; the editor cannot review; rights gate; a different person approves
    queue = (await ok(http, reviewer, "GET", "/review-queue"))["items"]
    assert {item["word_revision_id"] for item in queue} == {fr, ht}
    assert {item["source_rights_status"] for item in queue} == {"unverified"}
    assert_error(
        await call(http, editor, "POST", f"/revisions/{fr}/review", json={"verdict": "approved"}),
        403,
        "forbidden",
    )
    gate = await call(
        http, reviewer, "POST", f"/revisions/{fr}/review", json={"verdict": "approved"}
    )
    assert_error(gate, 409, "vocab_rule_violation")
    assert gate.json()["error"]["message"] == "Approval requires a rights-cleared source record"
    assert_error(
        await call(
            http, editor, "PUT", f"/sources/{source}/rights", json={"rights_status": "cleared"}
        ),
        403,
        "forbidden",
    )
    await ok(
        http, publisher.token, "PUT", f"/sources/{source}/rights", json={"rights_status": "cleared"}
    )
    await ok(
        http,
        reviewer,
        "POST",
        f"/revisions/{fr}/review",
        json={"verdict": "approved", "notes": "Note de test."},
    )
    await ok(http, reviewer, "POST", f"/revisions/{ht}/review", json={"verdict": "approved"})
    assert (await ok(http, reviewer, "GET", "/review-queue"))["items"] == []

    # Approved, but not scheduled: still nothing for the learner.
    assert (
        await http.get("/v1/daily-word", params={"locale": "fr"}, headers=learner)
    ).status_code == 404

    # 3. publisher: the fill records today (it never back-fills, so the first created date IS today)
    utc_today = datetime.now(UTC).date()
    assert_error(await call(http, editor, "POST", "/schedule/ensure",
                            json={"from_date": str(utc_today - timedelta(days=2)), "days": 4}), 403, "forbidden")  # fmt: skip
    created = (await ok(http, publisher.token, "POST", "/schedule/ensure",
                        json={"from_date": str(utc_today - timedelta(days=2)), "days": 4}))["created"]  # fmt: skip
    today = date.fromisoformat(min(item["haiti_date"] for item in created))
    assert {(item["locale"], item["word_revision_id"]) for item in created if item["haiti_date"] == str(today)} == {
        ("fr", fr), ("ht", ht),
    }  # fmt: skip
    again = (await ok(http, publisher.token, "POST", "/schedule/ensure",
                      json={"from_date": str(today), "days": 3}))["created"]  # fmt: skip
    assert again == [] or all(item["haiti_date"] > str(today) for item in again)

    # 4. the learner reads it — both languages, with the recording metadata
    french = await http.get("/v1/daily-word", params={"locale": "fr"}, headers=learner)
    assert french.status_code == 200, french.text
    body = french.json()
    assert (body["haiti_date"], body["word"]["term"], body["word"]["revision_id"]) == (
        str(today),
        "VOYAGE",
        fr,
    )
    assert body["word"]["pronunciation"] == "vwa-yaj" and body["audio"]["asset_id"] == audio
    creole = (await http.get("/v1/daily-word", params={"locale": "ht"}, headers=learner)).json()
    assert (creole["word"]["term"], creole["is_fallback_locale"], creole["word"]["gloss"]) == (
        "VWAYAJ",
        False,
        "voyage",
    )

    # 5. today is locked for everyone; a future date can be scheduled, rescheduled and cleared
    locked = await call(http, publisher.token, "PUT", f"/schedule/{today}", json={"word_id": word})
    assert_error(locked, 409, "vocab_rule_violation")
    assert_error(
        await call(http, publisher.token, "DELETE", f"/schedule/{today}"),
        409,
        "vocab_rule_violation",
    )
    future = today + timedelta(days=5)
    await ok(http, publisher.token, "DELETE", f"/schedule/{future}")
    assert (await ok(http, publisher.token, "PUT", f"/schedule/{future}", json={"word_id": word}))[
        "rows"
    ] == 2
    assert_error(
        await call(http, reviewer, "PUT", f"/schedule/{future}", json={"word_id": word}),
        403,
        "forbidden",
    )
    calendar = (
        await ok(http, reviewer, "GET", "/calendar", params={"from_date": str(today), "days": 6})
    )["items"]
    by_day = {(item["haiti_date"], item["locale"]): item for item in calendar}
    assert (
        by_day[(str(today), "fr")]["is_locked"] is True
        and by_day[(str(today), "fr")]["assigned_via"] == "auto"
    )
    assert by_day[(str(future), "fr")]["is_locked"] is False
    assert by_day[(str(future), "fr")]["assigned_via"] == "staff"
    assert by_day[(str(future), "fr")]["assigned_by"] == str(publisher.user_id)
    assert (await ok(http, publisher.token, "DELETE", f"/schedule/{future}"))["rows"] == 2
    # retiring later does not change today
    await ok(http, publisher.token, "POST", f"/words/{word}/retire")
    assert (
        await http.get("/v1/daily-word", params={"locale": "fr"}, headers=learner)
    ).content == french.content

    # 6. every action was audited, by the right person, on the staff channel, with codes and ids only
    rows = await admin.fetch(
        "SELECT actor_id, actor_kind, action, outcome, target_kind, details FROM app.audit_events "
        "WHERE action LIKE 'vocab.%' AND created_at >= $1 ORDER BY created_at, id",
        started,
    )
    allowed = [(str(r["actor_id"]), r["action"]) for r in rows if r["outcome"] == "allowed"]
    e, r_, p = (
        "a0000000-0000-4000-8000-000000000003",
        "a0000000-0000-4000-8000-000000000004",
        str(publisher.user_id),
    )
    assert allowed == [
        (e, "vocab.source.register"), (e, "vocab.word.create"), (e, "vocab.revision.create"),
        (e, "vocab.revision.create"), (e, "vocab.revision.update"), (e, "vocab.audio.set"),
        (e, "vocab.revision.submit"), (e, "vocab.revision.submit"), (p, "vocab.source.rights"),
        (r_, "vocab.revision.review"), (r_, "vocab.revision.review"), (p, "vocab.schedule.ensure"),
        (p, "vocab.schedule.ensure"), (p, "vocab.schedule.clear"), (p, "vocab.schedule.set"),
        (p, "vocab.schedule.clear"), (p, "vocab.word.retire"),
    ]  # fmt: skip
    assert {r["actor_kind"] for r in rows} == {"staff"}
    machine_value = re.compile(r"^[A-Za-z0-9_.:/{}+-]{0,120}$")
    for row in rows:
        for value in json.loads(row["details"]).values():
            assert (
                isinstance(value, bool | int | float) or value is None or machine_value.match(value)
            ), row
        for text_typed_by_a_person in (
            "VOYAGE",
            "VWAYAJ",
            "vwa-yaj",
            "Synthetic",
            "Note",
            "Définition",
        ):
            assert text_typed_by_a_person not in row["details"]
    # refused steps left 'denied' rows written by the HTTP layer, none 'allowed'
    denied = await admin.fetch(
        "SELECT action FROM app.audit_events WHERE outcome = 'denied' AND created_at >= $1 AND actor_id = $2",
        started, uuid.UUID(e),
    )  # fmt: skip
    assert denied and {d["action"] for d in denied} == {"staff.access"}


# ------------------------------------------------------------------ errors and limits
async def test_error_mapping_and_limits(
    staff_client: httpx.AsyncClient,
    staff_tokens: dict[str, str],
    make_staff: MakeStaff,
    admin: asyncpg.Pool,
) -> None:
    editor = staff_tokens["editor"]
    other_editor = await make_staff("editor")
    await reset_denial_windows(admin)
    source = (await ok(staff_client, editor, "POST", "/sources",
                       json={"source_title": "Synthetic limits source", "licence": "synthetic-test-only"}))["id"]  # fmt: skip
    word = (await ok(staff_client, editor, "POST", "/words", json={"slug": "http-limits"}))["id"]
    assert_error(
        await call(staff_client, editor, "POST", "/words", json={"slug": "http-limits"}),
        409,
        "vocab_conflict",
    )
    for bad in ({"slug": "Bad Slug"}, {"slug": "ok-slug", "extra": 1}, {}):
        assert_error(
            await call(staff_client, editor, "POST", "/words", json=bad), 422, "validation_error"
        )
    base = {**CONTENT, "locale": "fr", "source_id": source}
    for bad_content in ({"term": "x" * 61}, {"definition": ""}, {"part_of_speech": "gerund"}, {"locale": "en"},
                        {"created_by": NOBODY}, {"status": "approved"}):  # fmt: skip
        response = await call(
            staff_client, editor, "POST", f"/words/{word}/revisions", json={**base, **bad_content}
        )
        assert_error(response, 422, "validation_error")
        assert "x" * 61 not in response.text  # validation errors never echo the value
    # Each field within its limit, but the whole payload over the byte budget: the DATABASE refuses.
    budget = await call(staff_client, editor, "POST", f"/words/{word}/revisions",
                        json={**base, "definition": "é" * 300, "example": "é" * 240})  # fmt: skip
    assert_error(budget, 422, "vocab_invalid_content")
    assert budget.json()["error"]["details"] == [{"constraint": "word_revisions_payload_budget"}]
    multiline = await call(
        staff_client,
        editor,
        "POST",
        f"/words/{word}/revisions",
        json={**base, "definition": "a\nb"},
    )
    assert_error(multiline, 422, "vocab_invalid_content")
    assert_error(
        await call(staff_client, editor, "POST", f"/words/{NOBODY}/revisions", json=base),
        404,
        "vocab_not_found",
    )
    assert_error(await call(staff_client, editor, "POST", f"/words/{word}/revisions", json={**base, "source_id": NOBODY}),
                 404, "vocab_not_found")  # fmt: skip
    assert_error(
        await call(staff_client, editor, "POST", "/revisions/not-a-uuid/submit"),
        422,
        "validation_error",
    )
    assert await admin.fetchval("SELECT count(*) FROM vocab.word_revisions") == 0

    revision = (await ok(staff_client, editor, "POST", f"/words/{word}/revisions", json=base))["id"]
    # AUDIO SIZE CAP over HTTP
    for bad_audio in ({"byte_size": 102_401}, {"byte_size": 0}, {"mime_type": "audio/wav"}, {"sha256": "zz"},
                      {"duration_ms": 15_001}, {"object_key": "../etc/passwd"}, {"autoplay": True}):  # fmt: skip
        response = await call(staff_client, editor, "PUT", f"/revisions/{revision}/audio",
                              json={**AUDIO, "source_id": source, **bad_audio})  # fmt: skip
        assert_error(response, 422, "validation_error")
    assert await admin.fetchval("SELECT count(*) FROM vocab.audio_assets") == 0

    # Another editor cannot touch this draft: refused by the DATABASE, audited by the HTTP layer.
    for method, path, kw in (
        (
            "PUT",
            f"/revisions/{revision}",
            {"json": {**CONTENT, "term": "pris", "source_id": source}},
        ),
        ("POST", f"/revisions/{revision}/submit", {}),
        ("PUT", f"/revisions/{revision}/audio", {"json": {**AUDIO, "source_id": source}}),
    ):
        assert_error(
            await call(staff_client, other_editor.token, method, path, **kw), 403, "forbidden"
        )
    denied = await audit(admin, other_editor.user_id, "staff.access")
    assert denied, "a refusal by the database function is audited by the HTTP layer"
    assert (denied[0]["outcome"], denied[0]["actor_kind"], denied[0]["details"]["check"]) == (
        "denied",
        "staff",
        "function",
    )
    assert denied[0]["details"]["route"] == BASE + "/revisions/{revision_id}"
    assert denied[0]["details"]["held_roles"] == ["editor"]
    assert (
        await admin.fetchval(
            "SELECT term FROM vocab.word_revisions WHERE id = $1", uuid.UUID(revision)
        )
        == "mot"
    )
    assert not [a for a in await audit(admin, other_editor.user_id) if a["outcome"] == "allowed"]

    # query validation on the calendar
    for params in ({}, {"from_date": "tomorrow"}, {"from_date": "2030-01-01", "days": 93}):
        assert_error(
            await call(staff_client, editor, "GET", "/calendar", params=params),
            422,
            "validation_error",
        )
