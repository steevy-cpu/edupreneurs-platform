"""Authentication with REAL local Supabase-issued tokens, and /v1/me."""

from __future__ import annotations

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.auth.jwks import StaticKeyProvider
from edu_api.config import Settings
from edu_api.main import create_app
from tests.helpers import (
    EDITOR,
    STUDENT_A,
    STUDENT_B,
    TEST_ISSUER,
    TEST_KID,
    bearer,
    make_token,
    new_ec_key,
    public_jwk,
)

pytestmark = pytest.mark.integration


async def test_real_token_resolves_the_caller(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    a = await client.get("/v1/me", headers=bearer(tokens["student_a"]))
    b = await client.get("/v1/me", headers=bearer(tokens["student_b"]))
    assert a.status_code == b.status_code == 200
    assert a.json()["user_id"] == str(STUDENT_A)
    assert a.json()["preferred_locale"] == "fr"
    assert a.json()["grade"]["code"] == "9AF"
    assert b.json()["user_id"] == str(STUDENT_B)
    assert b.json()["preferred_locale"] == "ht"
    assert b.json()["grade"]["label"] == "9èm ane fondamantal"
    assert a.headers["x-request-id"] != b.headers["x-request-id"]


async def test_identity_cannot_be_chosen_by_the_client(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """Query params, headers and bodies naming another user are simply not inputs."""
    response = await client.get(
        "/v1/me",
        params={"user_id": str(STUDENT_B), "learner_id": str(STUDENT_B)},
        headers={**bearer(tokens["student_a"]), "X-User-Id": str(STUDENT_B)},
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == str(STUDENT_A)


async def test_first_contact_creates_only_the_callers_profile(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    before = await admin.fetchval(
        "SELECT count(*) FROM app.learner_profiles WHERE user_id <> $1", EDITOR
    )
    first = await client.get("/v1/me", headers=bearer(tokens["editor"]))
    second = await client.get("/v1/me", headers=bearer(tokens["editor"]))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["user_id"] == str(EDITOR)
    assert first.json()["grade"] is None
    assert (
        await admin.fetchval("SELECT count(*) FROM app.learner_profiles WHERE user_id = $1", EDITOR)
        == 1
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.learner_profiles WHERE user_id <> $1", EDITOR
        )
        == before
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/me",
        "/v1/catalog?locale=fr",
        "/v1/sync/pull",
        "/v1/lessons/b0000000-0000-4000-8000-000000000005?locale=fr",
    ],
)
async def test_missing_token_is_401_everywhere(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 401
    body = response.json()["error"]
    assert body["code"] == "unauthenticated"
    assert body["request_id"] == response.headers["x-request-id"]
    assert response.headers["www-authenticate"] == "Bearer"


async def test_push_without_token_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.post("/v1/sync/push", json={"ops": []})).status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer   ",
        "Basic dXNlcjpwYXNz",
        "Bearer not.a.jwt",
        "Token abc",
        "bearer a.b.c",
    ],
)
async def test_malformed_authorization_headers(client: httpx.AsyncClient, header: str) -> None:
    response = await client.get("/v1/me", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_real_token_with_altered_signature_or_payload(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    header, payload, signature = tokens["student_a"].split(".")
    flipped = signature[:-2] + ("AA" if not signature.endswith("AA") else "BB")
    swapped_payload = tokens["student_b"].split(".")[1]  # B's claims under A's signature
    for forged in (f"{header}.{payload}.{flipped}", f"{header}.{swapped_payload}.{signature}"):
        response = await client.get("/v1/me", headers=bearer(forged))
        assert response.status_code == 401, forged[:20]


async def test_token_signed_by_an_attacker_key_with_the_real_kid(
    client: httpx.AsyncClient, tokens: dict[str, str], settings: Settings
) -> None:
    import jwt

    real_kid = jwt.get_unverified_header(tokens["student_a"])["kid"]
    forged = make_token(new_ec_key(), kid=real_kid, iss=settings.auth_issuer, sub=str(STUDENT_B))
    assert (await client.get("/v1/me", headers=bearer(forged))).status_code == 401


async def test_project_api_keys_are_not_user_tokens(
    client: httpx.AsyncClient, local_env: dict[str, str]
) -> None:
    """The anon / service keys of the stack are JWTs too; they must not authenticate."""
    names = (
        "LOCAL_SUPABASE_PUBLISHABLE_KEY",
        "LOCAL_SUPABASE_SECRET_KEY",
        "LOCAL_SUPABASE_ANON_JWT",
        "LOCAL_SUPABASE_SERVICE_ROLE_JWT",
    )
    for name in names:
        assert local_env.get(name), f"{name} missing from .env; run `make db-reset`"
        response = await client.get("/v1/me", headers=bearer(local_env[name]))
        assert response.status_code == 401, name


# --- correctly SIGNED tokens that must still be refused (test key injected) ---------
@pytest.fixture(scope="module")
async def static_key_app(local_env: dict[str, str]):  # type: ignore[no-untyped-def]
    from tests.conftest import build_settings

    key = new_ec_key()
    application: FastAPI = create_app(
        build_settings(local_env, auth_issuer=TEST_ISSUER),
        key_provider=StaticKeyProvider({TEST_KID: public_jwk(key)}),
    )
    yield application, key
    await application.state.db.dispose()


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": 1_000_000_000, "iat": 999_999_000},  # expired
        {"iss": "https://evil.example/auth/v1"},  # wrong issuer
        {"aud": "another-audience"},  # wrong audience
        {"role": "service_role"},  # wrong token type
        {"role": "anon"},
        {"is_anonymous": True},
        {"sub": "not-a-uuid"},
    ],
    ids=[
        "expired",
        "wrong-issuer",
        "wrong-audience",
        "service-role",
        "anon-role",
        "anonymous",
        "bad-sub",
    ],
)
async def test_signed_but_unacceptable_tokens_are_401(static_key_app, overrides) -> None:  # type: ignore[no-untyped-def]
    application, key = static_key_app
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        good = await http.get("/v1/me", headers=bearer(make_token(key)))
        bad = await http.get("/v1/me", headers=bearer(make_token(key, **overrides)))
    assert good.status_code == 200 and good.json()["user_id"] == str(STUDENT_A)
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "unauthenticated"
    assert "expired" not in bad.text and "issuer" not in bad.text  # reason is not disclosed
