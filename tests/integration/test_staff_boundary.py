"""The staff boundary (B1): a separate database login, role checks on every
request, audited refusals, and nothing reachable from the student side or the
Supabase Data API."""

# ruff: noqa: F811  (fixtures imported from tests.staff_fixtures are requested by name)
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, Any

import asyncpg
import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from edu_api.db.session import Database
from edu_api.main import create_app
from edu_api.routers import staff as staff_router
from edu_api.staff.deps import StaffPrincipal, require_staff
from tests.helpers import EDITOR, REVIEWER, STUDENT_A, STUDENT_B, bearer
from tests.staff_fixtures import (  # noqa: F401  (fixtures are used by name)
    MakeStaff,
    build_staff_settings,
    create_account,
    dispose_app,
    make_staff,
    remove_account,
    set_role_active,
    staff_app,
    staff_client,
    staff_settings,
    staff_tokens,
    staff_url,
    worker_url,
)

pytestmark = pytest.mark.integration

WHOAMI = text("SELECT current_user AS u, session_user AS s")


async def denied_events(admin: asyncpg.Pool, actor: uuid.UUID) -> list[dict[str, Any]]:
    rows = await admin.fetch(
        "SELECT actor_kind, action, target_kind, target_id, outcome, details "
        "FROM app.audit_events WHERE actor_id = $1 AND action = 'staff.access' ORDER BY created_at, id",
        actor,
    )
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


def _rebuilt_router(original: APIRouter, *, include_in_schema: bool) -> APIRouter:
    """The same routes on a router declared with the given ``include_in_schema``."""
    rebuilt = APIRouter(
        prefix=original.prefix, tags=list(original.tags), include_in_schema=include_in_schema
    )
    for route in original.routes:
        assert isinstance(route, APIRoute)
        rebuilt.add_api_route(
            route.path.removeprefix(original.prefix),
            route.endpoint,
            methods=list(route.methods),
            response_model=route.response_model,
            responses=route.responses,
            summary=route.summary,
        )
    return rebuilt


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert set(error) <= {"code", "message", "request_id", "details"}
    assert error["request_id"]


# ------------------------------------------------- staff side switched off (default)
async def test_staff_routes_answer_503_when_the_staff_side_is_not_configured(
    client: httpx.AsyncClient, app: FastAPI, tokens: dict[str, str]
) -> None:
    assert app.state.staff_db is None
    # authentication still comes first
    assert_error(await client.get("/v1/staff/me"), 401, "unauthenticated")
    for who in ("student_a", "editor"):
        response = await client.get("/v1/staff/me", headers=bearer(tokens[who]))
        assert_error(response, 503, "staff_unavailable")
    spec = (await client.get("/openapi.json")).json()
    assert not [path for path in spec["paths"] if path.startswith("/v1/staff")], (
        "with the staff side off, the published contract is exactly the learner contract"
    )


# ----------------------------------------------------------- who gets through
async def test_staff_me_requires_a_token(staff_client: httpx.AsyncClient) -> None:
    response = await staff_client.get("/v1/staff/me")
    assert_error(response, 401, "unauthenticated")
    assert response.headers["www-authenticate"] == "Bearer"
    garbage = await staff_client.get("/v1/staff/me", headers=bearer("not-a-token"))
    assert_error(garbage, 401, "unauthenticated")


async def test_seeded_staff_see_their_own_roles(
    staff_client: httpx.AsyncClient, staff_tokens: dict[str, str]
) -> None:
    editor = await staff_client.get("/v1/staff/me", headers=bearer(staff_tokens["editor"]))
    reviewer = await staff_client.get("/v1/staff/me", headers=bearer(staff_tokens["reviewer"]))
    assert (editor.status_code, editor.json()) == (
        200,
        {"user_id": str(EDITOR), "roles": ["editor"]},
    )
    assert (reviewer.status_code, reviewer.json()) == (
        200,
        {"user_id": str(REVIEWER), "roles": ["reviewer"]},
    )


async def test_a_learner_token_is_refused_and_the_refusal_is_audited(
    staff_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    before = await denied_events(admin, STUDENT_A)
    others_before = await admin.fetchval(
        "SELECT count(*) FROM app.audit_events WHERE actor_id IS DISTINCT FROM $1", STUDENT_A
    )
    response = await staff_client.get("/v1/staff/me", headers=bearer(tokens["student_a"]))
    assert_error(response, 403, "forbidden")
    assert "editor" not in response.text and "role" not in response.text.lower()

    after = await denied_events(admin, STUDENT_A)
    assert len(after) == len(before) + 1
    assert after[-1] == {
        "actor_kind": "staff",  # the channel: written through the staff login
        "action": "staff.access",
        "target_kind": None,
        "target_id": None,
        "outcome": "denied",
        "details": {"method": "GET", "route": "/v1/staff/me", "required_roles": ["any"]},
    }
    assert others_before == await admin.fetchval(
        "SELECT count(*) FROM app.audit_events WHERE actor_id IS DISTINCT FROM $1", STUDENT_A
    ), "nothing was attributed to anyone else"
    # being refused on the staff side does not turn the account into anything else
    assert (
        await admin.fetchval("SELECT count(*) FROM app.staff_roles WHERE user_id = $1", STUDENT_A)
        == 0
    )


async def test_an_allowed_staff_request_writes_no_access_event(
    staff_client: httpx.AsyncClient, staff_tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    before = len(await denied_events(admin, EDITOR))
    assert (
        await staff_client.get("/v1/staff/me", headers=bearer(staff_tokens["editor"]))
    ).status_code == 200
    assert len(await denied_events(admin, EDITOR)) == before


async def test_new_synthetic_staff_accounts_and_accounts_without_roles(
    staff_client: httpx.AsyncClient,
    make_staff: MakeStaff,
    local_env: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    publisher = await make_staff("publisher")
    admin_and_editor = await make_staff("admin", "editor", granted_by=publisher.user_id)
    nobody = await make_staff()

    one = await staff_client.get("/v1/staff/me", headers=bearer(publisher.token))
    two = await staff_client.get("/v1/staff/me", headers=bearer(admin_and_editor.token))
    assert one.json() == {"user_id": str(publisher.user_id), "roles": ["publisher"]}
    assert two.json() == {"user_id": str(admin_and_editor.user_id), "roles": ["admin", "editor"]}
    assert_error(
        await staff_client.get("/v1/staff/me", headers=bearer(nobody.token)), 403, "forbidden"
    )
    assert len(await denied_events(admin, nobody.user_id)) == 1
    # the staff side never creates a learner profile as a side effect
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.learner_profiles WHERE user_id = ANY($1::uuid[])",
            [publisher.user_id, admin_and_editor.user_id, nobody.user_id],
        )
        == 0
    )


# ----------------------------------------------------- role-specific routes
@pytest.fixture
async def role_app(local_env: dict[str, str]):  # type: ignore[no-untyped-def]
    """A private app instance with two extra routes that need specific roles."""
    application = create_app(build_staff_settings(local_env))

    @application.get("/v1/staff/test-only/publish/{thing_id}")
    async def publish_only(
        thing_id: uuid.UUID,
        staff: Annotated[StaffPrincipal, Depends(require_staff("publisher", "admin"))],
    ) -> dict[str, Any]:
        return {"user_id": str(staff.user_id), "roles": sorted(staff.roles)}

    @application.post("/v1/staff/test-only/review")
    async def review_only(
        staff: Annotated[StaffPrincipal, Depends(require_staff("reviewer"))],
    ) -> dict[str, Any]:
        return {"user_id": str(staff.user_id), "roles": sorted(staff.roles)}

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http
    await dispose_app(application)


async def test_a_route_can_require_specific_roles(
    role_app: httpx.AsyncClient,
    staff_tokens: dict[str, str],
    tokens: dict[str, str],
    make_staff: MakeStaff,
    admin: asyncpg.Pool,
) -> None:
    thing = uuid.uuid4()
    publish = f"/v1/staff/test-only/publish/{thing}"
    publisher = await make_staff("publisher")
    multi = await make_staff("editor", "admin")

    ok = await role_app.get(publish, headers=bearer(publisher.token))
    assert (ok.status_code, ok.json()["roles"]) == (200, ["publisher"])
    also_ok = await role_app.get(publish, headers=bearer(multi.token))
    assert (also_ok.status_code, also_ok.json()["roles"]) == (200, ["admin", "editor"])

    # a real staff member WITHOUT the right role is refused exactly like a learner
    editor_before = len(await denied_events(admin, EDITOR))
    wrong_role = await role_app.get(publish, headers=bearer(staff_tokens["editor"]))
    learner = await role_app.get(publish, headers=bearer(tokens["student_b"]))
    assert_error(wrong_role, 403, "forbidden")
    assert_error(learner, 403, "forbidden")
    assert wrong_role.json()["error"]["message"] == learner.json()["error"]["message"]
    editor_events = await denied_events(admin, EDITOR)
    assert len(editor_events) == editor_before + 1
    assert editor_events[-1]["details"] == {
        "method": "GET",
        # the route TEMPLATE: the id from the URL is not copied into the audit log
        "route": "/v1/staff/test-only/publish/{thing_id}",
        "required_roles": ["admin", "publisher"],
    }
    assert str(thing) not in json.dumps(editor_events[-1]["details"])

    review = "/v1/staff/test-only/review"
    assert (
        await role_app.post(review, headers=bearer(staff_tokens["reviewer"]))
    ).status_code == 200
    assert_error(await role_app.post(review, headers=bearer(publisher.token)), 403, "forbidden")
    assert_error(await role_app.post(review), 401, "unauthenticated")
    assert (await denied_events(admin, STUDENT_B))[-1]["details"]["route"] == (
        "/v1/staff/test-only/publish/{thing_id}"
    )


async def test_a_deactivated_role_stops_working_on_the_next_request(
    role_app: httpx.AsyncClient,
    make_staff: MakeStaff,
    admin: asyncpg.Pool,
) -> None:
    """Roles are read from the database on every request: an already issued,
    still valid access token loses its staff access the moment the role does."""
    account = await make_staff("publisher", "editor")
    publish = f"/v1/staff/test-only/publish/{uuid.uuid4()}"
    assert (await role_app.get(publish, headers=bearer(account.token))).status_code == 200

    await set_role_active(admin, account.user_id, "publisher", False)
    assert_error(await role_app.get(publish, headers=bearer(account.token)), 403, "forbidden")
    me = await role_app.get("/v1/staff/me", headers=bearer(account.token))
    assert me.json()["roles"] == ["editor"], "the other, still active role is unaffected"

    await set_role_active(admin, account.user_id, "editor", False)
    assert_error(
        await role_app.get("/v1/staff/me", headers=bearer(account.token)), 403, "forbidden"
    )

    await set_role_active(admin, account.user_id, "publisher", True)
    assert (await role_app.get(publish, headers=bearer(account.token))).status_code == 200


def test_require_staff_rejects_unknown_role_names_when_the_route_is_defined() -> None:
    with pytest.raises(ValueError, match="unknown staff role"):
        require_staff("editor", "superuser")


# ------------------------------------------- identity isolation on the staff pool
async def test_staff_identity_does_not_leak_across_a_single_pooled_connection(
    local_env: dict[str, str], staff_tokens: dict[str, str], tokens: dict[str, str]
) -> None:
    application = create_app(
        build_staff_settings(local_env, staff_db_pool_size=1, staff_db_max_overflow=0)
    )
    expected = {
        "editor": (200, ["editor"]),
        "reviewer": (200, ["reviewer"]),
        "student_a": (403, None),
    }
    all_tokens = {**staff_tokens, "student_a": tokens["student_a"]}
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            order = ["editor", "student_a", "reviewer", "student_a", "editor", "reviewer"]
            for who in order:
                response = await http.get("/v1/staff/me", headers=bearer(all_tokens[who]))
                assert (response.status_code, response.json().get("roles")) == expected[who], who
            assert (await http.get("/v1/staff/me")).status_code == 401
            mixed = await asyncio.gather(
                *(http.get("/v1/staff/me", headers=bearer(all_tokens[who])) for who in order * 4)
            )
            for who, response in zip(order * 4, mixed, strict=True):
                assert (response.status_code, response.json().get("roles")) == expected[who], who
        staff_db: Database = application.state.staff_db
        async with staff_db.transaction(None) as conn:
            leftover = (
                await conn.execute(text("SELECT current_setting('edu.actor_id', true)"))
            ).scalar_one()
            roles = (await conn.execute(text("SELECT staff.actor_roles()"))).scalar_one()
        assert leftover in ("", None) and roles == []
    finally:
        await dispose_app(application)


# ------------------------------------------------------------ the database roles
async def test_the_three_pools_use_three_separate_least_privilege_logins(
    staff_app: FastAPI,
    local_env: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    async with staff_app.state.db.transaction(None) as conn:
        student = (await conn.execute(WHOAMI)).one()
    async with staff_app.state.staff_db.transaction(None) as conn:
        staff = (await conn.execute(WHOAMI)).one()
    worker_conn = await asyncpg.connect(worker_url(local_env), timeout=10)
    try:
        worker = await worker_conn.fetchrow("SELECT current_user AS u, session_user AS s")
    finally:
        await worker_conn.close()
    assert (student.u, student.s) == ("edu_api_login", "edu_api_login")
    assert (staff.u, staff.s) == ("edu_staff_login", "edu_staff_login")
    assert (worker["u"], worker["s"]) == ("edu_worker_login", "edu_worker_login")

    attributes = await admin.fetch(
        "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication "
        "FROM pg_roles WHERE rolname IN ('edu_api_login','edu_staff_login','edu_worker_login')"
    )
    assert len(attributes) == 3
    for row in attributes:
        assert not any(v for k, v in row.items() if k != "rolname"), dict(row)
    memberships = await admin.fetch(
        "SELECT u.rolname AS login, array_agg(g.rolname::text ORDER BY g.rolname) AS groups "
        "FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
        "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname LIKE 'edu\\_%\\_login' GROUP BY u.rolname"
    )
    assert {row["login"]: row["groups"] for row in memberships} == {
        "edu_api_login": ["edu_api"],
        "edu_staff_login": ["edu_staff"],
        "edu_worker_login": ["edu_worker"],
    }


STAFF_FORBIDDEN_SQL = [
    "SELECT * FROM app.staff_roles",
    "INSERT INTO app.staff_roles (user_id, role) VALUES ('a0000000-0000-4000-8000-000000000003', 'admin')",
    "UPDATE app.staff_roles SET is_active = true",
    "SELECT * FROM app.audit_events",
    "INSERT INTO app.audit_events (actor_kind, action, outcome) VALUES ('staff', 'forged.event', 'allowed')",
    "DELETE FROM app.audit_events",
    "UPDATE app.lesson_revisions SET title = 'x'",
    "UPDATE app.pack_current SET release_id = gen_random_uuid()",
    "SELECT * FROM app.learner_profiles",
    "SELECT * FROM app.practice_attempts",
    "SELECT * FROM app.background_jobs",
    "SELECT * FROM auth.users",
    "SELECT app.current_actor_id()",
    "SELECT app.sync_apply_operation(gen_random_uuid(), 'lesson_completed', '{}', sha256('x'), 'mep-canon-1')",
    "SELECT ops.actor_kind_for('postgres')",
    "SELECT ops.check_audit_details('{}')",
    "SELECT staff.check_role_names(ARRAY['admin'])",
    "SET ROLE postgres",
    "SET ROLE service_role",
    "SET ROLE edu_api",
    "SET ROLE edu_worker",
    "SET ROLE edu_api_login",
    "CREATE TABLE public.exfil (x int)",
    "CREATE TABLE staff.exfil (x int)",
    "CREATE FUNCTION ops.exfil() RETURNS int LANGUAGE sql AS 'SELECT 1'",
    "ALTER TABLE app.audit_events DISABLE TRIGGER no_edit_audit",
]


@pytest.mark.parametrize("statement", STAFF_FORBIDDEN_SQL)
async def test_arbitrary_sql_on_the_staff_connection_reaches_no_table(
    staff_app: FastAPI,
    statement: str,
) -> None:
    """Worst case: an attacker can run SQL of their choice on the staff API's
    connection, with a real staff member as the actor."""
    with pytest.raises(DBAPIError) as caught:
        async with staff_app.state.staff_db.transaction(EDITOR) as conn:
            await conn.execute(text(statement))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT ops.audit_write('staff.access', NULL, NULL, 'allowed')",
        "SELECT staff.actor_roles()",
        "SELECT staff.actor_has_role('editor')",
        "SELECT staff.require_role('editor')",
        "SET ROLE edu_staff",
        "SET ROLE edu_staff_login",
        "SET ROLE edu_worker",
    ],
)
async def test_the_student_connection_cannot_use_the_staff_or_ops_schema(
    app: FastAPI, statement: str
) -> None:
    """…even with a real staff member as the actor on the student pool."""
    with pytest.raises(DBAPIError) as caught:
        async with app.state.db.transaction(EDITOR) as conn:
            await conn.execute(text(statement))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT staff.actor_roles()",
        "SELECT staff.require_role('editor')",
        "SELECT * FROM app.background_jobs",
        "SELECT * FROM app.audit_events",
        "SELECT * FROM app.practice_attempts",
        "SELECT app.current_actor_id()",
        "SET ROLE edu_staff",
        "SET ROLE edu_api",
        "SET ROLE postgres",
    ],
)
async def test_the_worker_login_reaches_only_what_it_was_granted(
    local_env: dict[str, str], statement: str
) -> None:
    conn = await asyncpg.connect(worker_url(local_env), timeout=10)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(statement)
    finally:
        await conn.close()


# -------------------------------------------------------- audit attribution
async def test_audit_events_are_attributed_by_database_login(
    staff_app: FastAPI,
    local_env: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    revision = uuid.UUID("c0000000-0000-4000-8000-000000000001")
    write = text(
        "SELECT ops.audit_write('test_fixture.probe', 'lesson_revision', :target, 'allowed', "
        "CAST(:details AS jsonb))"
    )
    async with staff_app.state.staff_db.transaction(REVIEWER) as conn:
        staff_event = (
            await conn.execute(write, {"target": revision, "details": '{"step":"staff"}'})
        ).scalar_one()
    worker_conn = await asyncpg.connect(worker_url(local_env), timeout=10)
    try:
        worker_event = await worker_conn.fetchval(
            "SELECT ops.audit_write('test_fixture.probe', NULL, NULL, 'error', $1::jsonb)",
            '{"error_class":"TimeoutError"}',
        )
        # a worker cannot dress up as a person by setting the actor: the kind stays 'worker'
        async with worker_conn.transaction():
            await worker_conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(EDITOR))
            dressed_up = await worker_conn.fetchval(
                "SELECT ops.audit_write('test_fixture.probe', NULL, NULL, 'allowed')"
            )
    finally:
        await worker_conn.close()

    rows = {
        row["id"]: row
        for row in await admin.fetch(
            "SELECT id, actor_id, actor_kind, action, target_kind, target_id, outcome, details "
            "FROM app.audit_events WHERE id = ANY($1::uuid[])",
            [staff_event, worker_event, dressed_up],
        )
    }
    assert (rows[staff_event]["actor_id"], rows[staff_event]["actor_kind"]) == (REVIEWER, "staff")
    assert (rows[staff_event]["target_kind"], rows[staff_event]["target_id"]) == (
        "lesson_revision",
        revision,
    )
    assert json.loads(rows[staff_event]["details"]) == {"step": "staff"}
    assert (rows[worker_event]["actor_id"], rows[worker_event]["actor_kind"]) == (None, "worker")
    assert rows[worker_event]["outcome"] == "error"
    assert rows[dressed_up]["actor_kind"] == "worker"


async def test_a_staff_audit_event_needs_an_actor_and_rolls_back_with_its_transaction(
    staff_app: FastAPI,
    admin: asyncpg.Pool,
) -> None:
    staff_db: Database = staff_app.state.staff_db
    with pytest.raises(DBAPIError) as caught:
        async with staff_db.transaction(None) as conn:
            await conn.execute(
                text("SELECT ops.audit_write('test_fixture.anonymous', NULL, NULL, 'allowed')")
            )
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"

    # an event shares the fate of the transaction that wrote it
    with pytest.raises(RuntimeError, match="boom"):
        async with staff_db.transaction(EDITOR) as conn:
            await conn.execute(
                text("SELECT ops.audit_write('test_fixture.rolled_back', NULL, NULL, 'allowed')")
            )
            raise RuntimeError("boom")
    # a refused role check raises, so nothing written before it in the same transaction survives
    with pytest.raises(DBAPIError) as refused:
        async with staff_db.transaction(EDITOR) as conn:
            await conn.execute(
                text("SELECT ops.audit_write('test_fixture.rolled_back', NULL, NULL, 'denied')")
            )
            await conn.execute(text("SELECT staff.require_role('admin')"))
    assert getattr(refused.value.orig, "sqlstate", None) == "42501"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.audit_events WHERE action IN "
            "('test_fixture.anonymous', 'test_fixture.rolled_back')"
        )
        == 0
    )

    with pytest.raises(DBAPIError) as free_text:
        async with staff_db.transaction(EDITOR) as conn:
            await conn.execute(
                text(
                    "SELECT ops.audit_write('test_fixture.probe', NULL, NULL, 'allowed', "
                    "CAST(:details AS jsonb))"
                ),
                {"details": json.dumps({"answer": "a sentence typed by a learner"})},
            )
    assert getattr(free_text.value.orig, "sqlstate", None) == "22023"


# ---------------------------------------------------------------- outage
async def test_staff_database_outage_does_not_affect_learners(
    local_env: dict[str, str], staff_tokens: dict[str, str], tokens: dict[str, str]
) -> None:
    application = create_app(
        build_staff_settings(
            local_env,
            staff_database_url="postgresql+asyncpg://edu_staff_login:unused@127.0.0.1:1/postgres",
            db_connect_timeout_s=1.0,
            db_pool_timeout_s=1.0,
        )
    )
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            for who in (staff_tokens["editor"], tokens["student_a"]):
                response = await http.get("/v1/staff/me", headers=bearer(who))
                assert_error(response, 503, "dependency_unavailable")
                assert response.headers["retry-after"] == "5"
                assert "127.0.0.1" not in response.text and "edu_staff_login" not in response.text
            # fail closed: an unreachable role store never means "allowed"
            assert_error(await http.get("/v1/staff/me"), 401, "unauthenticated")
            learner = await http.get("/v1/me", headers=bearer(tokens["student_a"]))
            assert (learner.status_code, learner.json()["user_id"]) == (200, str(STUDENT_A))
            assert (await http.get("/ready")).status_code == 200
    finally:
        await dispose_app(application)


# ----------------------------- ops and staff are not reachable through the Data API
async def test_ops_and_staff_schemas_are_not_reachable_through_the_supabase_data_api(
    local_env: dict[str, str], tokens: dict[str, str], staff_tokens: dict[str, str]
) -> None:
    rest = local_env["LOCAL_SUPABASE_URL"] + "/rest/v1"
    publishable = local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]
    credentials = {
        "publishable key only": {"apikey": publishable},
        "signed-in student": {
            "apikey": publishable,
            "Authorization": f"Bearer {tokens['student_a']}",
        },
        "signed-in editor": {
            "apikey": publishable,
            "Authorization": f"Bearer {staff_tokens['editor']}",
        },
        "SECRET service key": {"apikey": local_env["LOCAL_SUPABASE_SECRET_KEY"]},
    }
    calls: list[tuple[str, dict[str, Any]]] = [
        (
            "audit_write",
            {
                "p_action": "forged.event",
                "p_target_kind": None,
                "p_target_id": None,
                "p_outcome": "allowed",
            },
        ),
        ("actor_roles", {}),
        ("actor_has_role", {"p_roles": ["editor"]}),
        ("require_role", {"p_roles": ["editor"]}),
        ("actor_kind_for", {"p_role": "postgres"}),
    ]
    before = await _audit_count(local_env)
    async with httpx.AsyncClient(timeout=10) as http:
        for label, headers in credentials.items():
            for function, arguments in calls:
                for profile in ({"Content-Profile": "ops"}, {"Content-Profile": "staff"}, {}):
                    response = await http.post(
                        f"{rest}/rpc/{function}", headers={**headers, **profile}, json=arguments
                    )
                    assert response.status_code >= 400, (
                        label,
                        function,
                        profile,
                        response.text[:200],
                    )
            for schema in ("ops", "staff"):
                listing = await http.get(f"{rest}/", headers={**headers, "Accept-Profile": schema})
                assert listing.status_code >= 400, (label, schema)
        exposed = (await http.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    assert "audit_write" not in exposed and "require_role" not in exposed
    assert await _audit_count(local_env) == before, "no audit event was forged through the Data API"


async def _audit_count(env: dict[str, str]) -> int:
    conn = await asyncpg.connect(env["LOCAL_ADMIN_DATABASE_URL"], timeout=10)
    try:
        return int(await conn.fetchval("SELECT count(*) FROM app.audit_events"))
    finally:
        await conn.close()


# ------------------------------------------------------------------ contract
async def test_staff_routes_stay_out_of_the_published_contract_on_this_branch(
    staff_client: httpx.AsyncClient,
) -> None:
    """Ruling R-01: registered and working, but absent from the OpenAPI document."""
    assert staff_router.INCLUDE_IN_SCHEMA is False
    spec = (await staff_client.get("/openapi.json")).json()
    assert not [path for path in spec["paths"] if path.startswith("/v1/staff")]


async def test_staff_routes_follow_the_api_contract_rules_once_included(
    local_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With INCLUDE_IN_SCHEMA on (as the director will set it at integration)."""
    monkeypatch.setattr(staff_router, "INCLUDE_IN_SCHEMA", True)
    original_router = staff_router.router
    monkeypatch.setattr(
        staff_router, "router", _rebuilt_router(original_router, include_in_schema=True)
    )
    application = create_app(build_staff_settings(local_env))
    try:
        spec = application.openapi()
    finally:
        await dispose_app(application)
    staff_paths = {path: ops for path, ops in spec["paths"].items() if path.startswith("/v1/staff")}
    assert set(staff_paths) == {"/v1/staff/me"}
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, operations in staff_paths.items():
        for operation in operations.values():
            assert operation["security"] == [{"HTTPBearer": []}], path
            assert {"401", "403", "503"} <= set(operation["responses"]), path
            for status, response in operation["responses"].items():
                if status != "200":
                    assert response["content"]["application/json"]["schema"] == error_ref, (
                        path,
                        status,
                    )
    assert "HTTPValidationError" not in spec["components"]["schemas"], "one error shape only"
    # the learner routes are exactly the ones `main` has
    assert {path for path in spec["paths"] if not path.startswith("/v1/staff")} == {
        "/health",
        "/ready",
        "/v1/me",
        "/v1/catalog",
        "/v1/lessons/{lesson_id}",
        "/v1/sync/push",
        "/v1/sync/pull",
    }


async def test_an_account_without_roles_created_by_the_helper_is_a_plain_learner(
    client: httpx.AsyncClient,
    staff_client: httpx.AsyncClient,
    local_env: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    """`create_account` gives other lanes a fresh synthetic learner with a real token."""
    user_id, email, token = await create_account(local_env)
    try:
        assert email.endswith("@edupreneur.test")
        assert_error(
            await staff_client.get("/v1/staff/me", headers=bearer(token)), 403, "forbidden"
        )
        me = await client.get("/v1/me", headers=bearer(token))
        assert (me.status_code, me.json()["user_id"]) == (200, str(user_id))
    finally:
        await remove_account(admin, local_env, user_id)
    assert await admin.fetchval("SELECT count(*) FROM auth.users WHERE id = $1", user_id) == 0
