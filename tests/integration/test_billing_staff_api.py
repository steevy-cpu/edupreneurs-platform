"""Staff entitlement routes under /v1/staff/billing, through the real API with
real local Auth tokens and the real staff database login (edu_staff_login)."""

# ruff: noqa: F811  (pytest fixtures imported from the fixture modules are used as arguments)
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.billing_fixtures import (
    SEED_COURSE,
    SEED_GRADE,
    billing_clean,  # noqa: F401
    billing_client,  # noqa: F401
    billing_staff_app,  # noqa: F401
    billing_staff_client,  # noqa: F401
    grant,
    parse_time,
)
from tests.helpers import STUDENT_A, STUDENT_B, bearer
from tests.staff_fixtures import (  # noqa: F401
    StaffAccount,
    make_staff,
    set_role_active,
    staff_app,
    staff_client,
    staff_settings,
    staff_tokens,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("billing_clean")]

GRANTS = "/v1/staff/billing/grants"
FREE_TEXT = "Because the learner asked nicely on the phone"


def grant_body(learner: uuid.UUID = STUDENT_A, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "learner_id": str(learner),
        "scope": {"kind": "all", "id": None},
        "duration_days": 30,
        "source": "gift",
        "reason_code": "goodwill",
        "idempotency_key": f"http-grant-{uuid.uuid4()}",
    }
    body.update(overrides)
    return body


def revoke_path(entitlement_id: object) -> str:
    return f"{GRANTS}/{entitlement_id}/revoke"


def list_path(learner: uuid.UUID) -> str:
    return f"/v1/staff/billing/learners/{learner}/grants"


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code, response.text
    assert set(error) <= {"code", "message", "request_id", "details"}
    assert error["request_id"]


async def audit_of(admin: asyncpg.Pool, actor: uuid.UUID) -> list[dict[str, Any]]:
    rows = await admin.fetch(
        "SELECT actor_kind, action, target_kind, target_id, outcome, details "
        "FROM app.audit_events WHERE actor_id = $1 ORDER BY created_at, id",
        actor,
    )
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


async def grant_count(admin: asyncpg.Pool) -> int:
    count: int = await admin.fetchval("SELECT count(*) FROM billing.entitlements")
    return count


def three_routes(learner: uuid.UUID = STUDENT_A) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("POST", GRANTS, {"json": grant_body(learner)}),
        ("POST", revoke_path(uuid.uuid4()), {"json": {"reason_code": "correction"}}),
        ("GET", list_path(learner), {}),
    ]


# ----------------------------------------------------------- switched off / closed
async def test_with_the_flag_off_the_staff_routes_do_not_exist(
    staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    """Staff side configured, EDU_ENTITLEMENTS_ENABLED off (the default)."""
    boss = await make_staff("admin")
    for method, path, kwargs in three_routes():
        for headers in ({}, bearer(boss.token)):
            response = await staff_client.request(method, path, headers=headers, **kwargs)
            assert_error(response, 404, "not_found")
    assert await grant_count(admin) == 0
    assert await audit_of(admin, boss.user_id) == []


async def test_without_a_staff_database_the_routes_answer_503(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    for method, path, kwargs in three_routes():
        response = await billing_client.request(
            method, path, headers=bearer(tokens["student_a"]), **kwargs
        )
        assert_error(response, 503, "staff_unavailable")
    assert await grant_count(admin) == 0


async def test_a_token_is_required(billing_staff_client: httpx.AsyncClient) -> None:
    for method, path, kwargs in three_routes():
        response = await billing_staff_client.request(method, path, **kwargs)
        assert_error(response, 401, "unauthenticated")


async def test_learners_and_non_admin_staff_are_refused_and_the_refusal_is_audited(
    billing_staff_client: httpx.AsyncClient,
    tokens: dict[str, str],
    staff_tokens: dict[str, str],
    make_staff: Any,
    admin: asyncpg.Pool,
) -> None:
    await grant(admin, STUDENT_B)
    publisher = await make_staff("publisher")
    callers = [
        (uuid.UUID("a0000000-0000-4000-8000-000000000001"), tokens["student_a"]),
        (uuid.UUID("a0000000-0000-4000-8000-000000000003"), staff_tokens["editor"]),
        (uuid.UUID("a0000000-0000-4000-8000-000000000004"), staff_tokens["reviewer"]),
        (publisher.user_id, publisher.token),
    ]
    templates = [
        ("POST", "/v1/staff/billing/grants"),
        ("POST", "/v1/staff/billing/grants/{entitlement_id}/revoke"),
        ("GET", "/v1/staff/billing/learners/{learner_id}/grants"),
    ]
    for user_id, token in callers:
        before = len(await audit_of(admin, user_id))
        for method, path, kwargs in three_routes(STUDENT_B):
            response = await billing_staff_client.request(
                method, path, headers=bearer(token), **kwargs
            )
            assert_error(response, 403, "forbidden")
            assert str(STUDENT_B) not in response.text
        # a malformed body is still a 403: nothing about the route is revealed
        response = await billing_staff_client.post(
            GRANTS, headers=bearer(token), json={"nonsense": True}
        )
        assert_error(response, 403, "forbidden")
        written = (await audit_of(admin, user_id))[before:]
        assert [(e["action"], e["outcome"], e["actor_kind"]) for e in written] == [
            ("staff.access", "denied", "staff")
        ] * 4
        assert [(e["details"]["method"], e["details"]["route"]) for e in written[:3]] == templates
        assert all(e["details"]["required_roles"] == ["admin"] for e in written)
    assert await grant_count(admin) == 1, "only the fixture grant exists"
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlement_revocations") == 0


# ------------------------------------------------------------------- granting
async def test_an_admin_grants_and_the_learner_sees_it(
    billing_staff_client: httpx.AsyncClient,
    tokens: dict[str, str],
    make_staff: Any,
    admin: asyncpg.Pool,
) -> None:
    boss = await make_staff("admin")
    body = grant_body(
        scope={"kind": "grade", "id": str(SEED_GRADE)},
        duration_days=90,
        source="school_licence",
        reason_code="school_agreement",
    )
    response = await billing_staff_client.post(GRANTS, headers=bearer(boss.token), json=body)
    assert response.status_code == 200, response.text
    created = response.json()
    assert set(created) == {"entitlement_id", "replayed", "starts_at", "ends_at"}
    assert created["replayed"] is False
    assert parse_time(created["ends_at"]) - parse_time(created["starts_at"]) == timedelta(days=90)

    row = await admin.fetchrow(
        "SELECT learner_id, scope_kind, scope_grade_id, source, source_ref, granted_by, idempotency_key "
        "FROM billing.entitlements WHERE id = $1",
        uuid.UUID(created["entitlement_id"]),
    )
    assert dict(row) == {
        "learner_id": STUDENT_A,
        "scope_kind": "grade",
        "scope_grade_id": SEED_GRADE,
        "source": "school_licence",
        "source_ref": "staff:school_agreement",
        "granted_by": boss.user_id,  # from the verified token, not from the body
        "idempotency_key": body["idempotency_key"],
    }

    mine = (
        await billing_staff_client.get("/v1/entitlements", headers=bearer(tokens["student_a"]))
    ).json()["entitlements"]
    assert [(g["id"], g["scope"], g["source"]) for g in mine] == [
        (created["entitlement_id"], {"kind": "grade", "id": str(SEED_GRADE)}, "school_licence")
    ]
    others = (
        await billing_staff_client.get("/v1/entitlements", headers=bearer(tokens["student_b"]))
    ).json()["entitlements"]
    assert others == []

    assert await audit_of(admin, boss.user_id) == [
        {
            "actor_kind": "staff",
            "action": "billing.entitlement.grant",
            "target_kind": "billing_entitlement",
            "target_id": uuid.UUID(created["entitlement_id"]),
            "outcome": "allowed",
            "details": {
                "status": "granted",
                "replayed": False,
                "learner_id": str(STUDENT_A),
                "scope_kind": "grade",
                "scope_id": str(SEED_GRADE),
                "duration_days": 90,
                "source": "school_licence",
                "reason_code": "school_agreement",
            },
        }
    ]


async def test_a_double_grant_with_the_same_key_is_idempotent_through_http(
    billing_staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    body = grant_body()
    first = await billing_staff_client.post(GRANTS, headers=bearer(boss.token), json=body)
    assert first.status_code == 200 and first.json()["replayed"] is False
    for _ in range(3):
        again = await billing_staff_client.post(GRANTS, headers=bearer(boss.token), json=body)
        assert again.status_code == 200
        assert again.json() == {**first.json(), "replayed": True}, "the ORIGINAL grant and dates"
    assert await grant_count(admin) == 1

    # ten simultaneous submissions of a NEW request: still one grant
    burst = grant_body(STUDENT_B)
    responses = await asyncio.gather(
        *(
            billing_staff_client.post(GRANTS, headers=bearer(boss.token), json=burst)
            for _ in range(10)
        )
    )
    assert {r.status_code for r in responses} == {200}
    assert {r.json()["entitlement_id"] for r in responses} == {
        responses[0].json()["entitlement_id"]
    }
    assert sorted(r.json()["replayed"] for r in responses) == [False] + [True] * 9
    assert await grant_count(admin) == 2

    # another admin retrying the same key gets the same grant, not a second one
    colleague = await make_staff("admin")
    theirs = await billing_staff_client.post(GRANTS, headers=bearer(colleague.token), json=body)
    assert theirs.status_code == 200 and theirs.json() == {**first.json(), "replayed": True}
    assert await grant_count(admin) == 2
    assert (
        await admin.fetchval(
            "SELECT granted_by FROM billing.entitlements WHERE id = $1",
            uuid.UUID(first.json()["entitlement_id"]),
        )
        == boss.user_id
    )

    events = await audit_of(admin, boss.user_id)
    assert len(events) == 14, "every call is audited, replays included"
    assert {e["action"] for e in events} == {"billing.entitlement.grant"}
    assert sum(1 for e in events if e["details"]["replayed"] is False) == 2


async def test_reusing_a_key_for_a_different_grant_is_a_409_and_changes_nothing(
    billing_staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    body = grant_body()
    first = await billing_staff_client.post(GRANTS, headers=bearer(boss.token), json=body)
    assert first.status_code == 200
    for change in (
        {"duration_days": 366},
        {"learner_id": str(STUDENT_B)},
        {"scope": {"kind": "course", "id": str(SEED_COURSE)}},
        {"source": "promo"},
    ):
        response = await billing_staff_client.post(
            GRANTS, headers=bearer(boss.token), json={**body, **change}
        )
        assert_error(response, 409, "idempotency_key_conflict")
    assert await grant_count(admin) == 1
    stored = await admin.fetchrow(
        "SELECT learner_id, ends_at - starts_at AS lasts FROM billing.entitlements"
    )
    assert (stored["learner_id"], stored["lasts"]) == (STUDENT_A, timedelta(days=30))
    events = await audit_of(admin, boss.user_id)
    assert [(e["outcome"], e["details"]["status"]) for e in events] == [("allowed", "granted")] + [
        ("denied", "conflict")
    ] * 4, "the refusals are audited and survive the 409"
    assert all(e["target_id"] is None for e in events[1:])


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ({"source": "purchase"}, 422, "validation_error"),
        ({"duration_days": 0}, 422, "validation_error"),
        ({"duration_days": 367}, 422, "validation_error"),
        ({"duration_days": 30.5}, 422, "validation_error"),
        ({"reason_code": FREE_TEXT}, 422, "validation_error"),
        ({"reason_code": None}, 422, "validation_error"),
        ({"reason": FREE_TEXT}, 422, "validation_error"),
        ({"note": FREE_TEXT}, 422, "validation_error"),
        ({"granted_by": str(STUDENT_B)}, 422, "validation_error"),
        ({"starts_at": "2020-01-01T00:00:00Z"}, 422, "validation_error"),
        ({"ends_at": "2099-01-01T00:00:00Z"}, 422, "validation_error"),
        ({"amount_minor": 1}, 422, "validation_error"),
        ({"idempotency_key": "short"}, 422, "validation_error"),
        ({"idempotency_key": "has spaces in it"}, 422, "validation_error"),
        ({"scope": {"kind": "all", "id": str(SEED_GRADE)}}, 422, "validation_error"),
        ({"scope": {"kind": "grade", "id": None}}, 422, "validation_error"),
        ({"scope": {"kind": "lesson", "id": str(SEED_GRADE)}}, 422, "validation_error"),
        ({"learner_id": "not-a-uuid"}, 422, "validation_error"),
        ({"learner_id": str(uuid.UUID(int=7))}, 422, "invalid_entitlement_request"),
        (
            {"scope": {"kind": "grade", "id": str(uuid.UUID(int=8))}},
            422,
            "invalid_entitlement_request",
        ),
        ({"scope": {"kind": "course", "id": str(SEED_GRADE)}}, 422, "invalid_entitlement_request"),
    ],
)
async def test_invalid_grant_requests_are_refused_and_grant_nothing(
    billing_staff_client: httpx.AsyncClient,
    make_staff: Any,
    admin: asyncpg.Pool,
    change: dict[str, Any],
    status: int,
    code: str,
) -> None:
    boss = await make_staff("admin")
    response = await billing_staff_client.post(
        GRANTS, headers=bearer(boss.token), json=grant_body(**change)
    )
    assert_error(response, status, code)
    assert FREE_TEXT not in response.text, "a submitted value is never echoed back"
    assert await grant_count(admin) == 0
    assert await audit_of(admin, boss.user_id) == [], "a rolled-back call leaves no allowed row"


async def test_an_admin_cannot_grant_to_themselves(
    billing_staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    response = await billing_staff_client.post(
        GRANTS, headers=bearer(boss.token), json=grant_body(boss.user_id)
    )
    assert_error(response, 403, "forbidden")
    assert await grant_count(admin) == 0


# ------------------------------------------------------------------- revoking
async def test_an_admin_revokes_once_and_the_learner_loses_only_that_grant(
    billing_staff_client: httpx.AsyncClient,
    tokens: dict[str, str],
    make_staff: Any,
    admin: asyncpg.Pool,
) -> None:
    boss = await make_staff("admin")
    kept = await grant(admin, STUDENT_A, scope_kind="course", scope_id=SEED_COURSE)
    created = (
        await billing_staff_client.post(GRANTS, headers=bearer(boss.token), json=grant_body())
    ).json()
    target = created["entitlement_id"]

    response = await billing_staff_client.post(
        revoke_path(target), headers=bearer(boss.token), json={"reason_code": "granted_in_error"}
    )
    assert response.status_code == 200, response.text
    revoked = response.json()
    assert set(revoked) == {"entitlement_id", "replayed", "revoked_at"}
    assert (revoked["entitlement_id"], revoked["replayed"]) == (target, False)

    again = await billing_staff_client.post(
        revoke_path(target), headers=bearer(boss.token), json={"reason_code": "duplicate"}
    )
    assert again.status_code == 200
    assert again.json() == {**revoked, "replayed": True}, "the first revocation stands"
    stored = await admin.fetch(
        "SELECT revoked_by, reason_code, source_ref FROM billing.entitlement_revocations"
    )
    assert [tuple(r) for r in stored] == [(boss.user_id, "staff_revoke", "staff:granted_in_error")]

    mine = (
        await billing_staff_client.get("/v1/entitlements", headers=bearer(tokens["student_a"]))
    ).json()["entitlements"]
    assert [g["id"] for g in mine] == [str(kept)], "the other grant still gives access"
    assert await grant_count(admin) == 2, "the revoked grant row is kept (history)"

    events = (await audit_of(admin, boss.user_id))[1:]
    assert [(e["action"], e["outcome"], e["actor_kind"], str(e["target_id"])) for e in events] == [
        ("billing.entitlement.revoke", "allowed", "staff", target)
    ] * 2
    assert [e["details"] for e in events] == [
        {"replayed": False, "reason_code": "granted_in_error"},
        {"replayed": True, "reason_code": "duplicate"},
    ]


async def test_invalid_revocations_are_refused(
    billing_staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    existing = await grant(admin, STUDENT_A)
    headers = bearer(boss.token)
    unknown = await billing_staff_client.post(
        revoke_path(uuid.uuid4()), headers=headers, json={"reason_code": "correction"}
    )
    assert_error(unknown, 404, "entitlement_not_found")
    for path, body in [
        (revoke_path(existing), {"reason_code": FREE_TEXT}),
        (revoke_path(existing), {}),
        (revoke_path(existing), {"reason_code": "correction", "note": FREE_TEXT}),
        (revoke_path("not-a-uuid"), {"reason_code": "correction"}),
    ]:
        response = await billing_staff_client.post(path, headers=headers, json=body)
        assert_error(response, 422, "validation_error")
        assert FREE_TEXT not in response.text
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlement_revocations") == 0
    assert await audit_of(admin, boss.user_id) == []


# -------------------------------------------------------------------- listing
async def test_an_admin_lists_every_grant_of_one_learner_with_its_state(
    billing_staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    headers = bearer(boss.token)
    expired = await grant(admin, STUDENT_A, starts_in="-23 hours", lasts="22 hours")
    scheduled = await grant(admin, STUDENT_A, starts_in="1 day", source="promo")
    active = (await billing_staff_client.post(GRANTS, headers=headers, json=grant_body())).json()[
        "entitlement_id"
    ]
    revoked = (
        await billing_staff_client.post(
            GRANTS,
            headers=headers,
            json=grant_body(scope={"kind": "course", "id": str(SEED_COURSE)}),
        )
    ).json()["entitlement_id"]
    await billing_staff_client.post(
        revoke_path(revoked), headers=headers, json={"reason_code": "learner_request"}
    )
    someone_else = await grant(admin, STUDENT_B)

    response = await billing_staff_client.get(list_path(STUDENT_A), headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["learner_id"] == str(STUDENT_A)
    by_id = {g["id"]: g for g in body["grants"]}
    assert {gid: g["state"] for gid, g in by_id.items()} == {
        str(expired): "expired",
        str(scheduled): "scheduled",
        active: "active",
        revoked: "revoked",
    }
    assert str(someone_else) not in response.text
    item = by_id[revoked]
    assert set(item) == {
        "id", "scope", "starts_at", "ends_at", "source", "state", "order_id",
        "granted_by", "created_at", "revoked_at", "revocation_reason",
    }  # fmt: skip
    assert item["scope"] == {"kind": "course", "id": str(SEED_COURSE)}
    assert (item["granted_by"], item["revocation_reason"], item["order_id"]) == (
        str(boss.user_id),
        "staff_revoke",
        None,
    )
    assert item["revoked_at"] is not None and by_id[active]["revoked_at"] is None

    nobody = await billing_staff_client.get(list_path(uuid.uuid4()), headers=headers)
    assert nobody.status_code == 200 and nobody.json()["grants"] == []
    assert_error(
        await billing_staff_client.get(
            "/v1/staff/billing/learners/not-a-uuid/grants", headers=headers
        ),
        422,
        "validation_error",
    )

    reads = [e for e in await audit_of(admin, boss.user_id) if e["action"].endswith(".list")]
    first = reads[0]
    assert (first["target_kind"], first["target_id"], first["outcome"], first["details"]) == (
        "learner",
        STUDENT_A,
        "allowed",
        {"count": 4},
    )
    assert len(reads) == 2, "every read of a learner's grants is audited"


# ---------------------------------------------------------- audit hygiene, roles
async def test_no_free_text_and_no_client_key_ever_reaches_the_audit_log(
    billing_staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    headers = bearer(boss.token)
    body = grant_body(idempotency_key="client-chosen-key-0001")
    created = (await billing_staff_client.post(GRANTS, headers=headers, json=body)).json()
    await billing_staff_client.post(GRANTS, headers=headers, json={**body, "duration_days": 60})
    await billing_staff_client.post(GRANTS, headers=headers, json={**body, "reason": FREE_TEXT})
    await billing_staff_client.post(
        revoke_path(created["entitlement_id"]), headers=headers, json={"reason_code": "misuse"}
    )
    await billing_staff_client.get(list_path(STUDENT_A), headers=headers)

    events = await audit_of(admin, boss.user_id)
    assert [e["action"].rsplit(".", 1)[1] for e in events] == ["grant", "grant", "revoke", "list"]
    allowed_keys = {
        "status", "replayed", "learner_id", "scope_kind", "scope_id", "duration_days",
        "source", "reason_code", "count",
    }  # fmt: skip
    for event in events:
        assert set(event["details"]) <= allowed_keys
        blob = json.dumps(event["details"])
        for value in event["details"].values():
            assert not isinstance(value, str) or not any(ch.isspace() for ch in value), blob
        assert "client-chosen-key" not in blob and "asked nicely" not in blob


async def test_a_deactivated_admin_role_stops_working_at_once(
    billing_staff_client: httpx.AsyncClient, make_staff: Any, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    headers = bearer(boss.token)
    assert (
        await billing_staff_client.post(GRANTS, headers=headers, json=grant_body())
    ).status_code == 200
    await set_role_active(admin, boss.user_id, "admin", False)
    for method, path, kwargs in three_routes():
        response = await billing_staff_client.request(method, path, headers=headers, **kwargs)
        assert_error(response, 403, "forbidden")
    assert await grant_count(admin) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM billing.entitlements",
        "SELECT * FROM billing.orders",
        "SELECT * FROM billing.provider_events",
        "INSERT INTO billing.entitlements (learner_id, scope_kind, starts_at, ends_at, source, idempotency_key) "
        "VALUES ('a0000000-0000-4000-8000-000000000001', 'all', now(), now() + interval '10 years', 'gift', 'staff-forged-1')",
        "UPDATE billing.entitlements SET ends_at = ends_at + interval '10 years'",
        "DELETE FROM billing.entitlement_revocations",
        "SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), "
        "now() + interval '3000 days', 'gift', NULL, 'staff-forged-2', NULL)",
        "SELECT billing.revoke_entitlement(gen_random_uuid(), 'staff_revoke', NULL)",
        "SELECT billing.apply_provider_event('mock', 'staff-forged-event', 'payment.succeeded', '{}'::jsonb)",
        "SELECT billing.create_order('synthetic-all-30', 'HTG', 'mock', 'staff-forged-order')",
        "SELECT billing.erase_learner('a0000000-0000-4000-8000-000000000001')",
        "INSERT INTO billing.providers (code, is_simulated, is_enabled) VALUES ('mock', true, true)",
        "INSERT INTO billing.plan_prices (plan_id, currency, amount_minor) VALUES (gen_random_uuid(), 'HTG', 1)",
    ],
)
async def test_even_arbitrary_sql_on_the_staff_connection_is_limited_to_the_three_functions(
    billing_staff_app: FastAPI, make_staff: Any, admin: asyncpg.Pool, statement: str
) -> None:
    """Worst case on the staff side: SQL of the attacker's choice, as a real admin."""
    boss = await make_staff("admin")
    await grant(admin, STUDENT_A)
    with pytest.raises(DBAPIError) as caught:
        async with billing_staff_app.state.staff_db.transaction(boss.user_id) as conn:
            await conn.execute(text(statement))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement
    assert await grant_count(admin) == 1
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlement_revocations") == 0


async def test_the_staff_functions_check_the_role_again_in_the_database(
    billing_staff_app: FastAPI, staff_tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """The API gate is not the only gate: the same call as an editor, straight
    on the staff connection, is refused by PostgreSQL."""
    editor = uuid.UUID("a0000000-0000-4000-8000-000000000003")
    for statement in (
        "SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, 'gift', 'goodwill', 'editor-direct-1')",
        "SELECT billing.staff_list_entitlements('a0000000-0000-4000-8000-000000000001')",
        "SELECT billing.staff_revoke_entitlement(gen_random_uuid(), 'correction')",
    ):
        for actor in (editor, STUDENT_A, None):
            with pytest.raises(DBAPIError) as caught:
                async with billing_staff_app.state.staff_db.transaction(actor) as conn:
                    await conn.execute(text(statement))
            assert getattr(caught.value.orig, "sqlstate", None) == "42501", (statement, actor)
    assert await grant_count(admin) == 0
