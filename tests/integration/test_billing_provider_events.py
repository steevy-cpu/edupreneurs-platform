"""Simulated provider events, end to end: signed in-process message -> adapter
-> billing.apply_provider_event -> what the learner reads at GET /v1/entitlements.

No payment provider is contacted. The signing secret is generated for each test
and exists only in memory. The event sink is test code using the LOCAL owner
connection: the application has no way to apply an event (see the last tests).
"""

# ruff: noqa: F811  (pytest fixtures imported from tests.billing_fixtures are used as arguments)
from __future__ import annotations

import asyncio
import secrets
import uuid

import asyncpg
import httpx
import pytest

from edu_api.billing.mock_provider import (
    InvalidSignature,
    MalformedEvent,
    MockProvider,
    SignedMessage,
    SimulatedProviderDisabled,
    apply_simulated_event,
)
from tests.billing_fixtures import (
    SYNTHETIC_CURRENCY,
    SYNTHETIC_PLAN_CODE,
    SYNTHETIC_PLAN_DAYS,
    SYNTHETIC_PRICE_MINOR,
    AdminEventSink,
    billing_clean,  # noqa: F401  (pytest fixture)
    billing_client,  # noqa: F401  (pytest fixture)
    create_order,
    mock_billing,  # noqa: F401  (pytest fixture)
    mock_provider,  # noqa: F401  (pytest fixture)
    parse_time,
    snapshot,
)
from tests.helpers import STUDENT_A, STUDENT_B, bearer

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("mock_billing")]

NOTHING = {"grants": 0, "revocations": 0, "events": 0, "refunds": 0, "settled_orders": 0}


def message(
    provider: MockProvider,
    order_id: uuid.UUID,
    event_type: str = "payment.succeeded",
    *,
    event_id: str | None = None,
    amount_minor: int = SYNTHETIC_PRICE_MINOR,
    currency: str = SYNTHETIC_CURRENCY,
    plan_code: str | None = SYNTHETIC_PLAN_CODE,
) -> SignedMessage:
    return provider.sign(
        event_id=event_id or f"evt-{uuid.uuid4()}",
        event_type=event_type,
        order_id=order_id,
        amount_minor=amount_minor,
        currency=currency,
        plan_code=plan_code if event_type == "payment.succeeded" else None,
    )


async def entitlements(client: httpx.AsyncClient, token: str) -> list[dict[str, object]]:
    response = await client.get("/v1/entitlements", headers=bearer(token))
    assert response.status_code == 200
    items: list[dict[str, object]] = response.json()["entitlements"]
    return items


async def test_a_paid_order_is_reflected_at_the_next_read(
    admin: asyncpg.Pool,
    mock_provider: MockProvider,
    billing_client: httpx.AsyncClient,
    tokens: dict[str, str],
) -> None:
    sink = AdminEventSink(admin)
    order = await create_order(admin, STUDENT_A)
    assert await entitlements(billing_client, tokens["student_a"]) == [], "an order is not access"

    paid = message(mock_provider, order)
    outcome = await apply_simulated_event(mock_provider, sink, paid.body, paid.signature)
    assert (outcome["status"], outcome["code"], outcome["replayed"]) == (
        "applied",
        "entitlement_granted",
        False,
    )

    mine = await entitlements(billing_client, tokens["student_a"])
    assert len(mine) == 1
    assert mine[0]["id"] == outcome["result"]["entitlement_id"]
    assert (mine[0]["source"], mine[0]["scope"]) == ("purchase", {"kind": "all", "id": None})
    lasted = parse_time(str(mine[0]["ends_at"])) - parse_time(str(mine[0]["starts_at"]))
    assert lasted.total_seconds() == SYNTHETIC_PLAN_DAYS * 24 * 3600
    assert await entitlements(billing_client, tokens["student_b"]) == [], (
        "nobody else gained access"
    )
    assert await snapshot(admin) == {**NOTHING, "grants": 1, "events": 1, "settled_orders": 1}


async def test_duplicated_and_replayed_messages_grant_once(
    admin: asyncpg.Pool, mock_provider: MockProvider
) -> None:
    sink = AdminEventSink(admin)
    order = await create_order(admin, STUDENT_A)
    paid = message(mock_provider, order)
    first = await apply_simulated_event(mock_provider, sink, paid.body, paid.signature)
    for _ in range(5):
        again = await apply_simulated_event(mock_provider, sink, paid.body, paid.signature)
        assert again["replayed"] is True
        assert again["result"] == first["result"], "a replay returns the original outcome"
    # the provider re-announces the same payment under a NEW event id
    second_id = message(mock_provider, order)
    renamed = await apply_simulated_event(mock_provider, sink, second_id.body, second_id.signature)
    assert (renamed["status"], renamed["code"]) == ("ignored", "order_already_paid")
    assert await snapshot(admin) == {**NOTHING, "grants": 1, "events": 2, "settled_orders": 1}


async def test_twenty_concurrent_deliveries_of_one_message_grant_once(
    admin: asyncpg.Pool, mock_provider: MockProvider
) -> None:
    sink = AdminEventSink(admin)
    order = await create_order(admin, STUDENT_A)
    paid = message(mock_provider, order)
    outcomes = await asyncio.gather(
        *(apply_simulated_event(mock_provider, sink, paid.body, paid.signature) for _ in range(20))
    )
    assert sorted(o["replayed"] for o in outcomes) == [False] + [True] * 19
    assert {o["result"]["entitlement_id"] for o in outcomes} == {
        outcomes[0]["result"]["entitlement_id"]
    }
    assert await snapshot(admin) == {**NOTHING, "grants": 1, "events": 1, "settled_orders": 1}


async def test_two_different_success_messages_racing_for_one_order_grant_once(
    admin: asyncpg.Pool, mock_provider: MockProvider
) -> None:
    sink = AdminEventSink(admin)
    order = await create_order(admin, STUDENT_A)
    messages = [message(mock_provider, order) for _ in range(6)]
    outcomes = await asyncio.gather(
        *(apply_simulated_event(mock_provider, sink, m.body, m.signature) for m in messages)
    )
    assert (
        sorted(o["code"] for o in outcomes) == ["entitlement_granted"] + ["order_already_paid"] * 5
    )
    assert await snapshot(admin) == {**NOTHING, "grants": 1, "events": 6, "settled_orders": 1}


async def test_forged_and_tampered_messages_change_nothing(
    admin: asyncpg.Pool,
    mock_provider: MockProvider,
    billing_client: httpx.AsyncClient,
    tokens: dict[str, str],
) -> None:
    sink = AdminEventSink(admin)
    order = await create_order(admin, STUDENT_A)
    attacker = MockProvider(secrets.token_bytes(32), environment="test")

    forged = message(attacker, order)  # perfectly shaped, wrong key
    with pytest.raises(InvalidSignature):
        await apply_simulated_event(mock_provider, sink, forged.body, forged.signature)

    genuine = message(mock_provider, order, amount_minor=SYNTHETIC_PRICE_MINOR)
    for body in (
        genuine.body.replace(str(order).encode(), str(uuid.uuid4()).encode()),
        genuine.body.replace(b"payment.succeeded", b"payment.refunded!"),
        genuine.body + b" ",
    ):
        with pytest.raises(InvalidSignature):
            await apply_simulated_event(mock_provider, sink, body, genuine.signature)
    for signature in ("", "v1=" + "0" * 64, genuine.signature[:-1], genuine.signature.upper()):
        with pytest.raises(InvalidSignature):
            await apply_simulated_event(mock_provider, sink, genuine.body, signature)

    odd = mock_provider.sign_raw({"id": "evt-odd", "type": "payment.succeeded"})
    with pytest.raises(MalformedEvent):
        await apply_simulated_event(mock_provider, sink, odd.body, odd.signature)

    assert sink.calls == 0, "none of them reached the database"
    assert await snapshot(admin) == NOTHING
    assert (
        await admin.fetchval("SELECT status FROM billing.orders WHERE id = $1", order) == "pending"
    )
    assert await entitlements(billing_client, tokens["student_a"]) == []

    # the untouched genuine message still works afterwards
    outcome = await apply_simulated_event(mock_provider, sink, genuine.body, genuine.signature)
    assert outcome["code"] == "entitlement_granted"


async def test_amount_currency_and_plan_are_verified_by_the_server(
    admin: asyncpg.Pool,
    mock_provider: MockProvider,
    billing_client: httpx.AsyncClient,
    tokens: dict[str, str],
) -> None:
    """Authentic messages whose CONTENT does not match the order: stored, refused."""
    sink = AdminEventSink(admin)
    order = await create_order(admin, STUDENT_A)
    other_learners_order = await create_order(admin, STUDENT_B)
    cases = [
        (message(mock_provider, order, amount_minor=SYNTHETIC_PRICE_MINOR - 1), "amount_mismatch"),
        (message(mock_provider, order, amount_minor=1), "amount_mismatch"),
        (
            message(mock_provider, order, amount_minor=SYNTHETIC_PRICE_MINOR * 100),
            "amount_mismatch",
        ),
        (message(mock_provider, order, currency="USD"), "currency_mismatch"),
        (message(mock_provider, order, plan_code="synthetic-all-365"), "plan_mismatch"),
        (message(mock_provider, uuid.uuid4()), "unknown_order"),
    ]
    for signed, code in cases:
        outcome = await apply_simulated_event(mock_provider, sink, signed.body, signed.signature)
        assert (outcome["status"], outcome["code"]) == ("rejected", code)
    for signed, _ in cases:  # replaying a rejected message keeps it rejected
        outcome = await apply_simulated_event(mock_provider, sink, signed.body, signed.signature)
        assert (outcome["status"], outcome["replayed"]) == ("rejected", True)

    assert await snapshot(admin) == {**NOTHING, "events": len(cases)}
    assert await entitlements(billing_client, tokens["student_a"]) == []
    assert await entitlements(billing_client, tokens["student_b"]) == []
    statuses = await admin.fetch(
        "SELECT status FROM billing.orders WHERE id = ANY($1::uuid[])",
        [order, other_learners_order],
    )
    assert [row["status"] for row in statuses] == ["pending", "pending"]
    stored = await admin.fetchval(
        "SELECT payload ->> 'amount_minor' FROM billing.provider_events WHERE outcome_code = 'amount_mismatch' "
        "ORDER BY received_at LIMIT 1"
    )
    assert stored == str(SYNTHETIC_PRICE_MINOR - 1), "the raw message is kept for reconciliation"


async def test_refund_revokes_and_out_of_order_messages_cannot_restore_access(
    admin: asyncpg.Pool,
    mock_provider: MockProvider,
    billing_client: httpx.AsyncClient,
    tokens: dict[str, str],
) -> None:
    sink = AdminEventSink(admin)

    async def deliver(signed: SignedMessage) -> dict[str, object]:
        return await apply_simulated_event(mock_provider, sink, signed.body, signed.signature)

    # normal order: pay, then refund; then everything is replayed in a bad order
    order = await create_order(admin, STUDENT_A)
    paid, refund = message(mock_provider, order), message(mock_provider, order, "payment.refunded")
    assert (await deliver(paid))["code"] == "entitlement_granted"
    assert len(await entitlements(billing_client, tokens["student_a"])) == 1
    assert (await deliver(refund))["code"] == "order_refunded"
    assert await entitlements(billing_client, tokens["student_a"]) == [], "refunded: access ends"
    assert (await deliver(paid))["replayed"] is True
    assert (await deliver(message(mock_provider, order)))["code"] == "order_already_refunded"
    assert (await deliver(message(mock_provider, order, "payment.failed")))["code"] == (
        "order_already_refunded"
    )
    assert (await deliver(refund))["replayed"] is True
    assert await entitlements(billing_client, tokens["student_a"]) == []

    # out of order: the refund overtakes the payment message
    late = await create_order(admin, STUDENT_B)
    late_paid = message(mock_provider, late)
    assert (await deliver(message(mock_provider, late, "payment.refunded")))["code"] == (
        "order_refunded"
    )
    assert (await deliver(late_paid))["code"] == "order_already_refunded"
    assert await entitlements(billing_client, tokens["student_b"]) == []

    # out of order: a stale failure arrives after the success
    third = await create_order(admin, STUDENT_B)
    assert (await deliver(message(mock_provider, third)))["code"] == "entitlement_granted"
    assert (await deliver(message(mock_provider, third, "payment.failed")))["code"] == (
        "order_already_paid"
    )
    assert len(await entitlements(billing_client, tokens["student_b"])) == 1, "still entitled"

    assert await snapshot(admin) == {
        "grants": 2,
        "revocations": 1,
        "events": 8,
        "refunds": 2,
        "settled_orders": 3,
    }


# -------------------- the simulated provider cannot exist outside local / test
@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_the_adapter_refuses_non_local_environments(
    admin: asyncpg.Pool, environment: str
) -> None:
    with pytest.raises(SimulatedProviderDisabled):
        MockProvider(secrets.token_bytes(32), environment=environment)
    assert await snapshot(admin) == NOTHING


async def test_a_database_whose_provider_is_not_enabled_refuses_every_event(
    admin: asyncpg.Pool, mock_provider: MockProvider
) -> None:
    """Like a hosted database, where no provider is registered at all (pgTAP 223
    covers the unregistered case): without an enabled provider nothing is stored."""
    sink = AdminEventSink(admin)
    order = await create_order(admin, STUDENT_A)
    paid = message(mock_provider, order)
    await admin.execute("UPDATE billing.providers SET is_enabled = false WHERE code = 'mock'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="Payment provider is not enabled"):
        await apply_simulated_event(mock_provider, sink, paid.body, paid.signature)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="Payment provider is not enabled"):
        await create_order(admin, STUDENT_A)
    assert await snapshot(admin) == NOTHING
    assert await admin.fetchval("SELECT count(*) FROM billing.orders") == 1


async def test_the_api_process_cannot_apply_an_event_itself(
    app, admin: asyncpg.Pool, mock_provider: MockProvider
) -> None:  # type: ignore[no-untyped-def]
    """A sink built on the API's own database role is refused by PostgreSQL."""
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.sql.expression import bindparam

    order = await create_order(admin, STUDENT_A)
    paid = message(mock_provider, order)
    statement = text(
        "SELECT billing.apply_provider_event(:provider, :event_id, :event_type, :payload)"
    ).bindparams(bindparam("payload", type_=JSONB))

    async def api_role_sink(
        provider: str, event_id: str, event_type: str, payload: dict[str, object]
    ) -> dict[str, object]:
        async with app.state.db.transaction(STUDENT_A) as conn:
            await conn.execute(
                statement,
                {
                    "provider": provider,
                    "event_id": event_id,
                    "event_type": event_type,
                    "payload": payload,
                },
            )
        return {}

    with pytest.raises(DBAPIError) as caught:
        await apply_simulated_event(mock_provider, api_role_sink, paid.body, paid.signature)
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"
    assert await snapshot(admin) == NOTHING
