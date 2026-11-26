"""Offline sync: push (apply operations exactly once) and pull (read the feed).

The heavy lifting — de-duplication, scoring, version allocation, receipt and
change-feed writes — happens inside the PostgreSQL function
``app.sync_apply_operation`` so that it is one atomic unit the API cannot
partially perform or bypass. This module validates and canonicalises input,
calls that function inside ONE transaction per batch, and shapes the response.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import LargeBinary, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.db.session import Database
from edu_api.errors import ApiError
from edu_api.identity import ensure_learner_profile
from edu_api.sync.canonical import CANON_VERSION, payload_digest
from edu_api.sync.cursor import InvalidCursor, decode_cursor, encode_cursor
from edu_api.sync.schemas import (
    PAYLOAD_MODELS,
    ChangeItem,
    OperationResult,
    PullResponse,
    PushRequest,
    PushResponse,
    SyncOperation,
)

logger = logging.getLogger("edu_api.sync")

_APPLY = text(
    "SELECT app.sync_apply_operation("
    ":op_id, :kind, :payload, :digest, :canon_version, :client_recorded_at) AS outcome"
).bindparams(bindparam("payload", type_=JSONB), bindparam("digest", type_=LargeBinary))

_CURRENT_VERSION = text(
    "SELECT current_version FROM app.account_sync_state WHERE learner_id = :learner_id"
)

_FEED_PAGE = text(
    "SELECT version, entity_type, entity_id, is_tombstone, change_data, created_at "
    "FROM app.account_change_feed "
    "WHERE learner_id = :learner_id AND version > :after "
    "ORDER BY version ASC LIMIT :limit"
)


@dataclass(frozen=True, slots=True)
class _Prepared:
    op: SyncOperation
    payload: dict[str, Any]
    digest: bytes


def _prepare(op: SyncOperation) -> _Prepared | OperationResult:
    """Validate one operation's payload. Bad operations are reported
    individually so one faulty item does not block the rest of the batch."""
    model = PAYLOAD_MODELS.get(op.kind)
    if model is None:
        return OperationResult(
            op_id=op.op_id, status="rejected", replayed=False, code="unsupported_kind"
        )
    try:
        payload = model.model_validate(op.payload).model_dump(mode="json")
    except ValidationError:
        return OperationResult(
            op_id=op.op_id, status="rejected", replayed=False, code="invalid_payload"
        )
    return _Prepared(op=op, payload=payload, digest=payload_digest(op.kind, payload))


def _check_envelope(request: PushRequest, max_ops: int) -> None:
    if not request.ops:
        raise ApiError(422, "empty_batch", "A push must contain at least one operation.")
    if len(request.ops) > max_ops:
        raise ApiError(413, "batch_too_large", f"A push may contain at most {max_ops} operations.")
    seen: set[uuid.UUID] = set()
    for op in request.ops:
        if op.op_id in seen:
            raise ApiError(
                422,
                "duplicate_op_id_in_batch",
                "Each op_id may appear only once in a batch.",
            )
        seen.add(op.op_id)


async def _current_version(conn: AsyncConnection, learner_id: uuid.UUID) -> int:
    value = (await conn.execute(_CURRENT_VERSION, {"learner_id": learner_id})).scalar_one_or_none()
    return int(value) if value is not None else 0


async def push(
    db: Database, learner_id: uuid.UUID, request: PushRequest, *, max_ops: int
) -> PushResponse:
    _check_envelope(request, max_ops)
    prepared = [_prepare(op) for op in request.ops]

    results: list[OperationResult] = []
    # ONE transaction for the whole batch: either every operation in it is
    # durably applied together with its receipt, or (on any failure) none is and
    # the client simply retries the same batch.
    async with db.transaction(learner_id) as conn:
        await ensure_learner_profile(conn, learner_id)
        for item in prepared:
            if isinstance(item, OperationResult):
                results.append(item)
                continue
            outcome = (
                await conn.execute(
                    _APPLY,
                    {
                        "op_id": item.op.op_id,
                        "kind": item.op.kind,
                        "payload": item.payload,
                        "digest": item.digest,
                        "canon_version": CANON_VERSION,
                        "client_recorded_at": item.op.client_recorded_at,
                    },
                )
            ).scalar_one()
            results.append(_to_result(item.op.op_id, outcome))
        server_version = await _current_version(conn, learner_id)

    for result in results:
        if result.status == "conflict":
            logger.warning("sync operation conflict")
    return PushResponse(results=results, server_version=server_version, canon_version=CANON_VERSION)


def _to_result(op_id: uuid.UUID, outcome: dict[str, Any]) -> OperationResult:
    status = outcome["status"]
    body: dict[str, Any] = outcome.get("result") or {}
    if status == "accepted":
        return OperationResult(
            op_id=op_id, status="accepted", replayed=bool(outcome["replayed"]), result=body
        )
    return OperationResult(
        op_id=op_id, status=status, replayed=bool(outcome["replayed"]), code=body.get("code")
    )


async def pull(
    db: Database, learner_id: uuid.UUID, cursor: str | None, *, limit: int
) -> PullResponse:
    reset = ApiError(
        410,
        "sync_cursor_invalid",
        "This cursor cannot be used. Discard it and pull again without a cursor "
        "to replay this account's changes from the beginning.",
    )
    after = 0
    if cursor is not None:
        try:
            after = decode_cursor(learner_id, cursor)
        except InvalidCursor:
            raise reset from None

    async with db.transaction(learner_id, read_only=True) as conn:
        server_version = await _current_version(conn, learner_id)
        if after > server_version:
            # The client is "ahead" of the server: wrong environment, restored
            # backup, or a tampered cursor. Continuing could skip changes forever.
            raise reset
        rows = (
            await conn.execute(
                _FEED_PAGE, {"learner_id": learner_id, "after": after, "limit": limit + 1}
            )
        ).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    changes = [
        ChangeItem(
            version=row.version,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            is_tombstone=row.is_tombstone,
            data=row.change_data,
            created_at=row.created_at,
        )
        for row in page
    ]
    last_version = changes[-1].version if changes else after
    return PullResponse(
        changes=changes,
        next_cursor=encode_cursor(learner_id, last_version),
        has_more=has_more,
        server_version=server_version,
    )
