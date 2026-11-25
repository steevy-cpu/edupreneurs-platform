"""A SIMULATED payment provider: pure, in-process, for local development and tests.

It moves no money and talks to nobody. It exists so that the event pipeline in
the database (``billing.apply_provider_event``) can be exercised end to end with
messages that are signed, duplicated, replayed, reordered or forged — before any
real provider is chosen (BLOCKED_BY_OWNER PO-06).

How it is kept out of non-local environments (four independent layers)
    1. No HTTP route. Nothing in ``edu_api.routers`` receives a provider
       message, in any environment, whatever the flags are.
    2. ``MockProvider`` refuses to be constructed unless the environment is
       ``local`` or ``test``.
    3. This module holds no database connection and ships no sink. To apply an
       event the caller must supply one; the API's own role (``edu_api``) has
       no EXECUTE on ``billing.apply_provider_event``, so the API process could
       not apply an event even if it tried. Only test code, connected as the
       owner of a disposable local database, provides a sink.
    4. The database accepts events only for a provider registered and enabled
       in ``billing.providers``. No migration registers one, so in a hosted
       database the simulated provider does not exist.

The signing secret is supplied by the caller (tests generate one per run with
``secrets.token_bytes``). It is never read from configuration, never logged and
never written anywhere.

No network library and no provider SDK is imported here; a test enforces it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

PROVIDER_CODE: Final = "mock"
LOCAL_ENVIRONMENTS: Final = frozenset({"local", "test"})
MIN_SECRET_BYTES: Final = 32
MAX_BODY_BYTES: Final = 8192
SIGNATURE_SCHEME: Final = "v1"

EventType = Literal["payment.succeeded", "payment.failed", "payment.refunded"]


class SimulatedProviderDisabled(RuntimeError):
    """The simulated provider was asked for outside ``local`` / ``test``."""


class InvalidSignature(Exception):
    """The message was not signed with this provider's secret. Nothing was applied."""


class MalformedEvent(Exception):
    """The message is authentic but is not a well-formed event envelope."""


@dataclass(frozen=True, slots=True)
class SignedMessage:
    """What a provider would POST: raw bytes and a signature header value."""

    body: bytes
    signature: str


@dataclass(frozen=True, slots=True)
class VerifiedEvent:
    provider: str
    event_id: str
    event_type: str
    payload: dict[str, Any]


class EventSink(Protocol):
    """Hands an AUTHENTICATED event to ``billing.apply_provider_event``."""

    def __call__(
        self, provider: str, event_id: str, event_type: str, payload: dict[str, Any]
    ) -> Awaitable[dict[str, Any]]: ...


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # Two parsers may disagree on which duplicate wins; refuse the ambiguity.
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MalformedEvent("duplicate key")
        result[key] = value
    return result


def _no_floats(_: str) -> Any:
    # Money is integer minor units. A fractional number never belongs in an event.
    raise MalformedEvent("fractional number")


class MockProvider:
    """Signs and verifies simulated provider messages with HMAC-SHA256."""

    code: Final = PROVIDER_CODE

    def __init__(self, secret: bytes, *, environment: str) -> None:
        if environment not in LOCAL_ENVIRONMENTS:
            raise SimulatedProviderDisabled(
                "The simulated payment provider only exists in local and test environments."
            )
        if not isinstance(secret, bytes) or len(secret) < MIN_SECRET_BYTES:
            raise ValueError(f"the signing secret must be at least {MIN_SECRET_BYTES} random bytes")
        self._secret = secret

    def __repr__(self) -> str:  # never expose the secret through a log line or traceback
        return "MockProvider(<secret hidden>)"

    def _mac(self, body: bytes) -> str:
        return hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    def sign(
        self,
        *,
        event_id: str,
        event_type: str,
        order_id: uuid.UUID,
        amount_minor: int,
        currency: str,
        plan_code: str | None = None,
    ) -> SignedMessage:
        """Build the message the simulated provider would send about an order."""
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
            raise TypeError("amount_minor must be an integer number of minor units")
        data: dict[str, Any] = {
            "order_id": str(order_id),
            "amount_minor": amount_minor,
            "currency": currency,
        }
        if plan_code is not None:
            data["plan_code"] = plan_code
        return self.sign_raw({"id": event_id, "type": event_type, "data": data})

    def sign_raw(self, envelope: dict[str, Any]) -> SignedMessage:
        """Sign an arbitrary envelope (tests use it to send authentic but odd messages)."""
        body = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return SignedMessage(body=body, signature=f"{SIGNATURE_SCHEME}={self._mac(body)}")

    def verify(self, body: bytes, signature: str) -> VerifiedEvent:
        """Authenticate the raw bytes, then parse them. Order matters: nothing
        from an unauthenticated body is ever interpreted."""
        if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
            raise InvalidSignature
        scheme, _, received = (
            signature.partition("=") if isinstance(signature, str) else ("", "", "")
        )
        if scheme != SIGNATURE_SCHEME or not hmac.compare_digest(
            received.encode("utf-8"), self._mac(body).encode("utf-8")
        ):
            raise InvalidSignature
        try:
            envelope = json.loads(
                body.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_float=_no_floats
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise MalformedEvent("not a JSON object") from exc
        if not isinstance(envelope, dict) or set(envelope) != {"id", "type", "data"}:
            raise MalformedEvent("unexpected envelope")
        event_id, event_type, data = envelope["id"], envelope["type"], envelope["data"]
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
            raise MalformedEvent("bad event id")
        if not isinstance(event_type, str) or not 1 <= len(event_type) <= 80:
            raise MalformedEvent("bad event type")
        if not isinstance(data, dict):
            raise MalformedEvent("bad event data")
        return VerifiedEvent(
            provider=self.code, event_id=event_id, event_type=event_type, payload=data
        )


async def apply_simulated_event(
    provider: MockProvider, sink: EventSink, body: bytes, signature: str
) -> dict[str, Any]:
    """Verify one simulated provider message and, only if authentic, hand it to
    the database through ``sink``. A forged or malformed message never reaches
    the sink. Amount, currency and plan are verified by the database against
    the order, not here.
    """
    event = provider.verify(body, signature)
    return await sink(event.provider, event.event_id, event.event_type, event.payload)
