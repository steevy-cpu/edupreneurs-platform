"""Role administration through the staff API (B2): admin only, never to
oneself, never the last admin, every change audited."""

# ruff: noqa: F811  (fixtures imported from tests.staff_fixtures are requested by name)
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest

from tests.helpers import bearer
from tests.staff_fixtures import (  # noqa: F401
    MakeStaff,
    create_account,
    make_staff,
    remove_account,
    reset_denial_windows,
    staff_app,
    staff_client,
    staff_settings,
)

pytestmark = pytest.mark.integration
S = "/v1/staff"


@pytest.fixture(autouse=True)
async def only_this_tests_admins(admin: asyncpg.Pool) -> AsyncIterator[None]:
    """ "Last admin" is a statement about the whole database: start each test
    without any other active admin, and put things back afterwards."""
    await reset_denial_windows(admin)
    parked = await admin.fetch(
        "UPDATE app.staff_roles SET is_active = false WHERE role = 'admin' AND is_active RETURNING user_id"
    )
    yield
    for row in parked:
        await admin.execute(
            "UPDATE app.staff_roles SET is_active = true WHERE role = 'admin' AND user_id = $1",
            row["user_id"],
        )


@pytest.fixture
async def learner(
    local_env: dict[str, str], admin: asyncpg.Pool
) -> AsyncIterator[tuple[uuid.UUID, str]]:
    """A fresh synthetic account without any role."""
    user_id, _, token = await create_account(local_env)
    yield user_id, token
    await remove_account(admin, local_env, user_id)


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


async def role_events(admin: asyncpg.Pool, target: uuid.UUID) -> list[tuple[str, str, uuid.UUID]]:
    rows = await admin.fetch(
        "SELECT action, details, actor_id FROM app.audit_events "
        "WHERE target_kind = 'user' AND target_id = $1 ORDER BY created_at, id",
        target,
    )
    return [(row["action"], json.loads(row["details"])["role"], row["actor_id"]) for row in rows]


async def test_an_admin_grants_and_revokes_a_role_and_it_takes_effect_at_once(
    staff_client: httpx.AsyncClient,
    make_staff: MakeStaff,
    learner: tuple[uuid.UUID, str],
    admin: asyncpg.Pool,
) -> None:
    boss = await make_staff("admin")
    user_id, token = learner
    path = f"{S}/users/{user_id}/roles/publisher"
    assert_error(await staff_client.get(f"{S}/me", headers=bearer(token)), 403, "forbidden")

    granted = await staff_client.put(path, headers=bearer(boss.token))
    assert (granted.status_code, granted.json()) == (
        200,
        {"user_id": str(user_id), "role": "publisher", "is_active": True, "changed": True},
    )
    # the SAME access token now works on the staff side: roles are read per request
    me = await staff_client.get(f"{S}/me", headers=bearer(token))
    assert (me.status_code, me.json()["roles"]) == (200, ["publisher"])
    again = await staff_client.put(path, headers=bearer(boss.token))
    assert again.json()["changed"] is False

    listing = await staff_client.get(f"{S}/roles", headers=bearer(boss.token))
    mine = [a for a in listing.json()["assignments"] if a["user_id"] == str(user_id)]
    assert [(a["role"], a["is_active"], a["granted_by"]) for a in mine] == [
        ("publisher", True, str(boss.user_id))
    ]
    assert "@" not in listing.text, "ids only: no e-mail address in the listing"

    revoked = await staff_client.delete(path, headers=bearer(boss.token))
    assert (revoked.status_code, revoked.json()["is_active"], revoked.json()["changed"]) == (
        200,
        False,
        True,
    )
    assert_error(await staff_client.get(f"{S}/me", headers=bearer(token)), 403, "forbidden")
    assert (await staff_client.delete(path, headers=bearer(boss.token))).json()["changed"] is False

    # two changes, two audit events; the two no-ops wrote none
    assert await role_events(admin, user_id) == [
        ("staff_role.grant", "publisher", boss.user_id),
        ("staff_role.revoke", "publisher", boss.user_id),
    ]
    # a new grant reactivates the kept row
    assert (await staff_client.put(path, headers=bearer(boss.token))).json()["changed"] is True
    assert (
        await admin.fetchval("SELECT count(*) FROM app.staff_roles WHERE user_id = $1", user_id)
        == 1
    )


async def test_nobody_can_grant_themselves_a_role(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    for role in ("reviewer", "publisher", "editor", "admin"):
        refused = await staff_client.put(
            f"{S}/users/{boss.user_id}/roles/{role}", headers=bearer(boss.token)
        )
        assert_error(refused, 403, "forbidden")
    assert [
        row["role"]
        for row in await admin.fetch(
            "SELECT role FROM app.staff_roles WHERE user_id = $1", boss.user_id
        )
    ] == ["admin"]
    assert await role_events(admin, boss.user_id) == []
    denied = await admin.fetch(
        "SELECT details FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied'",
        boss.user_id,
    )
    assert [json.loads(row["details"]) for row in denied] == [
        {
            "method": "PUT",
            "route": "/v1/staff/users/{user_id}/roles/{role}",
            "check": "function",
            "held_roles": ["admin"],
        }
    ], "the attempt is on record (one event per minute per account)"

    # two admins can give each other roles; that is the intended path
    other = await make_staff("admin")
    granted = await staff_client.put(
        f"{S}/users/{boss.user_id}/roles/reviewer", headers=bearer(other.token)
    )
    assert granted.json()["changed"] is True


async def test_only_admins_administer_roles(
    staff_client: httpx.AsyncClient,
    make_staff: MakeStaff,
    learner: tuple[uuid.UUID, str],
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    user_id, learner_token = learner
    others = [await make_staff(role) for role in ("editor", "reviewer", "publisher")]
    everything_but_admin = await make_staff("editor", "reviewer", "publisher")
    callers = [a.token for a in (*others, everything_but_admin)] + [
        learner_token,
        tokens["student_a"],
    ]
    for token in callers:
        for method, path in (
            ("GET", f"{S}/roles"),
            ("PUT", f"{S}/users/{user_id}/roles/editor"),
            ("PUT", f"{S}/users/{user_id}/roles/admin"),
            ("DELETE", f"{S}/users/{others[0].user_id}/roles/editor"),
        ):
            assert_error(
                await staff_client.request(method, path, headers=bearer(token)), 403, "forbidden"
            )
    assert_error(await staff_client.put(f"{S}/users/{user_id}/roles/admin"), 401, "unauthenticated")
    assert (
        await admin.fetchval("SELECT count(*) FROM app.staff_roles WHERE user_id = $1", user_id)
        == 0
    )
    assert (
        await admin.fetchval(
            "SELECT is_active FROM app.staff_roles WHERE user_id = $1 AND role = 'editor'",
            others[0].user_id,
        )
        is True
    )


async def test_the_last_admin_cannot_be_revoked(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, admin: asyncpg.Pool
) -> None:
    first = await make_staff("admin")
    own = f"{S}/users/{first.user_id}/roles/admin"
    assert_error(await staff_client.delete(own, headers=bearer(first.token)), 409, "last_admin")
    assert (await staff_client.get(f"{S}/me", headers=bearer(first.token))).json()["roles"] == [
        "admin"
    ]

    second = await make_staff()  # no role yet: appointed through the API
    appointed = await staff_client.put(
        f"{S}/users/{second.user_id}/roles/admin", headers=bearer(first.token)
    )
    assert appointed.json()["changed"] is True

    # with a second admin, stepping down is allowed
    stepped_down = await staff_client.delete(own, headers=bearer(first.token))
    assert (stepped_down.status_code, stepped_down.json()["changed"]) == (200, True)
    assert_error(
        await staff_client.get(f"{S}/roles", headers=bearer(first.token)), 403, "forbidden"
    )
    # ...and now the second one is the last
    assert_error(
        await staff_client.delete(
            f"{S}/users/{second.user_id}/roles/admin", headers=bearer(second.token)
        ),
        409,
        "last_admin",
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.staff_roles WHERE role = 'admin' AND is_active"
        )
        == 1
    )


async def test_two_admins_revoking_each_other_at_the_same_time_leave_one_admin(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, admin: asyncpg.Pool
) -> None:
    for _ in range(5):
        one = await make_staff("admin")
        two = await make_staff("admin")
        results = await asyncio.gather(
            staff_client.delete(f"{S}/users/{two.user_id}/roles/admin", headers=bearer(one.token)),
            staff_client.delete(f"{S}/users/{one.user_id}/roles/admin", headers=bearer(two.token)),
        )
        statuses = sorted(r.status_code for r in results)
        assert statuses == [200, 403], [r.text for r in results]
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM app.staff_roles WHERE role = 'admin' AND is_active "
                "AND user_id = ANY($1::uuid[])",
                [one.user_id, two.user_id],
            )
            == 1
        )
        # leave no admin behind for the next round
        await admin.execute(
            "UPDATE app.staff_roles SET is_active = false WHERE user_id = ANY($1::uuid[])",
            [one.user_id, two.user_id],
        )


async def test_bad_targets_and_roles(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, learner: tuple[uuid.UUID, str]
) -> None:
    boss = await make_staff("admin")
    user_id, _ = learner
    headers = bearer(boss.token)
    assert_error(
        await staff_client.put(f"{S}/users/{uuid.uuid4()}/roles/editor", headers=headers),
        404,
        "user_not_found",
    )
    assert_error(
        await staff_client.delete(f"{S}/users/{user_id}/roles/editor", headers=headers),
        404,
        "role_not_assigned",
    )
    assert_error(
        await staff_client.put(f"{S}/users/{user_id}/roles/superuser", headers=headers),
        422,
        "validation_error",
    )
    assert_error(
        await staff_client.put(f"{S}/users/not-a-uuid/roles/editor", headers=headers),
        422,
        "validation_error",
    )
    assert_error(
        await staff_client.get(f"{S}/roles", params={"limit": 0}, headers=headers),
        422,
        "validation_error",
    )
