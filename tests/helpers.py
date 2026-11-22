"""Shared test helpers: token forging with throw-away keys, fixed seed ids."""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

STUDENT_A = uuid.UUID("a0000000-0000-4000-8000-000000000001")
STUDENT_B = uuid.UUID("a0000000-0000-4000-8000-000000000002")
EDITOR = uuid.UUID("a0000000-0000-4000-8000-000000000003")
REVIEWER = uuid.UUID("a0000000-0000-4000-8000-000000000004")
SEED_UNIT = uuid.UUID("b0000000-0000-4000-8000-000000000004")
SEED_LESSON = uuid.UUID("b0000000-0000-4000-8000-000000000005")
SEED_REV_FR = uuid.UUID("c0000000-0000-4000-8000-000000000001")
SEED_REV_HT = uuid.UUID("c0000000-0000-4000-8000-000000000002")
SEED_SOURCE = uuid.UUID("e0000000-0000-4000-8000-000000000001")
#: French seed questions 1..5 and the id of the correct choice for each.
SEED_QUESTIONS_FR = [
    (uuid.UUID(f"d0000000-0000-4000-8000-00000000010{n}"), correct)
    for n, correct in enumerate(["b", "a", "c", "d", "b"], start=1)
]
SEED_QUESTIONS_HT = [
    (uuid.UUID(f"d0000000-0000-4000-8000-00000000020{n}"), correct)
    for n, correct in enumerate(["b", "a", "c", "d", "b"], start=1)
]

TEST_ISSUER = "https://auth.test.invalid/auth/v1"
TEST_AUDIENCE = "authenticated"
TEST_KID = "test-key-1"


def new_ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def public_jwk(private_key: ec.EllipticCurvePrivateKey, kid: str = TEST_KID) -> jwt.PyJWK:
    import json

    raw = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key()))
    raw.update({"kid": kid, "alg": "ES256", "use": "sig"})
    return jwt.PyJWK(raw)


def make_token(
    private_key: Any,
    *,
    kid: str | None = TEST_KID,
    algorithm: str = "ES256",
    remove: tuple[str, ...] = (),
    **overrides: Any,
) -> str:
    """A token shaped like a Supabase access token, signed with a TEST key."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "sub": str(STUDENT_A),
        "role": "authenticated",
        "iat": now,
        "exp": now + 600,
        "is_anonymous": False,
        "session_id": str(uuid.uuid4()),
    }
    claims.update(overrides)
    for name in remove:
        claims.pop(name, None)
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims, private_key, algorithm=algorithm, headers=headers)


def answer_op(
    question_id: uuid.UUID, choice: str, op_id: uuid.UUID | None = None
) -> dict[str, Any]:
    return {
        "op_id": str(op_id or uuid.uuid4()),
        "kind": "practice_answer",
        "payload": {"question_revision_id": str(question_id), "response": {"choice_id": choice}},
    }


def completed_op(revision_id: uuid.UUID, op_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "op_id": str(op_id or uuid.uuid4()),
        "kind": "lesson_completed",
        "payload": {"lesson_revision_id": str(revision_id)},
    }


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
