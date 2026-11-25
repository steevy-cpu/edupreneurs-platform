"""Request models for lesson content written by staff.

They mirror ``packages/contracts/content/lesson-blocks.schema.json`` and
``question-mcq.schema.json`` (content format v1) field for field, so that the
API refuses anything the published contract would refuse.
``tests/unit/test_staff_content_models.py`` checks both against the same
vectors with a real JSON Schema validator.

On top of the schemas, three rules that a schema cannot express:
block keys are unique in a lesson, question keys and choice ids are unique, and
the correct choice is one of the offered choices.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

_STRICT = ConfigDict(extra="forbid", strict=True)

BlockKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
ChoiceId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class Heading(BaseModel):
    model_config = _STRICT
    key: BlockKey
    type: Literal["heading"]
    text: ShortText


class Paragraph(BaseModel):
    model_config = _STRICT
    key: BlockKey
    type: Literal["paragraph"]
    text: LongText


class Example(BaseModel):
    model_config = _STRICT
    key: BlockKey
    type: Literal["example"]
    title: ShortText | None = None
    steps: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=500)]],
        Field(min_length=1, max_length=20),
    ]

    @model_validator(mode="before")
    @classmethod
    def _title_is_absent_or_text(cls, data: Any) -> Any:
        # The schema allows the title to be absent, not to be null.
        if isinstance(data, dict) and "title" in data and data["title"] is None:
            raise ValueError("title must be text when present")
        return data


class Callout(BaseModel):
    model_config = _STRICT
    key: BlockKey
    type: Literal["callout"]
    tone: Literal["tip", "warning", "remember"]
    text: LongText


Block = Annotated[Heading | Paragraph | Example | Callout, Field(discriminator="type")]


class _Text1000(BaseModel):
    model_config = _STRICT
    text: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class _Text2000(BaseModel):
    model_config = _STRICT
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class Choice(BaseModel):
    model_config = _STRICT
    id: ChoiceId
    text: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class ResponseSpec(BaseModel):
    model_config = _STRICT
    choices: Annotated[list[Choice], Field(min_length=2, max_length=6)]


class AnswerKey(BaseModel):
    model_config = _STRICT
    correct_choice_id: ChoiceId


class McqQuestion(BaseModel):
    """One multiple-choice practice question (scoring rule ``mcq-v1``)."""

    model_config = _STRICT
    question_key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,80}$")]
    kind: Literal["mcq"] = "mcq"
    prompt: _Text1000
    response_spec: ResponseSpec
    answer_key: AnswerKey
    explanation: _Text2000

    @model_validator(mode="after")
    def _consistent_choices(self) -> McqQuestion:
        ids = [choice.id for choice in self.response_spec.choices]
        if len(set(ids)) != len(ids):
            raise ValueError("choice ids must be unique")
        if self.answer_key.correct_choice_id not in ids:
            raise ValueError("correct_choice_id must be one of the choices")
        return self


class RevisionContent(BaseModel):
    """Title, blocks and questions of one lesson revision in one language."""

    model_config = _STRICT
    title: ShortText
    blocks: Annotated[list[Block], Field(min_length=1, max_length=200)]
    questions: Annotated[list[McqQuestion], Field(max_length=50)] = []

    @model_validator(mode="after")
    def _unique_keys(self) -> RevisionContent:
        block_keys = [block.key for block in self.blocks]
        if len(set(block_keys)) != len(block_keys):
            raise ValueError("block keys must be unique within a lesson")
        question_keys = [question.question_key for question in self.questions]
        if len(set(question_keys)) != len(question_keys):
            raise ValueError("question keys must be unique within a lesson")
        return self

    def blocks_json(self) -> list[dict[str, Any]]:
        """Blocks exactly as the contract stores them (absent optional fields omitted)."""
        return [block.model_dump(exclude_none=True) for block in self.blocks]

    def questions_json(self) -> list[dict[str, Any]]:
        return [question.model_dump() for question in self.questions]
