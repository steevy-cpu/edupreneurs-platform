"""Approved lesson content as the tutor sees it.

The tutor never reads curriculum tables on its own authority. ``SqlLessonSource``
runs the same query as ``GET /v1/lessons/{id}`` inside
``Database.transaction(learner_id)``, so PostgreSQL row-level security decides
what exists: only approved revisions that are in a current pack of a published
course. Drafts, rejected revisions, withdrawn lessons and unknown ids are all
"not found", and the tutor cannot tell them apart — on purpose.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sqlalchemy import text

from edu_api.db.session import Database
from edu_api.tutor.errors import LessonRevisionNotCurrent, LessonUnavailable
from edu_api.tutor.types import Locale

BlockType = Literal["heading", "paragraph", "example", "callout"]
AssessmentMode = Literal["offline_practice", "controlled_assessment"]

_KNOWN_BLOCK_TYPES: frozenset[str] = frozenset({"heading", "paragraph", "example", "callout"})


@dataclass(frozen=True)
class LessonBlock:
    key: str
    type: BlockType
    #: Plain text of the block. An example is its title and steps, one per line.
    text: str


@dataclass(frozen=True)
class Choice:
    id: str
    text: str


@dataclass(frozen=True)
class PracticeQuestion:
    question_key: str
    kind: str
    prompt: str
    choices: tuple[Choice, ...]
    correct_choice_id: str | None
    explanation: str


@dataclass(frozen=True)
class ApprovedLesson:
    lesson_id: uuid.UUID
    revision_id: uuid.UUID
    revision: int
    locale: Locale
    title: str
    blocks: tuple[LessonBlock, ...]
    questions: tuple[PracticeQuestion, ...] = ()
    #: Lessons shipped today are practice only. A controlled assessment never
    #: gets hints or answer explanations from Jude.
    assessment_mode: AssessmentMode = "offline_practice"

    def block(self, key: str) -> LessonBlock | None:
        return next((b for b in self.blocks if b.key == key), None)

    def question(self, key: str) -> PracticeQuestion | None:
        return next((q for q in self.questions if q.question_key == key), None)


def parse_blocks(raw: Sequence[Mapping[str, Any]]) -> tuple[LessonBlock, ...]:
    """Lesson blocks (content format v1) as plain text.

    Unknown block types are skipped rather than guessed at: a later content
    format may add types this module has not been taught to read safely.
    """
    blocks: list[LessonBlock] = []
    for item in raw:
        block_type = item.get("type")
        key = item.get("key")
        if not isinstance(key, str) or block_type not in _KNOWN_BLOCK_TYPES:
            continue
        if block_type == "example":
            steps = [s for s in item.get("steps", ()) if isinstance(s, str)]
            title = item.get("title")
            lines = ([title] if isinstance(title, str) else []) + steps
            body = "\n".join(lines)
        else:
            value = item.get("text")
            body = value if isinstance(value, str) else ""
        if body.strip():
            blocks.append(LessonBlock(key=key, type=block_type, text=body))
    return tuple(blocks)


def parse_question(
    *,
    question_key: str,
    kind: str,
    prompt: Mapping[str, Any],
    response_spec: Mapping[str, Any],
    answer_key: Mapping[str, Any],
    explanation: Mapping[str, Any],
) -> PracticeQuestion:
    choices = tuple(
        Choice(id=c["id"], text=c["text"])
        for c in response_spec.get("choices", ())
        if isinstance(c, Mapping)
        and isinstance(c.get("id"), str)
        and isinstance(c.get("text"), str)
    )
    correct = answer_key.get("correct_choice_id")
    prompt_text = prompt.get("text")
    explanation_text = explanation.get("text")
    return PracticeQuestion(
        question_key=question_key,
        kind=kind,
        prompt=prompt_text if isinstance(prompt_text, str) else "",
        choices=choices,
        correct_choice_id=correct if isinstance(correct, str) else None,
        explanation=explanation_text if isinstance(explanation_text, str) else "",
    )


class LessonSource(Protocol):
    async def get_approved_lesson(
        self,
        *,
        learner_id: uuid.UUID,
        lesson_id: uuid.UUID,
        locale: Locale,
        revision_id: uuid.UUID | None,
    ) -> ApprovedLesson:
        """The published revision this learner may read, or ``LessonUnavailable``.

        With ``revision_id`` the answer must be exactly that revision:
        ``LessonRevisionNotCurrent`` when a newer one replaced it.
        """
        ...


_CURRENT_REVISION = text(
    """
    SELECT r.id, r.lesson_id, r.revision, r.locale, r.title, r.blocks
    FROM app.lesson_revisions r
    WHERE r.lesson_id = :lesson_id AND r.locale = :locale
    ORDER BY r.revision DESC
    LIMIT 1
    """
)

_QUESTIONS = text(
    """
    SELECT q.question_key, q.kind, q.prompt, q.response_spec, q.answer_key, q.explanation
    FROM app.question_revisions q
    WHERE q.lesson_revision_id = :revision_id
    ORDER BY q.position
    """
)


class SqlLessonSource:
    """Reads published lessons as the learner, under row-level security.

    One short read-only transaction per call. No connection is held while a
    model provider is being awaited.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_approved_lesson(
        self,
        *,
        learner_id: uuid.UUID,
        lesson_id: uuid.UUID,
        locale: Locale,
        revision_id: uuid.UUID | None,
    ) -> ApprovedLesson:
        async with self._database.transaction(learner_id, read_only=True) as conn:
            revision = (
                await conn.execute(_CURRENT_REVISION, {"lesson_id": lesson_id, "locale": locale})
            ).one_or_none()
            if revision is None:
                raise LessonUnavailable()
            if revision_id is not None and revision.id != revision_id:
                raise LessonRevisionNotCurrent()
            questions = (await conn.execute(_QUESTIONS, {"revision_id": revision.id})).all()
        return ApprovedLesson(
            lesson_id=revision.lesson_id,
            revision_id=revision.id,
            revision=revision.revision,
            locale=revision.locale,
            title=revision.title,
            blocks=parse_blocks(revision.blocks),
            questions=tuple(
                parse_question(
                    question_key=q.question_key,
                    kind=q.kind,
                    prompt=q.prompt,
                    response_spec=q.response_spec,
                    answer_key=q.answer_key,
                    explanation=q.explanation,
                )
                for q in questions
            ),
        )


RevisionStatus = Literal["draft", "in_review", "approved", "rejected"]


@dataclass
class StoredRevision:
    lesson: ApprovedLesson
    status: RevisionStatus = "approved"
    #: False once the lesson is withdrawn (removed from the current pack).
    published: bool = True
    #: ``None`` means every learner; otherwise only these learners may read it.
    visible_to: frozenset[uuid.UUID] | None = None


@dataclass
class InMemoryLessonSource:
    """Deterministic test double that applies the SAME visibility rules in Python.

    It proves the tutor's behaviour around visibility, not PostgreSQL's
    policies; those are covered by the repository's own database tests.
    """

    revisions: list[StoredRevision] = field(default_factory=list)

    def add(
        self,
        lesson: ApprovedLesson,
        *,
        status: RevisionStatus = "approved",
        published: bool = True,
        visible_to: frozenset[uuid.UUID] | None = None,
    ) -> StoredRevision:
        stored = StoredRevision(lesson, status, published, visible_to)
        self.revisions.append(stored)
        return stored

    async def get_approved_lesson(
        self,
        *,
        learner_id: uuid.UUID,
        lesson_id: uuid.UUID,
        locale: Locale,
        revision_id: uuid.UUID | None,
    ) -> ApprovedLesson:
        visible = [
            r.lesson
            for r in self.revisions
            if r.lesson.lesson_id == lesson_id
            and r.lesson.locale == locale
            and r.status == "approved"
            and r.published
            and (r.visible_to is None or learner_id in r.visible_to)
        ]
        if not visible:
            raise LessonUnavailable()
        current = max(visible, key=lambda lesson: lesson.revision)
        if revision_id is not None and current.revision_id != revision_id:
            raise LessonRevisionNotCurrent()
        return current
