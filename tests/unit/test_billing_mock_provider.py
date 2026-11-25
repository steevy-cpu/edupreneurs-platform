"""The simulated payment provider: pure logic, no network, no database."""

from __future__ import annotations

import ast
import json
import secrets
import uuid
from pathlib import Path
from typing import Any

import pytest

import edu_api.billing
from edu_api.billing.mock_provider import (
    MAX_BODY_BYTES,
    InvalidSignature,
    MalformedEvent,
    MockProvider,
    SignedMessage,
    SimulatedProviderDisabled,
    apply_simulated_event,
)
from edu_api.config import Settings

ORDER = uuid.UUID("0d5c0e2e-6a0f-4a6e-9b61-3f5e5b0c9a11")


def provider(secret: bytes | None = None) -> MockProvider:
    return MockProvider(secret or secrets.token_bytes(32), environment="test")


def paid(p: MockProvider, **overrides: Any) -> SignedMessage:
    fields: dict[str, Any] = {
        "event_id": "evt-1",
        "event_type": "payment.succeeded",
        "order_id": ORDER,
        "amount_minor": 50_000,
        "currency": "HTG",
        "plan_code": "synthetic-all-30",
    }
    fields.update(overrides)
    return p.sign(**fields)


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict[str, Any]]] = []

    async def __call__(
        self, provider: str, event_id: str, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.events.append((provider, event_id, event_type, payload))
        return {"status": "applied"}


# ------------------------------------------------------- where it may exist
@pytest.mark.parametrize("environment", ["local", "test"])
def test_exists_in_local_and_test(environment: str) -> None:
    assert MockProvider(secrets.token_bytes(32), environment=environment).code == "mock"


@pytest.mark.parametrize("environment", ["staging", "production", "prod", "", "LOCAL", "test "])
def test_cannot_be_constructed_outside_local_and_test(environment: str) -> None:
    with pytest.raises(SimulatedProviderDisabled):
        MockProvider(secrets.token_bytes(32), environment=environment)


def test_every_configured_environment_other_than_local_and_test_is_refused() -> None:
    allowed = Settings.model_fields["environment"].annotation.__args__  # type: ignore[union-attr]
    assert set(allowed) == {"local", "test", "staging", "production"}
    for environment in set(allowed) - {"local", "test"}:
        with pytest.raises(SimulatedProviderDisabled):
            MockProvider(secrets.token_bytes(32), environment=environment)


@pytest.mark.parametrize("secret", [b"", b"short", secrets.token_bytes(31), "x" * 64])
def test_a_weak_or_non_bytes_secret_is_refused(secret: Any) -> None:
    with pytest.raises(ValueError, match="at least 32 random bytes"):
        MockProvider(secret, environment="test")


def test_the_secret_never_appears_in_repr() -> None:
    secret = secrets.token_bytes(32)
    text = repr(MockProvider(secret, environment="test"))
    assert secret.hex() not in text and repr(secret) not in text and "hidden" in text


# ------------------------------------------------------------ sign / verify
def test_a_signed_message_verifies_and_carries_integer_minor_units() -> None:
    p = provider()
    message = paid(p)
    event = p.verify(message.body, message.signature)
    assert (event.provider, event.event_id, event.event_type) == (
        "mock",
        "evt-1",
        "payment.succeeded",
    )
    assert event.payload == {
        "order_id": str(ORDER),
        "amount_minor": 50_000,
        "currency": "HTG",
        "plan_code": "synthetic-all-30",
    }
    assert isinstance(event.payload["amount_minor"], int)
    assert message.signature.startswith("v1=") and len(message.signature) == 3 + 64


@pytest.mark.parametrize("amount", [500.0, 500.5, "50000", True, None])
def test_money_must_be_an_integer(amount: Any) -> None:
    with pytest.raises(TypeError, match="integer number of minor units"):
        paid(provider(), amount_minor=amount)


def test_a_message_signed_with_another_secret_is_forged() -> None:
    message = paid(provider())
    with pytest.raises(InvalidSignature):
        provider().verify(message.body, message.signature)


def test_changing_one_byte_after_signing_is_detected() -> None:
    p = provider()
    message = paid(p)
    cheaper = message.body.replace(b"50000", b"50001")
    assert cheaper != message.body
    with pytest.raises(InvalidSignature):
        p.verify(cheaper, message.signature)
    upgraded = message.body.replace(b"synthetic-all-30", b"synthetic-all-99")
    with pytest.raises(InvalidSignature):
        p.verify(upgraded, message.signature)


@pytest.mark.parametrize(
    "signature",
    ["", "v1=", "v1=" + "0" * 64, "v2=" + "0" * 64, "0" * 64, "v1", "=", "v1=é", None, 123],
)
def test_missing_or_wrong_signatures_are_refused(signature: Any) -> None:
    p = provider()
    with pytest.raises(InvalidSignature):
        p.verify(paid(p).body, signature)


def test_a_signature_for_one_message_does_not_sign_another() -> None:
    p = provider()
    first, second = paid(p, event_id="evt-1"), paid(p, event_id="evt-2")
    with pytest.raises(InvalidSignature):
        p.verify(second.body, first.signature)


def test_an_oversized_body_is_refused_before_anything_is_parsed() -> None:
    p = provider()
    message = p.sign_raw({"id": "evt-big", "type": "x", "data": {"pad": "x" * MAX_BODY_BYTES}})
    with pytest.raises(InvalidSignature):
        p.verify(message.body, message.signature)


def _signed_bytes(p: MockProvider, body: bytes) -> SignedMessage:
    return SignedMessage(body=body, signature="v1=" + p._mac(body))


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'"text"',
        b"\xff\xfe",
        b'{"id":"e","type":"t"}',
        b'{"id":"e","type":"t","data":{},"extra":1}',
        b'{"id":"","type":"t","data":{}}',
        b'{"id":1,"type":"t","data":{}}',
        b'{"id":"e","type":"","data":{}}',
        b'{"id":"e","type":"t","data":[]}',
        b'{"id":"e","type":"t","data":{"amount_minor":500.5}}',
        b'{"id":"e","type":"t","data":{"amount_minor":1e3}}',
        b'{"id":"e","id":"f","type":"t","data":{}}',
        b'{"id":"e","type":"t","data":{"amount_minor":1,"amount_minor":2}}',
    ],
)
def test_authentic_but_malformed_envelopes_are_refused(body: bytes) -> None:
    p = provider()
    message = _signed_bytes(p, body)
    with pytest.raises(MalformedEvent):
        p.verify(message.body, message.signature)


# ------------------------------------------------------- apply_simulated_event
async def test_an_authentic_event_reaches_the_sink_once() -> None:
    p, sink = provider(), RecordingSink()
    message = paid(p)
    assert await apply_simulated_event(p, sink, message.body, message.signature) == {
        "status": "applied"
    }
    assert sink.events == [
        (
            "mock",
            "evt-1",
            "payment.succeeded",
            {
                "order_id": str(ORDER),
                "amount_minor": 50_000,
                "currency": "HTG",
                "plan_code": "synthetic-all-30",
            },
        )
    ]


async def test_a_forged_or_malformed_event_never_reaches_the_sink() -> None:
    p, sink = provider(), RecordingSink()
    forged = paid(provider())
    with pytest.raises(InvalidSignature):
        await apply_simulated_event(p, sink, forged.body, forged.signature)
    tampered = paid(p)
    with pytest.raises(InvalidSignature):
        await apply_simulated_event(
            p, sink, tampered.body.replace(b"50000", b"1"), tampered.signature
        )
    malformed = _signed_bytes(p, b'{"id":"e","type":"t"}')
    with pytest.raises(MalformedEvent):
        await apply_simulated_event(p, sink, malformed.body, malformed.signature)
    assert sink.events == []


# ---------------------------------------------- no provider SDK, no network
FORBIDDEN_IMPORT_ROOTS = {
    "httpx", "requests", "urllib", "urllib3", "http", "aiohttp", "socket", "ssl", "smtplib",
    "websockets", "grpc", "boto3", "stripe", "paypalrestsdk", "braintree", "moncash", "natcash",
}  # fmt: skip


def test_the_billing_package_imports_no_network_library_and_no_provider_sdk() -> None:
    package = Path(edu_api.billing.__file__).resolve().parent
    router = package.parent / "routers" / "entitlements.py"
    files = [*sorted(package.rglob("*.py")), router]
    assert len(files) >= 5, files
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not roots & FORBIDDEN_IMPORT_ROOTS, (path.name, roots)


def test_the_signed_body_is_canonical_json() -> None:
    message = paid(provider())
    assert json.loads(message.body) == {
        "id": "evt-1",
        "type": "payment.succeeded",
        "data": {
            "order_id": str(ORDER),
            "amount_minor": 50_000,
            "currency": "HTG",
            "plan_code": "synthetic-all-30",
        },
    }
    assert b" " not in message.body
