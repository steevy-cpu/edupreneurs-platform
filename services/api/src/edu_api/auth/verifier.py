"""Verify a Supabase Auth access token and turn it into a ``Principal``.

Checks, in order:
1. shape and size of the token;
2. the header names an algorithm on our allow-list and a key id (``kid``);
3. the key for that ``kid`` comes from the trusted JWKS — and the algorithm is
   the one THAT KEY is for (prevents "algorithm confusion" attacks);
4. signature, expiry (``exp``), issuer (``iss``) and audience (``aud``);
5. token type: it must be a signed-in user's access token
   (``role == "authenticated"``, a UUID ``sub``, not an anonymous session).
   Project API keys (``anon`` / ``service_role``) are JWTs too and are refused here.

Nothing from the token is believed before step 4 succeeds; the unverified
header is used only to pick which public key to try.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt

from edu_api.auth.jwks import KeyNotFound, KeyProvider, KeySourceUnavailable

MAX_TOKEN_LENGTH = 4096


class InvalidToken(Exception):
    """The token is missing, malformed, expired, or not acceptable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        #: Short internal reason for logs/tests. NOT returned to the client.
        self.reason = reason


class AuthUnavailable(Exception):
    """Token could not be checked because the key source is down."""


@dataclass(frozen=True, slots=True)
class Principal:
    """The verified caller. ``user_id`` is ``auth.users.id``."""

    user_id: uuid.UUID
    session_id: str | None = None


class TokenVerifier:
    def __init__(
        self,
        keys: KeyProvider,
        *,
        issuer: str,
        audience: str,
        algorithms: tuple[str, ...],
        leeway_s: int = 30,
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience
        self._algorithms = frozenset(algorithms)
        self._leeway = leeway_s

    async def verify(self, token: str) -> Principal:
        if not token or len(token) > MAX_TOKEN_LENGTH or token.count(".") != 2:
            raise InvalidToken("malformed")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise InvalidToken("malformed_header") from None

        alg = header.get("alg")
        kid = header.get("kid")
        if not isinstance(alg, str) or alg not in self._algorithms:
            raise InvalidToken("algorithm_not_allowed")
        if not isinstance(kid, str) or not kid or len(kid) > 128:
            raise InvalidToken("missing_kid")

        try:
            key = await self._keys.get_key(kid)
        except KeyNotFound:
            raise InvalidToken("unknown_kid") from None
        except KeySourceUnavailable:
            raise AuthUnavailable from None
        if key.algorithm_name != alg:
            raise InvalidToken("algorithm_key_mismatch")

        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=[alg],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError:
            raise InvalidToken("expired") from None
        except jwt.InvalidIssuerError:
            raise InvalidToken("wrong_issuer") from None
        except jwt.InvalidAudienceError:
            raise InvalidToken("wrong_audience") from None
        except jwt.InvalidSignatureError:
            raise InvalidToken("bad_signature") from None
        except jwt.PyJWTError:
            raise InvalidToken("invalid") from None

        if claims.get("role") != "authenticated":
            raise InvalidToken("wrong_token_type")
        if claims.get("is_anonymous") is True:
            raise InvalidToken("anonymous_session")
        subject = claims.get("sub")
        try:
            user_id = uuid.UUID(subject) if isinstance(subject, str) else None
        except ValueError:
            user_id = None
        if user_id is None:
            raise InvalidToken("subject_not_uuid")

        session_id = claims.get("session_id")
        return Principal(
            user_id=user_id, session_id=session_id if isinstance(session_id, str) else None
        )
