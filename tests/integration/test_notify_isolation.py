"""Nothing depends on notifications: lessons, catalog, sync and readiness answer
normally when the `notify` schema is unreachable, locked or slow. Also: the schema
is not reachable through the Supabase Data API.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.main import create_app
from tests.conftest import build_settings
from tests.helpers import SEED_LESSON, SEED_QUESTIONS_FR, STUDENT_A, answer_op, bearer

if TYPE_CHECKING:
    from tests.notify_fixtures import Enqueue

pytest_plugins = ("tests.notify_fixtures",)

PREFS = "/v1/me/notification-preferences"
LIST = "/v1/notifications"
PREFS_BODY = {"push_enabled": False, "muted_categories": [], "quiet_hours": None}


@pytest.fixture
async def fast_fail_client(
    local_env: dict[str, str], clean_notify_state: None
) -> AsyncIterator[httpx.AsyncClient]:
    """Flag on, with a short notify timeout so an outage is observed quickly."""
    settings = build_settings(
        local_env,
        notifications_enabled=True,
        notify_db_statement_timeout_ms=300,
        notify_db_pool_timeout_s=0.3,
    )
    application = create_app(settings)
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            yield http
    finally:
        await application.state.db.dispose()
        await application.state.notify_db.dispose()


async def _learning_works(http: httpx.AsyncClient, token: str) -> None:
    """Every learning route, including a real exactly-once write."""
    assert (await http.get("/health")).json() == {"status": "ok"}
    ready = await http.get("/ready")
    assert (ready.status_code, ready.json()["status"]) == (200, "ready")
    assert (await http.get("/v1/me", headers=bearer(token))).status_code == 200
    catalog = await http.get("/v1/catalog", params={"locale": "fr"}, headers=bearer(token))
    assert catalog.status_code == 200 and catalog.json()["courses"]
    lesson = await http.get(
        f"/v1/lessons/{SEED_LESSON}", params={"locale": "fr"}, headers=bearer(token)
    )
    assert lesson.status_code == 200 and lesson.json()["questions"]
    question, correct = SEED_QUESTIONS_FR[0]
    op = answer_op(question, correct)
    pushed = await http.post("/v1/sync/push", headers=bearer(token), json={"ops": [op]})
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["results"][0]["status"] == "accepted"
    pulled = await http.get("/v1/sync/pull", headers=bearer(token))
    assert pulled.status_code == 200 and pulled.json()["changes"]


async def _notify_is_down(http: httpx.AsyncClient, token: str) -> None:
    for method, path, kwargs in (
        ("GET", LIST, {}),
        ("GET", PREFS, {}),
        ("PUT", PREFS, {"json": PREFS_BODY}),
    ):
        response = await http.request(method, path, headers=bearer(token), **kwargs)
        assert response.status_code == 503, (method, path, response.text)
        error = response.json()["error"]
        assert error["code"] == "notifications_unavailable"
        assert response.headers["retry-after"] == "30"
        assert "notify." not in response.text and "permission" not in response.text


async def test_learning_answers_normally_when_the_notify_schema_is_unreachable(
    fast_fail_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    token = tokens["student_a"]
    assert (await fast_fail_client.get(LIST, headers=bearer(token))).status_code == 200
    await admin.execute("REVOKE USAGE ON SCHEMA notify FROM edu_api")
    try:
        await _notify_is_down(fast_fail_client, token)
        await _learning_works(fast_fail_client, token)
    finally:
        await admin.execute("GRANT USAGE ON SCHEMA notify TO edu_api")
    assert (await fast_fail_client.get(LIST, headers=bearer(token))).status_code == 200, "recovers"


async def test_learning_answers_normally_while_notify_tables_are_locked(
    fast_fail_client: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    enqueue: Enqueue,
) -> None:
    """A stuck migration or a runaway job holds every notify table. Notification
    requests pile up on their own 2-connection pool and time out; learning requests,
    on the main pool, are not slowed down."""
    token = tokens["student_a"]
    await enqueue(STUDENT_A, "sync_reminder")
    async with admin.acquire() as blocker:
        transaction = blocker.transaction()
        await transaction.start()
        try:
            await blocker.execute(
                "LOCK TABLE notify.outbox, notify.preferences, notify.policy, notify.kinds "
                "IN ACCESS EXCLUSIVE MODE"
            )
            # Twelve notification requests at once: far more than the notify pool holds.
            stuck = [
                asyncio.create_task(fast_fail_client.get(LIST, headers=bearer(token)))
                for _ in range(6)
            ] + [
                asyncio.create_task(fast_fail_client.get(PREFS, headers=bearer(token)))
                for _ in range(6)
            ]
            await asyncio.sleep(0.05)  # let them occupy the notify pool
            started = time.monotonic()
            await _learning_works(fast_fail_client, token)
            learning_seconds = time.monotonic() - started
            responses = await asyncio.gather(*stuck)
            assert {response.status_code for response in responses} == {503}
            assert {response.json()["error"]["code"] for response in responses} == {
                "notifications_unavailable"
            }
            await _notify_is_down(fast_fail_client, token)
            await _learning_works(fast_fail_client, token)
        finally:
            await transaction.rollback()
    assert learning_seconds < 5, f"learning took {learning_seconds:.2f}s during a notify outage"
    recovered = await fast_fail_client.get(LIST, headers=bearer(token))
    assert recovered.status_code == 200 and len(recovered.json()["items"]) == 1


def test_learning_code_never_references_the_notify_schema() -> None:
    """The structural half of the guarantee: lessons, catalog, identity, sync, health and
    the shared database/error/middleware modules contain no reference to `notify`."""
    source = Path(__file__).resolve().parents[2] / "services" / "api" / "src" / "edu_api"
    learning = [
        *source.glob("sync/*.py"),
        *source.glob("auth/*.py"),
        *source.glob("db/*.py"),
        source / "routers" / "catalog.py",
        source / "routers" / "sync.py",
        source / "routers" / "me.py",
        source / "routers" / "health.py",
        source / "identity.py",
        source / "deps.py",
        source / "errors.py",
        source / "middleware.py",
    ]
    assert len(learning) >= 15
    for module in learning:
        assert "notif" not in module.read_text(encoding="utf-8").lower(), module


async def test_readiness_does_not_look_at_notifications(
    notify_app: FastAPI, notify_client: httpx.AsyncClient, admin: asyncpg.Pool
) -> None:
    """`/ready` means "learning can be served". It must stay 200 when notify is broken,
    and it must not open a connection on the notification pool."""
    await admin.execute("REVOKE USAGE ON SCHEMA notify FROM edu_api")
    try:
        for _ in range(3):
            response = await notify_client.get("/ready")
            assert response.status_code == 200
            assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
    finally:
        await admin.execute("GRANT USAGE ON SCHEMA notify TO edu_api")
    assert notify_app.state.notify_db.engine.pool.checkedout() == 0
    assert notify_app.state.notify_db.engine is not notify_app.state.db.engine


async def test_notify_schema_is_not_reachable_through_the_supabase_data_api(
    local_env: dict[str, str], tokens: dict[str, str], enqueue: Enqueue
) -> None:
    marker = await enqueue(STUDENT_A, "sync_reminder")
    rest = local_env["LOCAL_SUPABASE_URL"] + "/rest/v1"
    credentials = {
        "publishable key only": {"apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
        "signed-in student": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {tokens['student_a']}",
        },
        "SECRET service key": {"apikey": local_env["LOCAL_SUPABASE_SECRET_KEY"]},
    }
    async with httpx.AsyncClient(timeout=10) as http:
        for label, headers in credentials.items():
            for table in ("outbox", "preferences", "deliveries", "delivery_attempts", "policy"):
                for profile in ({"Accept-Profile": "notify"}, {}):
                    response = await http.get(
                        f"{rest}/{table}", params={"select": "*"}, headers={**headers, **profile}
                    )
                    assert response.status_code >= 400, (label, table, profile, response.text[:200])
                    assert str(marker) not in response.text and "a0000000" not in response.text
            for function, arguments in (
                (
                    "enqueue",
                    {
                        "p_recipient": str(STUDENT_A),
                        "p_kind": "sync_reminder",
                        "p_refs": {},
                        "p_dedupe_key": uuid.uuid4().hex,
                    },
                ),
                ("claim_due", {"p_channel": "push"}),
                (
                    "set_preferences",
                    {
                        "p_push_enabled": True,
                        "p_muted_categories": [],
                        "p_quiet_start": None,
                        "p_quiet_end": None,
                    },
                ),
                ("erase_learner", {"p_user_id": str(STUDENT_A)}),
            ):
                for profile in ({"Content-Profile": "notify"}, {}):
                    rpc = await http.post(
                        f"{rest}/rpc/{function}", headers={**headers, **profile}, json=arguments
                    )
                    assert rpc.status_code >= 400, (label, function, profile, rpc.text[:200])
        exposed = (await http.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    assert "outbox" not in exposed and "delivery_attempts" not in exposed
