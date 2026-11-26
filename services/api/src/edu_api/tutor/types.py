"""Public data contracts of the Jude tutor (request in, cited answer out).

These models ARE the tutoring contract: retrieval strategy, prompt version and
model provider can all change behind them. JSON Schemas generated from them
live in ``packages/contracts/tutor`` (see ``edu_api.tutor.contracts``).

Deliberately absent: any learner identifier. The learner is always the verified
token subject, never a value a client can send.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Locale = Literal["fr", "ht"]

#: Longest student message accepted (characters). Short on purpose: Jude answers
#: questions about a lesson, it is not a place to paste documents.
MAX_MESSAGE_CHARS = 600


class TutorIntent(StrEnum):
    EXPLAIN_CONCEPT = "explain_concept"
    ASK_QUESTION = "ask_question"
    HINT = "hint"
    EXPLAIN_ANSWER = "explain_answer"
    ANOTHER_EXAMPLE = "another_example"
    SIMPLIFY = "simplify"


class ResponseStatus(StrEnum):
    #: A tutoring answer produced by the model and validated.
    ANSWERED = "answered"
    #: The lesson does not contain enough verified material; nothing was invented.
    INSUFFICIENT_CONTEXT = "insufficient_context"
    #: A fixed message: the request is outside what Jude does.
    DECLINED = "declined"
    #: A fixed supportive message pointing to a trusted adult. Its wording has not
    #: been professionally reviewed (``safety.TEMPLATES_REVIEW_STATUS``).
    SAFETY_SUPPORT = "safety_support"


class Grounding(StrEnum):
    #: Supported by the cited passages of the approved lesson.
    LESSON = "lesson"
    #: Ordinary school knowledge that goes beyond the lesson; shown with a notice.
    GENERAL = "general"
    #: No explanation of subject matter was given.
    NONE = "none"


class NextAction(StrEnum):
    NONE = "none"
    REREAD_PASSAGE = "reread_passage"
    REVIEW_EXAMPLE = "review_example"
    TRY_PRACTICE_QUESTION = "try_practice_question"
    ASK_FOLLOW_UP = "ask_follow_up"
    REPHRASE_QUESTION = "rephrase_question"
    TALK_TO_TRUSTED_ADULT = "talk_to_trusted_adult"


class ResponseSource(StrEnum):
    #: Text written by the model, validated by the server.
    MODEL = "model"
    #: Fixed text shipped with the server; no model was called. The name says
    #: nothing about review: see ``safety.TEMPLATES_REVIEW_STATUS``.
    FIXED_TEMPLATE = "fixed_template"


class Notice(StrEnum):
    GENERAL_KNOWLEDGE = "general_knowledge_beyond_lesson"
    PERSONAL_INFO_REMOVED = "personal_info_removed"
    QUESTION_NOT_IN_LESSON = "question_not_found_in_lesson"
    INSTRUCTION_MANIPULATION = "instruction_manipulation"
    INAPPROPRIATE_REQUEST = "inappropriate_request"
    CONTROLLED_ASSESSMENT = "controlled_assessment"
    SAFETY_CONCERN = "safety_concern"


class TutorRequest(BaseModel):
    """One stateless tutoring request about one lesson."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID = Field(
        description="Client-generated id of this request. A repeat is never charged twice."
    )
    lesson_id: uuid.UUID
    lesson_revision_id: uuid.UUID | None = Field(
        default=None,
        description="The immutable revision the learner is reading. When given, Jude "
        "answers only from exactly that revision.",
    )
    locale: Locale = Field(description="Language of the lesson content being read.")
    response_locale: Locale | None = Field(
        default=None, description="Language Jude answers in. Defaults to `locale`."
    )
    intent: TutorIntent
    message: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MESSAGE_CHARS,
        description="The student's own words. Never stored, never logged.",
    )
    focus_block_key: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9-]{0,63}$",
        description="Block the learner is looking at, if any.",
    )
    question_key: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9_-]{1,80}$",
        description="Practice question this request is about, if any.",
    )
    selected_choice_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="The learner's answer, for `explain_answer`.",
    )
    support_level: int = Field(
        default=1,
        ge=1,
        le=4,
        description="How much help was already given for the same difficulty "
        "(1 = first ask). Kept by the client: the server stores no conversation.",
    )

    @model_validator(mode="after")
    def _shape(self) -> TutorRequest:
        if self.message is not None and not self.message.strip():
            raise ValueError("message must not be blank")
        if self.intent in (TutorIntent.ASK_QUESTION, TutorIntent.EXPLAIN_CONCEPT) and not (
            self.message or self.focus_block_key
        ):
            raise ValueError("this intent needs a message or a focus_block_key")
        if self.intent is TutorIntent.EXPLAIN_ANSWER and not (
            self.question_key and self.selected_choice_id
        ):
            raise ValueError("explain_answer needs question_key and selected_choice_id")
        if self.intent is TutorIntent.HINT and not (self.question_key or self.message):
            raise ValueError("hint needs a question_key or a message")
        if self.intent in (TutorIntent.ANOTHER_EXAMPLE, TutorIntent.SIMPLIFY) and not (
            self.message or self.focus_block_key or self.question_key
        ):
            raise ValueError("this intent needs a message, a focus_block_key or a question_key")
        if self.selected_choice_id and not self.question_key:
            raise ValueError("selected_choice_id needs question_key")
        return self

    @property
    def answer_locale(self) -> Locale:
        return self.response_locale or self.locale


class LessonReference(BaseModel):
    """A stable pointer to approved content. Only the server creates these."""

    model_config = ConfigDict(frozen=True)

    lesson_id: uuid.UUID
    lesson_revision_id: uuid.UUID
    locale: Locale
    kind: Literal["block", "question"]
    key: str = Field(description="Block key, or question key when kind is `question`.")


class TutorResponse(BaseModel):
    request_id: uuid.UUID = Field(description="Echo of the idempotency key.")
    status: ResponseStatus
    source: ResponseSource
    grounding: Grounding
    language: Locale
    explanation: str
    hint: str | None = None
    check_question: str | None = Field(
        default=None, description="A short question so the learner can check understanding."
    )
    references: list[LessonReference] = Field(default_factory=list)
    next_action: NextAction = NextAction.NONE
    answer_was_correct: bool | None = Field(
        default=None,
        description="For `explain_answer`: decided by the server from the reviewed answer "
        "key, never by the model.",
    )
    notices: list[Notice] = Field(default_factory=list)
    lesson_revision_id: uuid.UUID | None = None
    prompt_version: str | None = None


class TutorAvailability(BaseModel):
    """Answer of the status probe. Contains no usage of anyone but the caller."""

    available: bool
    reason: str | None = Field(default=None, description="A stable tutor error code.")
    daily_requests_used: int | None = None
    daily_requests_limit: int | None = None
