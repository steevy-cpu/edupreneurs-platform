"""`PATCH /v1/me` — the learner edits their own study settings (identity lane, slice 1)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from tests.helpers import STUDENT_A, STUDENT_B, bearer

if TYPE_CHECKING:
    from tests.account_fixtures import SyntheticLearner

pytestmark = pytest.mark.integration
#: Registers the lane's fixtures (account_app, account_client, learners, ...).
pytest_plugins = ["tests.account_fixtures"]

SEED_GRADE_ID = uuid.UUID("b0000000-0000-4000-8000-000000000001")
SEED_GRADE_CODE = "9AF"

PROFILE_ROW = (
    "SELECT grade_id, preferred_locale, display_name, updated_at "
    "FROM app.learner_profiles WHERE user_id = $1"
)


# ------------------------------------------------------------- feature flag
async def test_with_the_flags_off_no_account_route_exists(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """The shared application runs with default settings: everything is off."""
    before = await admin.fetchrow(PROFILE_ROW, STUDENT_A)
    patched = await client.patch(
        "/v1/me", json={"display_name": "x"}, headers=bearer(tokens["student_a"])
    )
    assert patched.status_code == 405
    assert patched.json()["error"]["code"] == "method_not_allowed"
    assert await admin.fetchrow(PROFILE_ROW, STUDENT_A) == before


async def test_enabled_routes_follow_the_api_conventions(account_app: FastAPI) -> None:
    spec = account_app.openapi()
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    checked = 0
    for path in ("/v1/me",):
        for operation in spec["paths"][path].values():
            assert operation["security"] == [{"HTTPBearer": []}], path
            for status, response in operation["responses"].items():
                if status != "200":
                    assert response["content"]["application/json"]["schema"] == error_ref
                    checked += 1
    assert checked >= 3
    assert "HTTPValidationError" not in spec["components"]["schemas"], "one error shape only"
    patch_schema = spec["components"]["schemas"]["ProfilePatch"]
    assert patch_schema["additionalProperties"] is False
    assert set(patch_schema["properties"]) == {"grade_code", "preferred_locale", "display_name"}
    # GET /v1/me is unchanged by this lane.
    assert set(spec["components"]["schemas"]["MeResponse"]["properties"]) == {
        "user_id",
        "preferred_locale",
        "display_name",
        "grade",
        "created_at",
    }


# ------------------------------------------------------------------ editing
async def test_learner_edits_grade_language_and_name(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    x = learners["x"]
    first = await account_client.get("/v1/me", headers=x.headers)
    assert first.status_code == 200
    assert first.json() == {
        "user_id": str(x.user_id),
        "preferred_locale": "fr",
        "display_name": None,
        "grade": None,
        "created_at": first.json()["created_at"],
    }

    grade = await account_client.patch(
        "/v1/me", json={"grade_code": SEED_GRADE_CODE}, headers=x.headers
    )
    assert grade.status_code == 200, grade.text
    assert grade.json()["grade"] == {
        "id": str(SEED_GRADE_ID),
        "code": "9AF",
        "label": "9e année fondamentale",
    }
    assert grade.json()["preferred_locale"] == "fr" and grade.json()["display_name"] is None

    locale = await account_client.patch(
        "/v1/me", json={"preferred_locale": "ht"}, headers=x.headers
    )
    assert locale.status_code == 200
    assert locale.json()["preferred_locale"] == "ht"
    assert locale.json()["grade"]["label"] == "9èm ane fondamantal"  # label follows the language

    name = await account_client.patch(
        "/v1/me", json={"display_name": "  Ele\u0300v sentetik X \t"}, headers=x.headers
    )
    assert name.status_code == 200
    assert name.json()["display_name"] == "Elèv sentetik X"  # trimmed, NFC

    again = await account_client.get("/v1/me", headers=x.headers)
    assert again.json() == name.json()
    assert again.json()["created_at"] == first.json()["created_at"]


async def test_several_fields_in_one_request_and_clearing_the_name(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    x = learners["x"]
    both = await account_client.patch(
        "/v1/me",
        json={"grade_code": "9AF", "preferred_locale": "ht", "display_name": "X" * 80},
        headers=x.headers,
    )
    assert both.status_code == 200
    assert both.json()["display_name"] == "X" * 80
    assert (both.json()["preferred_locale"], both.json()["grade"]["code"]) == ("ht", "9AF")

    cleared = await account_client.patch("/v1/me", json={"display_name": None}, headers=x.headers)
    assert cleared.status_code == 200
    assert cleared.json()["display_name"] is None
    assert cleared.json()["grade"]["code"] == "9AF"  # omitted fields are kept
    assert cleared.json()["preferred_locale"] == "ht"


async def test_first_contact_through_patch_creates_only_the_callers_profile(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    await admin.execute("DELETE FROM app.learner_profiles WHERE user_id = $1", x.user_id)
    others = await admin.fetchval(
        "SELECT count(*) FROM app.learner_profiles WHERE user_id <> $1", x.user_id
    )
    response = await account_client.patch(
        "/v1/me", json={"preferred_locale": "ht"}, headers=x.headers
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == str(x.user_id)
    assert response.json()["preferred_locale"] == "ht"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.learner_profiles WHERE user_id <> $1", x.user_id
        )
        == others
    )


async def test_repeating_a_request_changes_nothing(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    body = {"grade_code": "9AF", "preferred_locale": "ht", "display_name": "Synthetic X"}
    first = await account_client.patch("/v1/me", json=body, headers=x.headers)
    stamp = (await admin.fetchrow(PROFILE_ROW, x.user_id))["updated_at"]
    second = await account_client.patch("/v1/me", json=body, headers=x.headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert (await admin.fetchrow(PROFILE_ROW, x.user_id))["updated_at"] == stamp

    changed = await account_client.patch(
        "/v1/me", json={"preferred_locale": "fr"}, headers=x.headers
    )
    assert changed.status_code == 200
    assert (await admin.fetchrow(PROFILE_ROW, x.user_id))["updated_at"] > stamp


# --------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "body",
    [
        {"display_name": ""},
        {"display_name": "   "},
        {"display_name": "x" * 81},
        {"display_name": "two\nlines"},
        {"display_name": "tab\tinside"},
        {"display_name": "c1\u0085control"},
        {"display_name": "line\u2028separator"},
        {"display_name": "nul\u0000byte"},
        {"display_name": 12},
        {"grade_code": None},
        {"grade_code": "9af"},
        {"grade_code": ""},
        {"preferred_locale": None},
        {"preferred_locale": "en"},
        {"user_id": str(STUDENT_B)},
        {"display_name": "ok", "user_id": str(STUDENT_B)},
        {"grade_id": str(SEED_GRADE_ID)},
        {"created_at": "2020-01-01T00:00:00Z"},
        {"display_name": "ok", "role": "admin"},
        {"entitlement": "paid"},
        ["display_name"],
        "display_name",
    ],
)
async def test_invalid_bodies_are_422_and_change_nothing(
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
    admin: asyncpg.Pool,
    body: object,
) -> None:
    x = learners["x"]
    before = await admin.fetchrow(PROFILE_ROW, x.user_id)
    response = await account_client.patch("/v1/me", json=body, headers=x.headers)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"] == response.headers["x-request-id"]
    assert await admin.fetchrow(PROFILE_ROW, x.user_id) == before


async def test_validation_errors_do_not_echo_the_submitted_name(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    secret_looking = "Marker-7f3a9c\nsecond line"
    response = await account_client.patch(
        "/v1/me", json={"display_name": secret_looking}, headers=learners["x"].headers
    )
    assert response.status_code == 422
    assert "Marker-7f3a9c" not in response.text
    assert response.json()["error"]["details"][0]["loc"] == ["body", "display_name"]


async def test_empty_patch_is_rejected(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    response = await account_client.patch("/v1/me", json={}, headers=learners["x"].headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_patch"


async def test_grade_must_exist_and_be_active(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    inactive_code = "ZZ" + uuid.uuid4().hex[:5].upper()
    sort_order = 20_000 + uuid.uuid4().int % 10_000
    inactive_id = await admin.fetchval(
        "INSERT INTO app.grades (code, sort_order, labels, is_active) "
        'VALUES ($1, $2, \'{"fr": "Classe inactive (synthétique)"}\', false) RETURNING id',
        inactive_code,
        sort_order,
    )
    try:
        before = await admin.fetchrow(PROFILE_ROW, x.user_id)
        answers = []
        for code in ("NOPE1", inactive_code):
            response = await account_client.patch(
                "/v1/me", json={"grade_code": code, "display_name": "kept out"}, headers=x.headers
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "grade_not_available"
            answers.append(response.json()["error"]["message"])
        assert answers[0] == answers[1], "unknown and inactive are indistinguishable"
        # The whole request is refused: the valid display name was not applied.
        assert await admin.fetchrow(PROFILE_ROW, x.user_id) == before

        # A learner already in a grade that is later deactivated keeps it, and
        # can still edit other fields.
        await admin.execute("UPDATE app.grades SET is_active = true WHERE id = $1", inactive_id)
        ok = await account_client.patch(
            "/v1/me", json={"grade_code": inactive_code}, headers=x.headers
        )
        assert ok.status_code == 200 and ok.json()["grade"]["code"] == inactive_code
        await admin.execute("UPDATE app.grades SET is_active = false WHERE id = $1", inactive_id)
        other = await account_client.patch(
            "/v1/me", json={"display_name": "still fine"}, headers=x.headers
        )
        assert other.status_code == 200
        assert other.json()["display_name"] == "still fine"
        row = await admin.fetchrow(PROFILE_ROW, x.user_id)
        assert row["grade_id"] == inactive_id
    finally:
        await admin.execute(
            "UPDATE app.learner_profiles SET grade_id = NULL WHERE grade_id = $1", inactive_id
        )
        await admin.execute("DELETE FROM app.grades WHERE id = $1", inactive_id)


# ---------------------------------------------------------------- isolation
async def test_a_learner_can_only_ever_edit_their_own_profile(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x, y = learners["x"], learners["y"]
    await account_client.get("/v1/me", headers=y.headers)  # make sure Y has a profile row
    y_before = await admin.fetchrow(PROFILE_ROW, y.user_id)
    seed_before = await admin.fetch(
        "SELECT user_id, grade_id, preferred_locale, display_name, updated_at "
        "FROM app.learner_profiles WHERE user_id = ANY($1::uuid[]) ORDER BY user_id",
        [STUDENT_A, STUDENT_B],
    )

    # Naming another user anywhere in the request is either rejected or ignored.
    response = await account_client.patch(
        "/v1/me",
        params={"user_id": str(y.user_id), "learner_id": str(y.user_id)},
        json={"display_name": "X only", "preferred_locale": "ht", "grade_code": "9AF"},
        headers={**x.headers, "X-User-Id": str(y.user_id)},
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == str(x.user_id)

    assert await admin.fetchrow(PROFILE_ROW, y.user_id) == y_before
    y_view = await account_client.get("/v1/me", headers=y.headers)
    assert y_view.json()["display_name"] is None and y_view.json()["grade"] is None
    assert (
        await admin.fetch(
            "SELECT user_id, grade_id, preferred_locale, display_name, updated_at "
            "FROM app.learner_profiles WHERE user_id = ANY($1::uuid[]) ORDER BY user_id",
            [STUDENT_A, STUDENT_B],
        )
        == seed_before
    )


async def test_account_switch_on_one_client_never_mixes_profiles(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    x, y = learners["x"], learners["y"]
    for round_number in range(3):
        px = await account_client.patch(
            "/v1/me", json={"display_name": f"X round {round_number}"}, headers=x.headers
        )
        py = await account_client.patch(
            "/v1/me", json={"display_name": f"Y round {round_number}"}, headers=y.headers
        )
        assert (px.json()["user_id"], py.json()["user_id"]) == (str(x.user_id), str(y.user_id))
        gx = await account_client.get("/v1/me", headers=x.headers)
        gy = await account_client.get("/v1/me", headers=y.headers)
        assert gx.json()["display_name"] == f"X round {round_number}"
        assert gy.json()["display_name"] == f"Y round {round_number}"


async def test_patch_requires_a_token(account_client: httpx.AsyncClient) -> None:
    response = await account_client.patch("/v1/me", json={"display_name": "x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["www-authenticate"] == "Bearer"


# ------------------------------------------- the database boundary still holds
async def test_api_role_still_cannot_update_profiles_directly(
    account_app: FastAPI, learners: dict[str, SyntheticLearner]
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    x = learners["x"]
    db = account_app.state.db
    for statement in (
        "UPDATE app.learner_profiles SET display_name = 'direct'",
        "SELECT account.audit_seam('x.y', 'z', NULL, 'allowed')",
    ):
        with pytest.raises(DBAPIError) as caught:
            async with db.transaction(x.user_id) as conn:
                await conn.execute(text(statement))
        assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement


async def test_account_schema_is_not_reachable_through_the_supabase_data_api(
    local_env: dict[str, str], learners: dict[str, SyntheticLearner]
) -> None:
    rest = local_env["LOCAL_SUPABASE_URL"] + "/rest/v1"
    x = learners["x"]
    credentials = {
        "publishable key only": {"apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
        "signed-in learner": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {x.token}",
        },
        "SECRET service key": {"apikey": local_env["LOCAL_SUPABASE_SECRET_KEY"]},
    }
    async with httpx.AsyncClient(timeout=10) as http:
        for label, headers in credentials.items():
            for function, arguments in (
                ("update_own_profile", {"p_patch": {"display_name": "via data api"}}),
            ):
                for profile in ({"Content-Profile": "account"}, {}):
                    rpc = await http.post(
                        f"{rest}/rpc/{function}", headers={**headers, **profile}, json=arguments
                    )
                    assert rpc.status_code >= 400, (label, function, rpc.text[:200])
        exposed = (await http.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    assert "update_own_profile" not in exposed
