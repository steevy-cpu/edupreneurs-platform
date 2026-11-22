"""JWT verification failure modes, using throw-away keys (no network, no DB)."""

from __future__ import annotations

import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from edu_api.auth.jwks import StaticKeyProvider
from edu_api.auth.verifier import InvalidToken, TokenVerifier
from tests.helpers import (
    STUDENT_A,
    TEST_AUDIENCE,
    TEST_ISSUER,
    TEST_KID,
    make_token,
    new_ec_key,
    public_jwk,
)

KEY = new_ec_key()
OTHER_KEY = new_ec_key()


def verifier(leeway_s: int = 0) -> TokenVerifier:
    return TokenVerifier(
        StaticKeyProvider({TEST_KID: public_jwk(KEY)}),
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        algorithms=("ES256",),
        leeway_s=leeway_s,
    )


async def reason(token: str, **kwargs: int) -> str:
    with pytest.raises(InvalidToken) as caught:
        await verifier(**kwargs).verify(token)
    return caught.value.reason


async def test_valid_token_yields_the_subject() -> None:
    principal = await verifier().verify(make_token(KEY))
    assert principal.user_id == STUDENT_A


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c.d", "x" * 5000])
async def test_malformed_tokens(token: str) -> None:
    assert (await reason(token)).startswith("malformed")


async def test_expired() -> None:
    now = int(time.time())
    assert await reason(make_token(KEY, iat=now - 7200, exp=now - 3600)) == "expired"


async def test_expiry_leeway_is_bounded() -> None:
    now = int(time.time())
    token = make_token(KEY, iat=now - 100, exp=now - 10)
    assert (await verifier(leeway_s=30).verify(token)).user_id == STUDENT_A
    assert await reason(token, leeway_s=5) == "expired"


async def test_wrong_issuer() -> None:
    assert await reason(make_token(KEY, iss="https://evil.example/auth/v1")) == "wrong_issuer"


async def test_wrong_audience() -> None:
    assert await reason(make_token(KEY, aud="some-other-api")) == "wrong_audience"


async def test_signed_with_another_key() -> None:
    assert await reason(make_token(OTHER_KEY)) == "bad_signature"


async def test_altered_payload() -> None:
    header, payload, signature = make_token(KEY).split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = "a0000000-0000-4000-8000-000000000002"  # try to become Student B
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    assert await reason(f"{header}.{forged}.{signature}") == "bad_signature"


async def test_unsigned_alg_none() -> None:
    header = (
        base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "kid": TEST_KID, "typ": "JWT"}).encode()
        )
        .decode()
        .rstrip("=")
    )
    payload = make_token(KEY).split(".")[1]
    assert await reason(f"{header}.{payload}.") == "algorithm_not_allowed"


async def test_algorithm_confusion_hs256_with_public_key() -> None:
    """Classic attack: sign with HS256 using the PUBLIC key bytes as the secret."""
    public_pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    now = int(time.time())
    claims = {
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "sub": str(STUDENT_A),
        "role": "authenticated",
        "iat": now,
        "exp": now + 600,
    }
    signing_input_header = {"alg": "HS256", "kid": TEST_KID, "typ": "JWT"}
    # PyJWT refuses to HMAC with a PEM key, so build the token by hand.
    import hashlib
    import hmac

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    signing_input = (
        f"{b64(json.dumps(signing_input_header).encode())}.{b64(json.dumps(claims).encode())}"
    )
    signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    assert await reason(f"{signing_input}.{b64(signature)}") == "algorithm_not_allowed"


async def test_missing_kid() -> None:
    assert await reason(make_token(KEY, kid=None)) == "missing_kid"


async def test_unknown_kid() -> None:
    assert await reason(make_token(KEY, kid="rotated-away")) == "unknown_kid"


@pytest.mark.parametrize("claim", ["exp", "iat", "sub", "aud", "iss"])
async def test_required_claims(claim: str) -> None:
    assert await reason(make_token(KEY, remove=(claim,))) in {
        "invalid",
        "wrong_audience",
        "wrong_issuer",
    }


@pytest.mark.parametrize("role", ["anon", "service_role", "supabase_admin", ""])
async def test_non_user_token_types_are_refused(role: str) -> None:
    assert await reason(make_token(KEY, role=role)) == "wrong_token_type"


async def test_missing_role_is_refused() -> None:
    assert await reason(make_token(KEY, remove=("role",))) == "wrong_token_type"


async def test_anonymous_session_is_refused() -> None:
    assert await reason(make_token(KEY, is_anonymous=True)) == "anonymous_session"


@pytest.mark.parametrize("sub", ["not-a-uuid", "1", "' OR 1=1 --"])
async def test_subject_must_be_a_uuid(sub: str) -> None:
    assert await reason(make_token(KEY, sub=sub)) == "subject_not_uuid"


async def test_rs256_token_refused_when_only_es256_allowed() -> None:
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"sub": str(STUDENT_A)}, rsa_key, algorithm="RS256", headers={"kid": TEST_KID}
    )
    assert await reason(token) == "algorithm_not_allowed"
