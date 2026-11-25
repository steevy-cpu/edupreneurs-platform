"""Delivery adapters. The only one that exists is a dummy that sends nothing.

A real push provider would implement ``DeliveryAdapter``. None is implemented,
none is imported, and no credential or device token exists anywhere: the
notification policy is an open product decision (PO-10).

CONTENT-FREE PAYLOADS
---------------------
A push body is built by ``build_push_payload`` and contains exactly: a format
version, the notification id, its kind and its reference ids. No title, no
body, no name, no recipient id. The app turns the kind and the ids into words
locally, in the learner's language, after it has checked who is signed in.
Because the age of a learner is not known to the platform (PO-04), EVERY
recipient is treated as a minor: there is no code path that adds content.
"""

from __future__ import annotations

import re
import uuid
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

PAYLOAD_FORMAT_VERSION = 1
#: Mirrors notify.refs_are_ids() in the migration.
ALLOWED_REF_KEYS = frozenset(
    {"word_id", "lesson_id", "unit_id", "course_id", "subject_id", "grant_id"}
)
_KIND = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

Outcome = Literal["delivered", "retry", "failed"]
ErrorCode = Literal["transient", "timeout", "provider_unavailable", "rejected", "adapter_error"]


class ContentNotAllowed(ValueError):
    """A payload carried something other than a kind and opaque ids."""


@dataclass(frozen=True)
class ClaimedDelivery:
    """One delivery leased to this worker by ``notify.claim_due``."""

    outbox_id: uuid.UUID
    channel: str
    lease_token: uuid.UUID
    attempt_no: int
    recipient_id: uuid.UUID
    kind: str
    refs: Mapping[str, str]


@dataclass(frozen=True)
class DeliveryResult:
    outcome: Outcome
    error_code: ErrorCode | None = None


DELIVERED = DeliveryResult("delivered")


def assert_content_free(payload: Mapping[str, object]) -> None:
    """Raise ``ContentNotAllowed`` unless ``payload`` is kind + opaque ids only."""
    if set(payload) != {"v", "id", "kind", "refs"}:
        raise ContentNotAllowed("unexpected payload keys")
    if payload["v"] != PAYLOAD_FORMAT_VERSION:
        raise ContentNotAllowed("unknown payload version")
    identifier, kind, refs = payload["id"], payload["kind"], payload["refs"]
    if not isinstance(identifier, str) or not _UUID.fullmatch(identifier):
        raise ContentNotAllowed("id is not a UUID")
    if not isinstance(kind, str) or not _KIND.fullmatch(kind):
        raise ContentNotAllowed("kind is not a machine code")
    if not isinstance(refs, Mapping) or len(refs) > 4:
        raise ContentNotAllowed("refs is not a small object")
    for key, value in refs.items():
        if key not in ALLOWED_REF_KEYS:
            raise ContentNotAllowed("reference key is not on the allow-list")
        if not isinstance(value, str) or not _UUID.fullmatch(value):
            raise ContentNotAllowed("reference value is not a UUID")


def build_push_payload(delivery: ClaimedDelivery) -> dict[str, object]:
    """The complete body handed to a push channel: kind + opaque ids, nothing else."""
    payload: dict[str, object] = {
        "v": PAYLOAD_FORMAT_VERSION,
        "id": str(delivery.outbox_id),
        "kind": delivery.kind,
        "refs": {key: str(value) for key, value in sorted(delivery.refs.items())},
    }
    assert_content_free(payload)
    return payload


class DeliveryAdapter(Protocol):
    channel: str

    async def deliver(
        self, recipient_id: uuid.UUID, payload: Mapping[str, object]
    ) -> DeliveryResult: ...


@dataclass(frozen=True)
class SinkRecord:
    channel: str
    recipient_id: uuid.UUID
    payload: Mapping[str, object]


class DummyLocalAdapter:
    """ "Delivers" by appending a record to a bounded in-memory list. Sends nothing.

    ``script`` lets a test decide the result of the next deliveries (to exercise
    retries); once it is exhausted every delivery succeeds.
    """

    channel = "push"

    def __init__(self, *, max_records: int = 1000, script: Iterable[DeliveryResult] = ()) -> None:
        self.records: deque[SinkRecord] = deque(maxlen=max_records)
        self._script = deque(script)

    async def deliver(
        self, recipient_id: uuid.UUID, payload: Mapping[str, object]
    ) -> DeliveryResult:
        assert_content_free(payload)  # the sink refuses content too, not only the builder
        result = self._script.popleft() if self._script else DELIVERED
        if result.outcome == "delivered":
            self.records.append(SinkRecord(self.channel, recipient_id, dict(payload)))
        return result
