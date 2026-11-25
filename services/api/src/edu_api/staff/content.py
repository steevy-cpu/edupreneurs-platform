"""Request models for lesson content written by staff.

They mirror ``packages/contracts/content/lesson-blocks.schema.json`` and
``question-mcq.schema.json`` (content format v1) field for field, so that the
API refuses anything the published contract would refuse.
``tests/unit/test_staff_content_models.py`` checks both against the same
vectors with a real JSON Schema validator.

On top of the schemas, four rules that a schema cannot express:
block keys are unique in a lesson, question keys and choice ids are unique,
the correct choice is one of the offered choices, and no text contains a
control character (Unicode category Cc: U+0000-U+001F, U+007F-U+009F) other
than tab and line feed (multi-line text; CRLF and CR are first turned into LF;
titles and URIs allow none). PostgreSQL cannot store U+0000 in ``text`` or ``jsonb``
at all, and the others have no place in text shown to learners.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

_STRICT = ConfigDict(extra="forbid", strict=True)

# Category Cc is exactly U+0000-U+001F and U+007F-U+009F.
# Multi-line text: CRLF and a lone CR become LF on input (Windows clients), then
# every control character except tab and LF is refused.
# Single-line text (titles, URIs): every control character is refused, CR and LF
# included.
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_ANY_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def normalise_line_endings(value: Any) -> Any:
    """CRLF and lone CR to LF; anything that is not a string is passed through."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    return value


def _refuse(pattern: re.Pattern[str], value: str, allowed: str) -> str:
    found = pattern.search(value)
    if found is not None:
        raise ValueError(f"control character U+{ord(found.group()):04X} is not allowed ({allowed})")
    return value


def _refuse_control_characters(value: str) -> str:
    return _refuse(_CONTROL_CHARACTER, value, "only tab and line feed are")


def _refuse_all_control_characters(value: str) -> str:
    return _refuse(_ANY_CONTROL_CHARACTER, value, "this is a single-line field")


#: Add to any multi-line free-text request field: normalises line endings, then
#: refuses control characters with 422. Put it AFTER the StringConstraints.
NoControlCharacters = AfterValidator(_refuse_control_characters)
#: Normaliser; goes first so that length limits count the stored text.
LineEndingsToLF = BeforeValidator(normalise_line_endings)
#: For titles and URIs: no control character at all (not even tab or line breaks).
SingleLine = AfterValidator(_refuse_all_control_characters)

BlockKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
LongText = Annotated[
    str, LineEndingsToLF, StringConstraints(min_length=1, max_length=4000), NoControlCharacters
]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200), SingleLine]
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
        list[
            Annotated[
                str,
                LineEndingsToLF,
                StringConstraints(min_length=1, max_length=500),
                NoControlCharacters,
            ]
        ],
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
    text: Annotated[
        str, LineEndingsToLF, StringConstraints(min_length=1, max_length=1000), NoControlCharacters
    ]


class _Text2000(BaseModel):
    model_config = _STRICT
    text: Annotated[
        str, LineEndingsToLF, StringConstraints(min_length=1, max_length=2000), NoControlCharacters
    ]


class Choice(BaseModel):
    model_config = _STRICT
    id: ChoiceId
    text: Annotated[
        str, LineEndingsToLF, StringConstraints(min_length=1, max_length=300), NoControlCharacters
    ]


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
