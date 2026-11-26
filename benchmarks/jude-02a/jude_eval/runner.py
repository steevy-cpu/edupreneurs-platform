"""Running the benchmark.

Two layers, because they answer different questions:

* MODEL layer — "what does this model return for the prompt Jude would send?"
  One call per case, no retries, the raw reply scored. Jude-01's safeguarding
  screen is deliberately bypassed here: the point is to see what the model does
  when the screen misses something.
* PIPELINE layer — "what does a learner get, and what does it cost, when this
  model sits behind the whole Jude-01 service?" Screens, retrieval, budget,
  retries and validation all apply; provider faults can be injected.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from edu_api.tutor.budget import InMemoryUsageStore
from edu_api.tutor.config import PriceEntry, TutorSettings
from edu_api.tutor.content import ApprovedLesson, InMemoryLessonSource
from edu_api.tutor.errors import TutorError
from edu_api.tutor.factory import build_tutor_service
from edu_api.tutor.governance import ConsentState, StaticConsent, StaticEntitlements
from edu_api.tutor.prompts import PromptTemplate, get_template
from edu_api.tutor.providers.base import ModelProvider, ModelRequest, ProviderError, TokenUsage
from edu_api.tutor.retrieval import (
    ContextPassage,
    LessonRetriever,
    RetrievalQuery,
    RetrievedContext,
    lesson_passages,
    question_passage,
)
from edu_api.tutor.service import TutorService
from edu_api.tutor.types import TutorRequest
from jude_eval.candidates import Candidate, FaultInjector, VirtualClock
from jude_eval.dataset import Case, LessonPack, poisoned
from jude_eval.metrics import ModelCaseResult, PipelineCaseResult, score_model_reply
from jude_eval.retrieval_bench import recommended_ranker

#: A learner that does not exist. Every request in the benchmark is made as this id.
SYNTHETIC_LEARNER = uuid.UUID("5e000000-0000-4000-8000-0000000002a0")
_REVEAL_FROM_LEVEL = 3


@dataclass(frozen=True)
class RunSettings:
    prompt_version: str = "jude-tutor.v1"
    max_output_tokens: int = 500
    temperature: float = 0.2
    top_k: int = 4
    max_context_chars: int = 6000


class RunStopped(Exception):
    """The run must stop now (for example the spending cap was reached)."""


def lesson_for(case: Case, pack: LessonPack) -> ApprovedLesson:
    lesson = pack.lesson(case.locale)
    return poisoned(lesson, case.poison) if case.poison else lesson


def tutor_request(case: Case, pack: LessonPack) -> TutorRequest:
    lesson = pack.lesson(case.locale)
    return TutorRequest.model_validate(
        {
            "idempotency_key": uuid.uuid5(SYNTHETIC_LEARNER, case.id),
            "lesson_id": lesson.lesson_id,
            "lesson_revision_id": lesson.revision_id,
            "locale": case.locale,
            "response_locale": case.response_locale,
            "intent": case.intent,
            "message": case.message,
            "focus_block_key": case.focus_block_key,
            "question_key": case.question_key,
            "selected_choice_id": case.selected_choice_id,
            "support_level": case.support_level,
        }
    )


def build_context(
    case: Case, pack: LessonPack, settings: RunSettings
) -> tuple[RetrievedContext, str]:
    """The passages a model sees for this case, and whether retrieval found them.

    When retrieval finds nothing the gold blocks are supplied instead, so a model
    is still measured on the case; ``context_source`` records that it happened.
    """
    lesson = lesson_for(case, pack)
    reveal = case.intent == "explain_answer" or case.support_level >= _REVEAL_FROM_LEVEL
    retriever = LessonRetriever(
        recommended_ranker(pack, case.locale),
        top_k=settings.top_k,
        max_context_chars=settings.max_context_chars,
    )
    context = retriever.retrieve(
        lesson,
        RetrievalQuery(
            text=case.message,
            focus_block_key=case.focus_block_key,
            question_key=case.question_key,
            reveal_question_explanation=reveal,
        ),
    )
    if not context.is_empty:
        return context, "retrieved"
    gold = case.expect_model.gold if case.expect_model else ()
    chosen = [p for p in lesson_passages(lesson) if p.ref.key in gold] or lesson_passages(lesson)[
        :3
    ]
    if case.question_key:
        question = question_passage(lesson, case.question_key, with_explanation=reveal)
        if question is not None:
            chosen.append(question)
    return (
        RetrievedContext(
            tuple(ContextPassage(f"P{i}", p) for i, p in enumerate(chosen, start=1)),
            "gold-fallback",
        ),
        "gold",
    )


async def run_model_layer(
    candidate: Candidate,
    cases: Sequence[Case],
    packs: dict[str, LessonPack],
    *,
    settings: RunSettings | None = None,
    clock: VirtualClock | Callable[[], float] | None = None,
    provider: ModelProvider | None = None,
) -> list[ModelCaseResult]:
    settings = settings or RunSettings()
    template: PromptTemplate = get_template(settings.prompt_version)
    virtual = clock if isinstance(clock, VirtualClock) else VirtualClock()
    now: Callable[[], float] = clock if clock is not None else virtual
    provider = provider or candidate.make_provider(virtual)
    results: list[ModelCaseResult] = []
    for case in cases:
        if "model" not in case.layers:
            continue
        pack = packs[case.lesson]
        lesson = lesson_for(case, pack)
        request = tutor_request(case, pack)
        context, source = build_context(case, pack, settings)
        # Same server-side decision the service makes (answer correctness, chosen text).
        turn = TutorService._student_turn(request, lesson, case.message)
        prompt = template.render(
            language=case.answer_locale,
            lesson_title=lesson.title,
            lesson_locale=lesson.locale,
            context=context,
            student=turn,
        )
        if hasattr(provider, "bind"):
            provider.bind(case, pack, context)
        started = now()
        failure: str | None = None
        try:
            reply = await provider.complete(
                ModelRequest(
                    messages=prompt.messages,
                    model=candidate.model,
                    max_output_tokens=settings.max_output_tokens,
                    temperature=settings.temperature,
                )
            )
            raw, usage = reply.text, reply.usage
        except RunStopped:
            raise
        except ProviderError as exc:
            raw, usage = "", TokenUsage(0, 0)
            failure = f"provider_{exc.kind}"
        result = score_model_reply(
            case,
            raw,
            candidate=candidate.name,
            context=context,
            context_source=source,
            canary=template.canary,
            usage=usage,
            price=candidate.price,
            latency_ms=(now() - started) * 1000,
            max_output_tokens=settings.max_output_tokens,
        )
        if failure:
            result.rejection = failure
        results.append(result)
    return results


async def _no_sleep(_: float) -> None:
    return None


async def run_pipeline_layer(
    candidate: Candidate,
    cases: Sequence[Case],
    packs: dict[str, LessonPack],
    *,
    settings: RunSettings | None = None,
    provider_timeout_s: float = 0.05,
) -> list[PipelineCaseResult]:
    """Each case through a fresh Jude-01 service with this candidate behind it."""
    settings = settings or RunSettings()
    results: list[PipelineCaseResult] = []
    for case in cases:
        if "pipeline" not in case.layers or case.expect_pipeline is None:
            continue
        pack = packs[case.lesson]
        tutor_settings = TutorSettings(
            _env_file=None,
            enabled=True,
            model=candidate.model,
            prices=(
                PriceEntry(
                    price_version=candidate.price.price_version,
                    model=candidate.model,
                    input_micro_per_mtok=candidate.price.input_micro_per_mtok,
                    output_micro_per_mtok=candidate.price.output_micro_per_mtok,
                ),
            ),
            prompt_version=settings.prompt_version,
            max_output_tokens=settings.max_output_tokens,
            temperature=settings.temperature,
            retrieval_top_k=settings.top_k,
            max_context_chars=settings.max_context_chars,
            request_timeout_s=provider_timeout_s,
            max_attempts=2,
            learner_daily_requests=10_000,
            learner_daily_micro=10**12,
            learner_monthly_micro=10**12,
            global_monthly_micro=10**12,
        )
        lessons = InMemoryLessonSource()
        for locale in ("fr", "ht"):
            lesson = pack.lesson(locale)
            lessons.add(
                poisoned(lesson, case.poison) if case.poison and locale == case.locale else lesson
            )
        usage = InMemoryUsageStore(tutor_settings.budget_policy(), clock=lambda: datetime.now(UTC))
        injector = FaultInjector(candidate.make_provider(VirtualClock()), case.fault)
        injector.bind(case, pack, None)
        service = build_tutor_service(
            tutor_settings,
            lessons=lessons,
            usage=usage,
            consent=StaticConsent({SYNTHETIC_LEARNER: ConsentState.GRANTED}),
            entitlements=StaticEntitlements({SYNTHETIC_LEARNER}),
            provider=injector,
            # The retrieval strategy the benchmark recommends, so that a model is
            # not blamed for passages Jude-01's baseline ranker failed to find.
            ranker=recommended_ranker(pack, case.locale),
            retry_sleep=_no_sleep,
        )
        text, notices = "", []
        try:
            response = await service.answer(SYNTHETIC_LEARNER, tutor_request(case, pack))
            outcome = response.status.value
            text = "\n".join(
                p for p in (response.explanation, response.hint, response.check_question) if p
            )
            notices = [n.value for n in response.notices]
        except TutorError as exc:
            outcome = exc.code
        expected = case.expect_pipeline
        records = usage.records()
        spent = sum(r.spent_micro for r in records)
        reserved = sum(r.reserved_micro for r in records)
        spend_ok: bool | None = None
        if expected.spend == "zero":
            spend_ok = spent == 0
        elif expected.spend == "positive":
            spend_ok = 0 < spent <= reserved
        elif expected.spend == "worst_case":
            spend_ok = spent == reserved > 0
        results.append(
            PipelineCaseResult(
                case_id=case.id,
                suite=case.suite,
                candidate=candidate.name,
                outcome=outcome,
                outcome_ok=outcome in expected.outcomes,
                provider_calls=injector.calls,
                provider_calls_ok=(
                    None
                    if expected.provider_calls is None
                    else injector.calls == expected.provider_calls
                ),
                spent_micro=spent,
                reserved_micro=reserved,
                spend_ok=spend_ok,
                forbidden_hits=[p for p in expected.forbid if re.search(p, text)],
                notices_ok=(
                    None
                    if not expected.notices_include
                    else all(n in notices for n in expected.notices_include)
                ),
                notices=notices,
            )
        )
    return results


def wall_clock() -> float:
    """Real time, for live runs. Offline runs use ``VirtualClock`` instead."""
    return time.perf_counter()
