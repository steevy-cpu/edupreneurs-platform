"""Learner-facing notification routes through the real API, real Auth tokens, real PostgreSQL."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import asyncpg
import httpx
from fastapi import FastAPI

from tests.helpers import EDITOR, STUDENT_A, STUDENT_B, bearer

if TYPE_CHECKING:
    from tests.notify_fixtures import Enqueue

pytest_plugins = ("tests.notify_fixtures",)

PREFS = "/v1/me/notification-preferences"
LIST = "/v1/notifications"
WORD = "f0000000-0000-4000-8000-000000000001"
DEFAULTS = {
    "push_enabled": False,
    "muted_categories": [],
    "quiet_hours": None,
    "platform_quiet_hours": {"start": "21:00", "end": "06:00"},
    "time_zone": "America/Port-au-Prince",
    "categories": ["account", "learning", "reminders"],
    "updated_at": None,
}


# ------------------------------------------------------------------ the flag
async def test_with_the_flag_off_the_routes_do_not_exist(
    client: httpx.AsyncClient, tokens: dict[str, str], app: FastAPI
) -> None:
    """Default settings: exactly today's API. Not mounted, not in the contract, no extra pool."""
    assert app.state.settings.notifications_enabled is False
    assert not hasattr(app.state, "notify_db")
    for method, path in (("GET", PREFS), ("PUT", PREFS), ("GET", LIST)):
        response = await client.request(method, path, headers=bearer(tokens["student_a"]), json={})
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"
    spec = (await client.get("/openapi.json")).json()
    assert not [path for path in spec["paths"] if "notification" in path]


async def test_contract_of_the_flagged_routes(notify_client: httpx.AsyncClient) -> None:
    spec = (await notify_client.get("/openapi.json")).json()
    added = {path: ops for path, ops in spec["paths"].items() if "notification" in path}
    assert {path: sorted(ops) for path, ops in added.items()} == {
        PREFS: ["get", "put"],
        LIST: ["get"],
    }
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, operations in added.items():
        for operation in operations.values():
            assert operation["security"] == [{"HTTPBearer": []}], path
            assert {"401", "503"} <= set(operation["responses"])
            for status, response in operation["responses"].items():
                if status != "200":
                    assert response["content"]["application/json"]["schema"] == error_ref
    assert "HTTPValidationError" not in spec["components"]["schemas"], "one error shape only"
    # There is no route that creates a notification.
    assert all(
        method in {"get", "put"} for operations in added.values() for method in operations
    ) and "post" not in spec["paths"].get(LIST, {})
    item = spec["components"]["schemas"]["NotificationItem"]["properties"]
    assert set(item) == {"id", "kind", "category", "refs", "available_at", "expires_at"}


async def test_routes_need_a_real_user_token(
    notify_client: httpx.AsyncClient, local_env: dict[str, str]
) -> None:
    for method, path in (("GET", PREFS), ("PUT", PREFS), ("GET", LIST)):
        for headers in ({}, bearer("not-a-token"), bearer(local_env["LOCAL_SUPABASE_SECRET_KEY"])):
            response = await notify_client.request(method, path, headers=headers, json={})
            assert response.status_code == 401, (method, path)
            assert response.json()["error"]["code"] == "unauthenticated"


# --------------------------------------------------------------- preferences
async def test_preferences_default_to_push_off_and_platform_quiet_hours(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    response = await notify_client.get(PREFS, headers=bearer(tokens["student_a"]))
    assert response.status_code == 200
    assert response.json() == DEFAULTS
    assert await admin.fetchval("SELECT count(*) FROM notify.preferences") == 0, (
        "GET writes nothing"
    )


async def test_put_replaces_only_the_callers_preferences(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    body = {
        "push_enabled": True,
        "muted_categories": ["reminders", "learning"],
        "quiet_hours": {"start": "20:00", "end": "07:30"},
    }
    saved = await notify_client.put(PREFS, headers=bearer(tokens["student_a"]), json=body)
    assert saved.status_code == 200, saved.text
    expected = {**DEFAULTS, **body, "muted_categories": ["learning", "reminders"]}
    payload = saved.json()
    assert payload.pop("updated_at") is not None
    assert payload == {key: value for key, value in expected.items() if key != "updated_at"}

    again = await notify_client.get(PREFS, headers=bearer(tokens["student_a"]))
    assert {**again.json(), "updated_at": None} == {**expected, "updated_at": None}
    # B is unaffected and cannot see A's choice.
    assert (await notify_client.get(PREFS, headers=bearer(tokens["student_b"]))).json() == DEFAULTS
    rows = await admin.fetch("SELECT learner_id, push_enabled FROM notify.preferences")
    assert [(row["learner_id"], row["push_enabled"]) for row in rows] == [(STUDENT_A, True)]

    # PUT is a full, repeatable replacement.
    reset = {"push_enabled": False, "muted_categories": [], "quiet_hours": None}
    for _ in range(2):
        response = await notify_client.put(PREFS, headers=bearer(tokens["student_a"]), json=reset)
        assert response.status_code == 200
    assert {**response.json(), "updated_at": None} == DEFAULTS
    assert await admin.fetchval("SELECT count(*) FROM notify.preferences") == 1


async def test_preferences_identity_cannot_be_chosen_and_input_is_validated(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    base = {"push_enabled": True, "muted_categories": [], "quiet_hours": None}
    bad_bodies = [
        {**base, "user_id": str(STUDENT_B)},
        {**base, "learner_id": str(STUDENT_B)},
        {**base, "push_enabled": "true"},
        {**base, "muted_categories": ["marketing"]},
        {**base, "quiet_hours": {"start": "21:00", "end": "21:00"}},
        {**base, "quiet_hours": {"start": "25:00", "end": "06:00"}},
        {**base, "platform_quiet_hours": {"start": "00:00", "end": "00:01"}},
        {"push_enabled": True},
        [],
    ]
    for body in bad_bodies:
        response = await notify_client.put(PREFS, headers=bearer(tokens["student_a"]), json=body)
        assert response.status_code == 422, body
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert "marketing" not in response.text and str(STUDENT_B) not in response.text
    assert await admin.fetchval("SELECT count(*) FROM notify.preferences") == 0
    assert await admin.fetchval("SELECT quiet_start::text FROM notify.policy") == "21:00:00"


async def test_an_account_without_a_profile_gets_one_on_first_save(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """Same rule as GET /v1/me: any signed-in account becomes a learner on first contact."""
    had_profile = await admin.fetchval(
        "SELECT EXISTS (SELECT 1 FROM app.learner_profiles WHERE user_id = $1)", EDITOR
    )
    assert (await notify_client.get(PREFS, headers=bearer(tokens["editor"]))).json() == DEFAULTS
    body = {"push_enabled": False, "muted_categories": ["account"], "quiet_hours": None}
    try:
        response = await notify_client.put(PREFS, headers=bearer(tokens["editor"]), json=body)
        assert response.status_code == 200, response.text
        assert response.json()["muted_categories"] == ["account"]
        assert await admin.fetchval(
            "SELECT EXISTS (SELECT 1 FROM app.learner_profiles WHERE user_id = $1)", EDITOR
        )
    finally:
        await admin.execute("DELETE FROM notify.preferences WHERE learner_id = $1", EDITOR)
        if not had_profile:  # leave the database as this test found it
            await admin.execute("DELETE FROM app.learner_profiles WHERE user_id = $1", EDITOR)


# ----------------------------------------------------------------- the list
async def test_list_is_own_rows_kind_and_ids_only(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], enqueue: Enqueue
) -> None:
    mine = await enqueue(STUDENT_A, "daily_word_available", json.dumps({"word_id": WORD}))
    await enqueue(STUDENT_B, "entitlement_expiring", json.dumps({"grant_id": str(uuid.uuid4())}))

    response = await notify_client.get(LIST, headers=bearer(tokens["student_a"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None
    (item,) = body["items"]
    assert set(item) == {"id", "kind", "category", "refs", "available_at", "expires_at"}
    assert (item["id"], item["kind"], item["category"], item["refs"], item["expires_at"]) == (
        str(mine),
        "daily_word_available",
        "learning",
        {"word_id": WORD},
        None,
    )
    assert str(STUDENT_A) not in response.text and str(STUDENT_B) not in response.text

    theirs = (await notify_client.get(LIST, headers=bearer(tokens["student_b"]))).json()["items"]
    assert [entry["kind"] for entry in theirs] == ["entitlement_expiring"]
    nobody = (await notify_client.get(LIST, headers=bearer(tokens["editor"]))).json()
    assert nobody == {"items": [], "next_cursor": None}


async def test_list_hides_future_push_only_and_expired_events(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], enqueue: Enqueue, admin: asyncpg.Pool
) -> None:
    now = datetime.now(UTC)
    visible = await enqueue(STUDENT_A, "sync_reminder")
    await enqueue(STUDENT_A, "sync_reminder", deliver_after=now + timedelta(hours=1))
    await enqueue(STUDENT_A, "sync_reminder", channels=("push",))
    await admin.execute(
        "INSERT INTO notify.outbox (recipient_id, kind, deliver_after, expires_at, dedupe_hash, state) "
        "VALUES ($1, 'sync_reminder', now() - interval '2 hours', now() - interval '1 hour', "
        "sha256('gone'), 'settled')",
        STUDENT_A,
    )
    both = await enqueue(STUDENT_A, "entitlement_expiring", channels=("in_app", "push"))
    items = (await notify_client.get(LIST, headers=bearer(tokens["student_a"]))).json()["items"]
    assert {entry["id"] for entry in items} == {str(visible), str(both)}
    # Muting a category stops PUSH for it; the learner's own in-app list is unaffected.
    await notify_client.put(
        PREFS,
        headers=bearer(tokens["student_a"]),
        json={"push_enabled": False, "muted_categories": ["account"], "quiet_hours": None},
    )
    items = (await notify_client.get(LIST, headers=bearer(tokens["student_a"]))).json()["items"]
    assert {entry["id"] for entry in items} == {str(visible), str(both)}


async def test_list_pagination_newest_first_without_gaps_or_repeats(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], enqueue: Enqueue
) -> None:
    now = datetime.now(UTC)
    expected = []
    for index in range(7):
        # Several rows share the same instant: the cursor must break the tie by sequence.
        moment = now - timedelta(minutes=10 * (index // 3))
        expected.append((moment, await enqueue(STUDENT_A, "sync_reminder", deliver_after=moment)))
    await enqueue(STUDENT_B, "sync_reminder")
    order = [str(ident) for _, ident in sorted(expected, key=lambda e: e[0], reverse=True)]

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        page = (
            await notify_client.get(LIST, headers=bearer(tokens["student_a"]), params=params)
        ).json()
        seen += [entry["id"] for entry in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 7 and set(seen) == set(order), "every row once, no row of B"
    # Newest instant first; within one instant the later-enqueued row comes first.
    instants = {str(ident): moment for moment, ident in expected}
    assert [instants[ident] for ident in seen] == sorted(instants.values(), reverse=True)

    exact = (
        await notify_client.get(LIST, headers=bearer(tokens["student_a"]), params={"limit": 7})
    ).json()
    assert len(exact["items"]) == 7 and exact["next_cursor"] is None, "no empty trailing page"


async def test_list_cursor_and_limit_rules(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], enqueue: Enqueue
) -> None:
    for _ in range(2):
        await enqueue(STUDENT_A, "sync_reminder")
    first = (
        await notify_client.get(LIST, headers=bearer(tokens["student_a"]), params={"limit": 1})
    ).json()
    cursor = first["next_cursor"]
    assert cursor
    # A's cursor used by B (shared phone, account switch): refused, never B's or A's rows.
    crossed = await notify_client.get(
        LIST, headers=bearer(tokens["student_b"]), params={"cursor": cursor}
    )
    assert crossed.status_code == 422
    assert crossed.json()["error"]["code"] == "notification_cursor_invalid"
    for params, code in (
        ({"cursor": "garbage"}, "notification_cursor_invalid"),
        ({"cursor": "x" * 201}, "validation_error"),
        ({"limit": 0}, "validation_error"),
        ({"limit": 51}, "validation_error"),
        ({"limit": "many"}, "validation_error"),
    ):
        response = await notify_client.get(LIST, headers=bearer(tokens["student_a"]), params=params)
        assert response.status_code == 422, params
        assert response.json()["error"]["code"] == code, params


async def test_no_request_can_create_a_notification(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    payload = {"recipient_id": str(STUDENT_B), "kind": "sync_reminder", "refs": {}}
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = await notify_client.request(
            method, LIST, headers=bearer(tokens["student_a"]), json=payload
        )
        assert response.status_code == 405, method
        assert response.json()["error"]["code"] == "method_not_allowed"
    for path in ("/v1/notifications/enqueue", "/v1/notify/enqueue", "/v1/notifications/send"):
        response = await notify_client.post(path, headers=bearer(tokens["student_a"]), json=payload)
        assert response.status_code == 404, path
    assert await admin.fetchval("SELECT count(*) FROM notify.outbox") == 0


async def test_even_arbitrary_sql_on_the_api_connection_cannot_create_or_read_others(
    notify_app: FastAPI, clean_notify_state: None, enqueue: Enqueue, admin: asyncpg.Pool
) -> None:
    """If the API were tricked into running SQL as its own role (both pools use the
    same least-privileged login), it still could not enqueue, deliver or erase."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    await enqueue(STUDENT_B, "sync_reminder")
    statements = [
        f"SELECT notify.enqueue('{STUDENT_B}', 'sync_reminder', '{{}}', 'forged')",
        f"SELECT notify.enqueue('{STUDENT_A}', 'sync_reminder', '{{}}', 'forged')",
        "SELECT * FROM notify.claim_due('push')",
        "SELECT notify.record_attempt(gen_random_uuid(), 'push', gen_random_uuid(), 'delivered')",
        f"SELECT notify.erase_learner('{STUDENT_B}')",
        f"INSERT INTO notify.outbox (recipient_id, kind, dedupe_hash) VALUES ('{STUDENT_A}', 'sync_reminder', sha256('x'))",
        f"INSERT INTO notify.preferences (learner_id, push_enabled) VALUES ('{STUDENT_A}', true)",
        "UPDATE notify.preferences SET push_enabled = true",
        "UPDATE notify.policy SET quiet_start = '00:00', quiet_end = '00:01'",
        "DELETE FROM notify.outbox",
        "SELECT count(*) FROM notify.deliveries",
        "SELECT dedupe_hash FROM notify.outbox",
    ]
    for database in (notify_app.state.db, notify_app.state.notify_db):
        for statement in statements:
            try:
                async with database.transaction(STUDENT_A) as conn:
                    await conn.execute(text(statement))
            except DBAPIError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "42501", statement
            else:
                raise AssertionError(f"statement was allowed: {statement}")
        async with database.transaction(STUDENT_A, read_only=True) as conn:
            assert (await conn.execute(text("SELECT count(*) FROM notify.outbox"))).scalar() == 0
    assert await admin.fetchval("SELECT count(*) FROM notify.outbox") == 1
