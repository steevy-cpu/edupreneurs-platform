"""Request/response models for offline sync.

The learner's identity is NEVER part of these models: it comes from the
verified access token only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

ChoiceId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- operation payloads (validated per operation) -----------------------------
class McqResponse(_Strict):
    choice_id: ChoiceId = Field(description="`id` of the selected choice.")


class PracticeAnswerPayload(_Strict):
    """An answer to one multiple-choice practice question."""

    question_revision_id: uuid.UUID
    response: McqResponse


class LessonCompletedPayload(_Strict):
    """The learner finished reading this exact lesson revision."""

    lesson_revision_id: uuid.UUID


PAYLOAD_MODELS: dict[str, type[_Strict]] = {
    "practice_answer": PracticeAnswerPayload,
    "lesson_completed": LessonCompletedPayload,
}


# --- push -----------------------------------------------------------------------
class SyncOperation(_Strict):
    op_id: uuid.UUID = Field(
        description="Client-generated UUID, created ONCE when the action happens offline "
        "and reused unchanged on every retry."
    )
    kind: Annotated[str, StringConstraints(min_length=1, max_length=40)] = Field(
        description="`practice_answer` or `lesson_completed`.",
        examples=["practice_answer"],
    )
    client_recorded_at: AwareDatetime | None = Field(
        default=None,
        description="When the phone recorded the action. Untrusted display metadata: "
        "never used for ordering or scoring, and not part of the payload digest.",
    )
    payload: dict[str, Any] = Field(
        description="Shape depends on `kind`: see PracticeAnswerPayload / LessonCompletedPayload."
    )


class PushRequest(_Strict):
    ops: list[SyncOperation] = Field(description="1 to 50 operations, applied in order.")


OperationStatus = Literal["accepted", "rejected", "conflict"]


class OperationResult(BaseModel):
    op_id: uuid.UUID
    status: OperationStatus = Field(
        description="`accepted`: applied (now or on an earlier attempt). "
        "`rejected`: permanently refused; do not retry this op_id. "
        "`conflict`: this op_id was already used with different content; nothing changed."
    )
    replayed: bool = Field(
        description="True when this op_id had already been processed and the stored "
        "result is being returned again. No new attempt, score or change was created."
    )
    code: str | None = Field(default=None, description="Reason code for rejected/conflict.")
    result: dict[str, Any] | None = Field(
        default=None, description="Canonical server result for accepted operations."
    )


class PushResponse(BaseModel):
    results: list[OperationResult] = Field(description="One result per op, in request order.")
    server_version: int = Field(description="This account's latest change version after the push.")
    canon_version: str


# --- pull -----------------------------------------------------------------------
class ChangeItem(BaseModel):
    version: int
    entity_type: Literal["lesson_progress", "practice_attempt"]
    entity_id: uuid.UUID
    is_tombstone: bool = Field(
        description="True means the entity was removed on the server: delete the local copy."
    )
    data: dict[str, Any]
    created_at: datetime


class PullResponse(BaseModel):
    changes: list[ChangeItem] = Field(description="Ascending by version, no gaps.")
    next_cursor: str = Field(description="Opaque. Store it only after applying `changes`.")
    has_more: bool
    server_version: int
