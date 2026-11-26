"""The benchmark dataset: synthetic bilingual lessons and the cases built on them.

Two sources, both plain JSON a teacher can read:

* ``dataset/lessons/*.json`` — one lesson per grade in French and Haitian Creole
  with identical block keys, a few practice questions, and "probes" (the same
  question in both languages with the blocks that answer it).
* ``dataset/special_cases.json`` — hand-written cases: prompt injection,
  unsupported claims, boundaries, provider failures, simple language, Creole.

``build_cases`` expands the lesson packs deterministically and appends the
special cases. ``dataset/cases.jsonl`` is that list written out for reviewers;
a test fails if it is stale.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from edu_api.tutor.content import ApprovedLesson, LessonBlock, parse_blocks, parse_question
from edu_api.tutor.types import Locale
from jude_eval import DATASET_DIR

Layer = Literal["model", "pipeline"]
LOCALES: tuple[Locale, ...] = ("fr", "ht")

SUITES: tuple[str, ...] = (
    "math_reasoning",
    "lesson_explanation",
    "progressive_hints",
    "worked_examples",
    "incorrect_answers",
    "simple_language",
    "creole_fluency",
    "retrieval_fr_to_ht",
    "retrieval_ht_to_fr",
    "prompt_injection",
    "unsupported_claims",
    "boundaries",
    "provider_failures",
)


@dataclass(frozen=True)
class Probe:
    id: str
    kind: str
    text: dict[str, str]
    gold: tuple[str, ...]


@dataclass(frozen=True)
class LessonPack:
    slug: str
    grade: str
    lesson_id: uuid.UUID
    lessons: dict[str, ApprovedLesson]
    probes: tuple[Probe, ...]
    hint_question_key: str
    final_answer_patterns: tuple[str, ...]
    final_answer_text: str
    wrong_question_key: str
    wrong_choice: str
    worked_example_block: str
    raw: dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def lesson(self, locale: str) -> ApprovedLesson:
        return self.lessons[locale]


@dataclass(frozen=True)
class Expectation:
    #: Acceptable results. Model layer: ``status`` or ``status/grounding``.
    #: Pipeline layer: a response status or a ``tutor_*`` error code.
    outcomes: tuple[str, ...] = ()
    #: Block keys of which at least one should be cited.
    gold: tuple[str, ...] = ()
    #: Regular expressions that must NOT match the output.
    forbid: tuple[str, ...] = ()
    #: Regular expressions of which at least one must match.
    require_any: tuple[str, ...] = ()
    provider_calls: int | None = None
    #: ``zero`` | ``positive`` | ``worst_case`` (pipeline layer).
    spend: str | None = None
    notices_include: tuple[str, ...] = ()


@dataclass(frozen=True)
class Poison:
    """Text appended to one lesson block to simulate an instruction hidden in content."""

    block: str
    text: str


@dataclass(frozen=True)
class Case:
    id: str
    suite: str
    lesson: str
    locale: Locale
    intent: str
    response_locale: Locale | None = None
    message: str | None = None
    focus_block_key: str | None = None
    question_key: str | None = None
    selected_choice_id: str | None = None
    support_level: int = 1
    layers: tuple[Layer, ...] = ("model",)
    poison: Poison | None = None
    fault: tuple[str, ...] = ()
    expect_model: Expectation | None = None
    expect_pipeline: Expectation | None = None
    #: Human-review rubrics that apply: ``teaching``, ``creole``.
    review: tuple[str, ...] = ()
    note: str = ""

    @property
    def answer_locale(self) -> Locale:
        return self.response_locale or self.locale

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in (None, "", (), [])}


def _lesson(raw: dict[str, Any], lesson_id: uuid.UUID, locale: Locale) -> ApprovedLesson:
    revision = raw["revisions"][locale]
    return ApprovedLesson(
        lesson_id=lesson_id,
        revision_id=uuid.UUID(revision["revision_id"]),
        revision=revision["revision"],
        locale=locale,
        title=revision["title"],
        blocks=parse_blocks(revision["blocks"]),
        questions=tuple(parse_question(**q) for q in revision["questions"]),
    )


def load_packs(directory: Path | None = None) -> dict[str, LessonPack]:
    packs: dict[str, LessonPack] = {}
    for path in sorted((directory or DATASET_DIR / "lessons").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        lesson_id = uuid.UUID(raw["lesson_id"])
        packs[raw["slug"]] = LessonPack(
            slug=raw["slug"],
            grade=raw["grade"],
            lesson_id=lesson_id,
            lessons={locale: _lesson(raw, lesson_id, locale) for locale in LOCALES},
            probes=tuple(
                Probe(p["id"], p["kind"], {"fr": p["fr"], "ht": p["ht"]}, tuple(p["gold"]))
                for p in raw["probes"]
            ),
            hint_question_key=raw["hint_problem"]["question_key"],
            final_answer_patterns=tuple(raw["hint_problem"]["final_answer_patterns"]),
            final_answer_text=raw["hint_problem"]["final_answer_text"],
            wrong_question_key=raw["wrong_answer"]["question_key"],
            wrong_choice=raw["wrong_answer"]["choice"],
            worked_example_block=raw["worked_example_block"],
            raw=raw,
        )
    return packs


def poisoned(lesson: ApprovedLesson, poison: Poison) -> ApprovedLesson:
    """The lesson with ``poison.text`` appended to one block (keys unchanged)."""
    if lesson.block(poison.block) is None:
        raise ValueError(f"no block {poison.block!r} to poison")
    return replace(
        lesson,
        blocks=tuple(
            LessonBlock(b.key, b.type, f"{b.text} {poison.text}") if b.key == poison.block else b
            for b in lesson.blocks
        ),
    )


def _expectation(raw: dict[str, Any] | None) -> Expectation | None:
    if raw is None:
        return None
    return Expectation(
        outcomes=tuple(raw.get("outcomes", ())),
        gold=tuple(raw.get("gold", ())),
        forbid=tuple(raw.get("forbid", ())),
        require_any=tuple(raw.get("require_any", ())),
        provider_calls=raw.get("provider_calls"),
        spend=raw.get("spend"),
        notices_include=tuple(raw.get("notices_include", ())),
    )


def _generated(packs: dict[str, LessonPack]) -> list[Case]:
    cases: list[Case] = []
    for index, pack in enumerate(packs.values()):
        # 1. Every probe, asked in each language against each language's revision.
        for probe in pack.probes:
            for question_locale in LOCALES:
                for lesson_locale in LOCALES:
                    if question_locale == lesson_locale:
                        suite = (
                            "math_reasoning" if probe.kind == "reasoning" else "lesson_explanation"
                        )
                    else:
                        suite = f"retrieval_{question_locale}_to_{lesson_locale}"
                    review = ("teaching", "creole") if question_locale == "ht" else ("teaching",)
                    cases.append(
                        Case(
                            id=f"probe-{pack.slug}-{probe.id}-{question_locale}-on-{lesson_locale}",
                            suite=suite,
                            lesson=pack.slug,
                            locale=lesson_locale,
                            response_locale=question_locale,
                            intent="ask_question"
                            if probe.kind == "reasoning"
                            else "explain_concept",
                            message=probe.text[question_locale],
                            expect_model=Expectation(
                                outcomes=("answered/lesson",), gold=probe.gold
                            ),
                            review=review,
                        )
                    )
        # 2. Progressive hints: one practice question at every support level.
        hint_locale: Locale = LOCALES[index % 2]
        for level in (1, 2, 3, 4):
            cases.append(
                Case(
                    id=f"hint-{pack.slug}-{hint_locale}-level-{level}",
                    suite="progressive_hints",
                    lesson=pack.slug,
                    locale=hint_locale,
                    intent="hint",
                    question_key=pack.hint_question_key,
                    support_level=level,
                    expect_model=Expectation(
                        outcomes=("answered/lesson", "answered/general"),
                        # Levels 1-3 must not hand over the result. Level 4 is a worked
                        # example of a RELATED problem: whether it went too far is a
                        # human judgement, so it is not auto-checked.
                        forbid=pack.final_answer_patterns if level <= 3 else (),
                    ),
                    review=("teaching", "creole") if hint_locale == "ht" else ("teaching",),
                )
            )
        # 3. Another worked example of the lesson's example.
        example_locale: Locale = LOCALES[(index + 1) % 2]
        cases.append(
            Case(
                id=f"example-{pack.slug}-{example_locale}",
                suite="worked_examples",
                lesson=pack.slug,
                locale=example_locale,
                intent="another_example",
                focus_block_key=pack.worked_example_block,
                expect_model=Expectation(
                    outcomes=("answered/general", "answered/lesson"),
                    gold=(pack.worked_example_block,),
                ),
                review=("teaching", "creole") if example_locale == "ht" else ("teaching",),
            )
        )
        # 4. Why was my answer wrong? (both languages), and one correct answer.
        for locale in LOCALES:
            cases.append(
                Case(
                    id=f"wrong-{pack.slug}-{locale}",
                    suite="incorrect_answers",
                    lesson=pack.slug,
                    locale=locale,
                    intent="explain_answer",
                    question_key=pack.wrong_question_key,
                    selected_choice_id=pack.wrong_choice,
                    expect_model=Expectation(outcomes=("answered/lesson",)),
                    review=("teaching", "creole") if locale == "ht" else ("teaching",),
                )
            )
        correct = pack.lesson("fr").question(pack.wrong_question_key)
        if index % 3 == 0 and correct is not None and correct.correct_choice_id:
            cases.append(
                Case(
                    id=f"right-{pack.slug}-fr",
                    suite="incorrect_answers",
                    lesson=pack.slug,
                    locale="fr",
                    intent="explain_answer",
                    question_key=pack.wrong_question_key,
                    selected_choice_id=correct.correct_choice_id,
                    expect_model=Expectation(outcomes=("answered/lesson",)),
                    review=("teaching",),
                    note="The answer is correct: the reply must not call it wrong.",
                )
            )
    return cases


def _special(path: Path | None = None) -> list[Case]:
    raw = json.loads((path or DATASET_DIR / "special_cases.json").read_text(encoding="utf-8"))
    cases: list[Case] = []
    for item in raw["cases"]:
        poison = item.get("poison")
        expect = item.get("expect", {})
        cases.append(
            Case(
                id=item["id"],
                suite=item["suite"],
                lesson=item["lesson"],
                locale=item["locale"],
                response_locale=item.get("response_locale"),
                intent=item["intent"],
                message=item.get("message"),
                focus_block_key=item.get("focus_block_key"),
                question_key=item.get("question_key"),
                selected_choice_id=item.get("selected_choice_id"),
                support_level=item.get("support_level", 1),
                layers=tuple(item.get("layers", ("model",))),
                poison=Poison(poison["block"], poison["text"]) if poison else None,
                fault=tuple(item.get("fault", ())),
                expect_model=_expectation(expect.get("model")),
                expect_pipeline=_expectation(expect.get("pipeline")),
                review=tuple(item.get("review", ())),
                note=item.get("note", ""),
            )
        )
    return cases


def build_cases(packs: dict[str, LessonPack] | None = None) -> list[Case]:
    packs = packs or load_packs()
    cases = _generated(packs) + _special()
    validate_cases(cases, packs)
    return cases


def validate_cases(cases: list[Case], packs: dict[str, LessonPack]) -> None:
    """Fail loudly on a dataset mistake rather than score against a broken case."""
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id}")
        seen.add(case.id)
        if case.suite not in SUITES:
            raise ValueError(f"{case.id}: unknown suite {case.suite}")
        lesson = packs[case.lesson].lesson(case.locale)
        keys = {b.key for b in lesson.blocks}
        if case.focus_block_key and case.focus_block_key not in keys:
            raise ValueError(f"{case.id}: focus block not in lesson")
        if case.question_key and lesson.question(case.question_key) is None:
            raise ValueError(f"{case.id}: question not in lesson")
        if case.poison and case.poison.block not in keys:
            raise ValueError(f"{case.id}: poisoned block not in lesson")
        for layer, expectation in (
            ("model", case.expect_model),
            ("pipeline", case.expect_pipeline),
        ):
            if layer in case.layers and expectation is None:
                raise ValueError(f"{case.id}: runs in the {layer} layer without an expectation")
            if expectation is None:
                continue
            if not set(expectation.gold) <= keys:
                raise ValueError(f"{case.id}: gold key not in lesson")
            for pattern in (*expectation.forbid, *expectation.require_any):
                re.compile(pattern)


def cases_jsonl(cases: list[Case]) -> str:
    return "".join(
        json.dumps(case.to_json(), ensure_ascii=False, sort_keys=True) + "\n" for case in cases
    )


def suite_counts(cases: list[Case]) -> dict[str, int]:
    return {suite: sum(1 for c in cases if c.suite == suite) for suite in SUITES}
