"""Pure logic of the notify lane: content-free payloads, the dummy adapter, the cursor."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from edu_api.notify.adapter import (
    ClaimedDelivery,
    ContentNotAllowed,
    DeliveryResult,
    DummyLocalAdapter,
    assert_content_free,
    build_push_payload,
)
from edu_api.notify.cursor import InvalidCursor, decode_cursor, encode_cursor
from edu_api.notify.schemas import PreferencesUpdate, QuietHours
from edu_api.notify.worker import DeliveryRunSummary, deliver_due

LEARNER = uuid.UUID("a0000000-0000-4000-8000-000000000001")
OTHER = uuid.UUID("a0000000-0000-4000-8000-000000000002")
WORD = "f0000000-0000-4000-8000-000000000001"


def claimed(**overrides: Any) -> ClaimedDelivery:
    values: dict[str, Any] = {
        "outbox_id": uuid.uuid4(),
        "channel": "push",
        "lease_token": uuid.uuid4(),
        "attempt_no": 1,
        "recipient_id": LEARNER,
        "kind": "daily_word_available",
        "refs": {"word_id": WORD},
    }
    values.update(overrides)
    return ClaimedDelivery(**values)


# ------------------------------------------------------------------ payload
def test_push_payload_is_kind_and_opaque_ids_only() -> None:
    delivery = claimed()
    payload = build_push_payload(delivery)
    assert payload == {
        "v": 1,
        "id": str(delivery.outbox_id),
        "kind": "daily_word_available",
        "refs": {"word_id": WORD},
    }
    # Nothing a lock screen could show, and nothing that identifies the learner.
    serialized = json.dumps(payload)
    for forbidden in ("title", "body", "alert", "message", "name", "email", str(LEARNER)):
        assert forbidden not in serialized


def test_every_string_in_a_payload_is_a_machine_code_or_a_uuid() -> None:
    payload = build_push_payload(claimed(refs={"word_id": WORD, "lesson_id": str(uuid.uuid4())}))

    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for k, v in value.items() for s in (k, *strings(v))]
        return []

    for value in strings(payload):
        is_uuid = len(value) == 36 and uuid.UUID(value).version is not None
        assert is_uuid or value.replace("_", "").isalnum(), value
        assert " " not in value


@pytest.mark.parametrize(
    "delivery",
    [
        claimed(kind="Viens voir le mot du jour !"),
        claimed(kind="daily word"),
        claimed(refs={"word_id": "Bonjour"}),
        claimed(refs={"title": WORD}),
        claimed(refs={"word_id": WORD.upper()}),
        claimed(refs={"word_id": {"text": "hello"}}),
        claimed(
            refs={key: WORD for key in ("word_id", "lesson_id", "unit_id", "course_id", "grant_id")}
        ),
    ],
)
def test_content_is_refused_by_the_builder(delivery: ClaimedDelivery) -> None:
    with pytest.raises(ContentNotAllowed):
        build_push_payload(delivery)


@pytest.mark.parametrize(
    "extra",
    [{"title": "Mot du jour"}, {"body": "Bonjour Marie"}, {"recipient": str(LEARNER)}, {"aps": {}}],
)
def test_content_is_refused_by_the_checker_and_by_the_sink(extra: dict[str, object]) -> None:
    payload = {**build_push_payload(claimed()), **extra}
    with pytest.raises(ContentNotAllowed):
        assert_content_free(payload)


async def test_dummy_adapter_refuses_content_and_only_records_in_memory() -> None:
    adapter = DummyLocalAdapter(max_records=2)
    with pytest.raises(ContentNotAllowed):
        await adapter.deliver(LEARNER, {**build_push_payload(claimed()), "title": "x"})
    assert len(adapter.records) == 0
    for _ in range(3):
        assert (await adapter.deliver(LEARNER, build_push_payload(claimed()))).outcome == (
            "delivered"
        )
    assert len(adapter.records) == 2, "the in-memory sink is bounded"
    assert adapter.records[0].channel == "push" and adapter.records[0].recipient_id == LEARNER


def test_the_notify_package_has_no_way_to_send_anything() -> None:
    """No HTTP client, socket, mail or push library is imported anywhere in the lane."""
    from pathlib import Path

    import edu_api.notify as package

    root = Path(package.__file__).parent
    sources = [*root.glob("*.py"), root.parent / "routers" / "notifications.py"]
    assert len(sources) >= 6
    for source in sources:
        code = source.read_text(encoding="utf-8")
        for needle in ("httpx", "requests", "urllib", "smtplib", "socket", "aiohttp", "firebase"):
            assert f"import {needle}" not in code and f"from {needle}" not in code, (source, needle)


# ------------------------------------------------------------------- worker
class FakePort:
    def __init__(self, deliveries: list[ClaimedDelivery]) -> None:
        self.deliveries = deliveries
        self.reports: list[tuple[uuid.UUID, str, str | None]] = []

    async def claim_due(
        self, channel: str, *, limit: int, lease_seconds: int
    ) -> list[ClaimedDelivery]:
        assert channel == "push"
        batch, self.deliveries = self.deliveries[:limit], self.deliveries[limit:]
        return batch

    async def recheck_lease(self, delivery: ClaimedDelivery) -> str:
        return "send"

    async def record_attempt(
        self, delivery: ClaimedDelivery, outcome: str, error_code: str | None
    ) -> str:
        self.reports.append((delivery.outbox_id, outcome, error_code))
        return {"delivered": "delivered", "retry": "pending", "failed": "failed"}[outcome]


class ExplodingAdapter(DummyLocalAdapter):
    async def deliver(self, recipient_id: uuid.UUID, payload: Any) -> DeliveryResult:
        raise RuntimeError("synthetic adapter bug")


async def test_worker_pass_reports_every_claimed_delivery() -> None:
    port = FakePort([claimed(), claimed(), claimed(), claimed(kind="NOT A CODE")])
    adapter = DummyLocalAdapter(
        script=[DeliveryResult("retry", "transient"), DeliveryResult("failed", "rejected")]
    )
    summary = await deliver_due(port, adapter, limit=10)
    assert summary == DeliveryRunSummary(claimed=4, delivered=1, retried=1, failed=2, stale=0)
    assert [(outcome, code) for _, outcome, code in port.reports] == [
        ("retry", "transient"),
        ("failed", "rejected"),
        ("delivered", None),
        ("failed", "rejected"),  # content never reaches the adapter
    ]
    assert len(adapter.records) == 1


async def test_an_adapter_crash_becomes_a_retry_not_a_lost_delivery() -> None:
    port = FakePort([claimed()])
    summary = await deliver_due(port, ExplodingAdapter())
    assert summary.retried == 1 and port.reports[0][1:] == ("retry", "adapter_error")


class ClockedPort(FakePort):
    """FakePort whose recheck answers can be scripted per row."""

    def __init__(
        self, deliveries: list[ClaimedDelivery], verdicts: list[str] | None = None
    ) -> None:
        super().__init__(deliveries)
        self.verdicts = verdicts or []
        self.rechecked = 0

    async def recheck_lease(self, delivery: ClaimedDelivery) -> str:
        self.rechecked += 1
        return self.verdicts.pop(0) if self.verdicts else "send"


class SlowAdapter(DummyLocalAdapter):
    """Each delivery takes ``seconds`` of (fake) time, without sleeping."""

    def __init__(self, now: list[float], seconds: float) -> None:
        super().__init__()
        self._now = now
        self._seconds = seconds

    async def deliver(self, recipient_id: uuid.UUID, payload: Any) -> DeliveryResult:
        self._now[0] += self._seconds
        return await super().deliver(recipient_id, payload)


async def test_rows_whose_lease_is_too_short_for_the_adapter_are_not_attempted() -> None:
    """Review L-2: claimed rows share one lease but are attempted one by one. With a
    slow adapter the later rows' lease has (almost) run out: attempting them would
    overlap another worker's pass. They are skipped and left to their lease."""
    now = [1000.0]
    port = ClockedPort([claimed(), claimed(), claimed(), claimed()])
    adapter = SlowAdapter(now, seconds=25.0)  # lease 60 s -> adapter timeout 30 s
    summary = await deliver_due(port, adapter, limit=10, lease_seconds=60, clock=lambda: now[0])
    # t=0: 60 s left, attempt (-> t=25). t=25: 35 s left, attempt (-> t=50).
    # t=50: 10 s left < 30 s: skipped; same for the fourth row.
    assert (summary.claimed, summary.delivered, summary.skipped) == (4, 2, 2)
    assert len(adapter.records) == 2 and len(port.reports) == 2
    assert port.rechecked == 2


async def test_quiet_hours_that_began_after_the_claim_stop_the_attempt() -> None:
    """Review L-2: the database re-checks quiet hours at delivery time. 'deferred'
    (and 'stale') mean nothing is sent and no outcome is reported."""
    port = ClockedPort([claimed(), claimed(), claimed()], verdicts=["deferred", "stale", "send"])
    adapter = DummyLocalAdapter()
    summary = await deliver_due(port, adapter, limit=10)
    assert (summary.claimed, summary.delivered, summary.skipped, summary.stale) == (3, 1, 1, 1)
    assert len(adapter.records) == 1 and len(port.reports) == 1


# ------------------------------------------------------------------- cursor
def test_cursor_round_trip_keeps_microseconds() -> None:
    moment = datetime(2026, 11, 24, 22, 15, 3, 123457, tzinfo=timezone(timedelta(hours=-5)))
    cursor = encode_cursor(LEARNER, moment, 42)
    assert decode_cursor(LEARNER, cursor) == (moment.astimezone(UTC), 42)
    assert "=" not in cursor and len(cursor) < 200


def _forge(document: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(document).encode()).decode().rstrip("=")


def test_cursor_rejects_other_accounts_and_garbage() -> None:
    good = encode_cursor(LEARNER, datetime(2026, 1, 1, tzinfo=UTC), 7)
    with pytest.raises(InvalidCursor, match="other_account"):
        decode_cursor(OTHER, good)
    document = json.loads(base64.urlsafe_b64decode(good + "=" * (-len(good) % 4)))
    for bad in (
        "",
        "x" * 201,
        "not base64 !",
        _forge([1, 2]),
        _forge({**document, "extra": 1}),
        _forge({**document, "v": 2}),
        _forge({**document, "s": 0}),
        _forge({**document, "s": True}),
        _forge({**document, "s": "7"}),
        _forge({**document, "t": 10**30}),
        _forge({**document, "t": 1.5}),
    ):
        with pytest.raises(InvalidCursor):
            decode_cursor(LEARNER, bad)


# ------------------------------------------------------------------ schemas
def test_preferences_body_is_strict() -> None:
    ok = PreferencesUpdate.model_validate(
        {
            "push_enabled": True,
            "muted_categories": ["learning"],
            "quiet_hours": {"start": "22:30", "end": "05:00"},
        }
    )
    assert ok.quiet_hours == QuietHours(start="22:30", end="05:00")
    base = {"push_enabled": False, "muted_categories": [], "quiet_hours": None}
    for bad in (
        {**base, "user_id": str(OTHER)},
        {**base, "learner_id": str(OTHER)},
        {**base, "push_enabled": "yes"},
        {**base, "push_enabled": 1},
        {**base, "muted_categories": ["marketing"]},
        {**base, "muted_categories": ["learning"] * 4},
        {**base, "quiet_hours": {"start": "24:00", "end": "05:00"}},
        {**base, "quiet_hours": {"start": "9:00", "end": "05:00"}},
        {**base, "quiet_hours": {"start": "21:00", "end": "21:00"}},
        {**base, "quiet_hours": {"start": "21:00"}},
        {**base, "quiet_hours": {"start": "21:00", "end": "06:00", "tz": "UTC"}},
        {"push_enabled": False, "muted_categories": []},
        {},
    ):
        with pytest.raises(ValueError):
            PreferencesUpdate.model_validate(bad)
