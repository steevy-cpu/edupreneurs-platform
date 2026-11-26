"""The tutoring pipeline, end to end.

    request
      -> enabled?                      (master switch)
      -> safety screen                 (a child in distress gets the reviewed message
                                        even when everything else is refused; no data
                                        leaves the server for it)
      -> kill switch -> consent -> entitlement
      -> manipulation / inappropriate  (reviewed message, no model call)
      -> approved lesson, as the learner (row-level security decides)
      -> retrieve relevant passages    (none -> "not in this lesson", no model call)
      -> build prompt                  (trusted system message + untrusted DATA)
      -> reserve worst-case cost       (atomic; refuses before any provider call)
      -> provider via gateway          (timeout, bounded retries, explicit fallback)
      -> validate output               (shape, language, citations, safety)
      -> settle real cost              (exactly once, also on failure or cancellation)
      -> cited answer

PRIVACY: this module never logs, stores or returns to anyone else the student's
message or the model's text. Log lines carry codes, counts and durations only.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from edu_api.tutor.budget import Reservation, UsageOutcome, UsageStore
from edu_api.tutor.config import TutorSettings
from edu_api.tutor.content import ApprovedLesson, LessonSource
from edu_api.tutor.errors import (
    ConsentRequired,
    InvalidModelOutput,
    InvalidTutorRequest,
    NotEntitled,
    ProviderTimeout,
    ProviderUnavailable,
    TutorDisabled,
    TutorError,
    TutorPaused,
)
from edu_api.tutor.gateway import Attempt, ModelGateway, Route
from edu_api.tutor.governance import ConsentGate, ConsentState, EntitlementGate
from edu_api.tutor.prompts import PromptTemplate, RenderedPrompt, StudentTurn
from edu_api.tutor.providers.base import ModelRequest, ModelResult
from edu_api.tutor.retrieval import LessonRetriever, RetrievalQuery, RetrievedContext
from edu_api.tutor.safety import (
    FixedMessage,
    ScreenAction,
    controlled_assessment_message,
    inappropriate_message,
    insufficient_context_message,
    manipulation_message,
    safety_support_message,
    screen_student_message,
)
from edu_api.tutor.text import estimate_tokens
from edu_api.tutor.types import (
    Grounding,
    Locale,
    Notice,
    ResponseSource,
    ResponseStatus,
    TutorAvailability,
    TutorIntent,
    TutorRequest,
    TutorResponse,
)
from edu_api.tutor.validation import ValidatedAnswer, validate_model_output

logger = logging.getLogger("edu_api.tutor")

#: From this support level on, a hint may use the reviewed explanation of the question.
_REVEAL_EXPLANATION_FROM_LEVEL = 3

_FAILURE_ERRORS: dict[str, type[TutorError]] = {
    "timeout": ProviderTimeout,
    "output_rejected": InvalidModelOutput,
}


@dataclass(frozen=True)
class TutorDependencies:
    settings: TutorSettings
    lessons: LessonSource
    retriever: LessonRetriever
    template: PromptTemplate
    gateway: ModelGateway
    usage: UsageStore
    consent: ConsentGate
    entitlements: EntitlementGate


class TutorService:
    def __init__(self, deps: TutorDependencies) -> None:
        self._d = deps

    # ------------------------------------------------------------------------------
    async def availability(self, learner_id: uuid.UUID) -> TutorAvailability:
        """Cheap probe for the app: can this learner ask Jude right now?"""
        try:
            await self._check_access(learner_id)
            usage = await self._d.usage.learner_usage(learner_id)
        except TutorError as exc:
            return TutorAvailability(available=False, reason=exc.code)
        except Exception as exc:
            logger.error("tutor availability probe failed: %s", type(exc).__name__)
            return TutorAvailability(available=False, reason=TutorError.code)
        limit_reached = usage.day_requests >= usage.daily_requests_limit
        return TutorAvailability(
            available=not limit_reached,
            reason="tutor_daily_limit_reached" if limit_reached else None,
            daily_requests_used=usage.day_requests,
            daily_requests_limit=usage.daily_requests_limit,
        )

    async def answer(self, learner_id: uuid.UUID, request: TutorRequest) -> TutorResponse:
        """Answer one request. Raises only ``TutorError`` (and task cancellation)."""
        started = time.monotonic()
        try:
            response = await self._answer(learner_id, request)
        except TutorError as exc:
            self._log(exc.code, started)
            raise
        except asyncio.CancelledError:
            self._log("cancelled", started)
            raise
        except Exception as exc:
            # The failure boundary: nothing unexpected escapes as anything but "unavailable".
            # Log the TYPE only — an exception message could carry request text.
            logger.error("tutor request failed unexpectedly: %s", type(exc).__name__)
            self._log(TutorError.code, started)
            raise TutorError() from None
        self._log(response.status.value, started)
        return response

    # ------------------------------------------------------------------------------
    async def _check_access(self, learner_id: uuid.UUID) -> None:
        settings = self._d.settings
        if not settings.enabled:
            raise TutorDisabled()
        if settings.paused or await self._d.usage.is_paused():
            raise TutorPaused()
        if await self._d.consent.tutor_consent(learner_id) is not ConsentState.GRANTED:
            raise ConsentRequired()
        if not await self._d.entitlements.may_use_tutor(learner_id):
            raise NotEntitled()

    async def _answer(self, learner_id: uuid.UUID, request: TutorRequest) -> TutorResponse:
        if not self._d.settings.enabled:
            raise TutorDisabled()
        language = request.answer_locale

        screen = screen_student_message(request.message)
        if screen.action is ScreenAction.SAFETY_SUPPORT:
            return self._fixed(
                request, ResponseStatus.SAFETY_SUPPORT, safety_support_message(language)
            )

        await self._check_access(learner_id)

        if screen.action is ScreenAction.DECLINE_MANIPULATION:
            return self._fixed(request, ResponseStatus.DECLINED, manipulation_message(language))
        if screen.action is ScreenAction.DECLINE_INAPPROPRIATE:
            return self._fixed(request, ResponseStatus.DECLINED, inappropriate_message(language))

        lesson = await self._d.lessons.get_approved_lesson(
            learner_id=learner_id,
            lesson_id=request.lesson_id,
            locale=request.locale,
            revision_id=request.lesson_revision_id,
        )
        turn = self._student_turn(request, lesson, screen.text)

        if lesson.assessment_mode == "controlled_assessment" and (
            request.question_key or request.intent in (TutorIntent.HINT, TutorIntent.EXPLAIN_ANSWER)
        ):
            return self._fixed(
                request,
                ResponseStatus.DECLINED,
                controlled_assessment_message(language),
                lesson=lesson,
            )

        context = self._d.retriever.retrieve(
            lesson,
            RetrievalQuery(
                text=screen.text,
                focus_block_key=request.focus_block_key,
                question_key=request.question_key,
                reveal_question_explanation=self._may_reveal_explanation(request),
            ),
        )
        if context.is_empty:
            return self._fixed(
                request,
                ResponseStatus.INSUFFICIENT_CONTEXT,
                insufficient_context_message(language),
                lesson=lesson,
            )

        prompt = self._d.template.render(
            language=language,
            lesson_title=lesson.title,
            lesson_locale=lesson.locale,
            context=context,
            student=turn,
        )
        answer = await self._ask_model(learner_id, request, lesson, context, prompt, language)

        notices: list[Notice] = []
        if screen.personal_info_removed:
            notices.append(Notice.PERSONAL_INFO_REMOVED)
        if answer.status is ResponseStatus.SAFETY_SUPPORT:
            return self._fixed(
                request,
                ResponseStatus.SAFETY_SUPPORT,
                safety_support_message(language),
                lesson=lesson,
            )
        if answer.status is ResponseStatus.DECLINED:
            return self._fixed(
                request, ResponseStatus.DECLINED, inappropriate_message(language), lesson=lesson
            )
        if answer.status is ResponseStatus.INSUFFICIENT_CONTEXT:
            return self._fixed(
                request,
                ResponseStatus.INSUFFICIENT_CONTEXT,
                insufficient_context_message(language),
                lesson=lesson,
            )
        if answer.grounding is Grounding.GENERAL:
            notices.append(Notice.GENERAL_KNOWLEDGE)
        return TutorResponse(
            request_id=request.idempotency_key,
            status=ResponseStatus.ANSWERED,
            source=ResponseSource.MODEL,
            grounding=answer.grounding,
            language=language,
            explanation=answer.explanation,
            hint=answer.hint,
            check_question=answer.check_question,
            references=list(answer.references),
            next_action=answer.next_action,
            answer_was_correct=turn.answer_is_correct,
            notices=notices,
            lesson_revision_id=lesson.revision_id,
            prompt_version=prompt.version,
        )

    # ------------------------------------------------------------------------------
    @staticmethod
    def _may_reveal_explanation(request: TutorRequest) -> bool:
        if request.intent is TutorIntent.EXPLAIN_ANSWER:
            return True
        return request.support_level >= _REVEAL_EXPLANATION_FROM_LEVEL

    @staticmethod
    def _student_turn(
        request: TutorRequest, lesson: ApprovedLesson, screened_message: str | None
    ) -> StudentTurn:
        """Check the request against the lesson and decide correctness on the server."""
        if request.focus_block_key and lesson.block(request.focus_block_key) is None:
            raise InvalidTutorRequest("focus_block_key is not in this revision")
        answer_is_correct: bool | None = None
        selected_text: str | None = None
        if request.question_key:
            question = lesson.question(request.question_key)
            if question is None:
                raise InvalidTutorRequest("question_key is not in this revision")
            if request.selected_choice_id:
                choice = next(
                    (c for c in question.choices if c.id == request.selected_choice_id), None
                )
                if choice is None or question.correct_choice_id is None:
                    raise InvalidTutorRequest("selected_choice_id is not a choice of the question")
                selected_text = choice.text
                if request.intent is TutorIntent.EXPLAIN_ANSWER:
                    answer_is_correct = choice.id == question.correct_choice_id
        return StudentTurn(
            intent=request.intent,
            message=screened_message,
            support_level=request.support_level,
            answer_is_correct=answer_is_correct,
            selected_choice_text=selected_text,
        )

    async def _ask_model(
        self,
        learner_id: uuid.UUID,
        request: TutorRequest,
        lesson: ApprovedLesson,
        context: RetrievedContext,
        prompt: RenderedPrompt,
        language: Locale,
    ) -> ValidatedAnswer:
        settings = self._d.settings
        gateway = self._d.gateway
        input_estimate = sum(estimate_tokens(m.content) for m in prompt.messages)
        reservation = await self._d.usage.reserve(
            learner_id=learner_id,
            request_key=request.idempotency_key,
            estimate_micro=gateway.worst_case_micro(
                input_tokens=input_estimate, max_output_tokens=settings.max_output_tokens
            ),
        )

        def build(route: Route) -> ModelRequest:
            return ModelRequest(
                messages=prompt.messages,
                model=route.model,
                max_output_tokens=settings.max_output_tokens,
                temperature=settings.temperature,
            )

        def parse(result: ModelResult) -> ValidatedAnswer:
            return validate_model_output(
                result.text,
                context=context,
                expected_language=language,
                canary=self._d.template.canary,
                allow_general=settings.allow_general_answers,
            )

        attempts: list[Attempt] = []
        outcome_code = TutorError.code
        succeeded = False
        try:
            result = await gateway.run(build, parse, attempts)
            if result.value is not None:
                succeeded = True
                outcome_code = "answered"
                return result.value
            error = _FAILURE_ERRORS.get(result.failure or "", ProviderUnavailable)
            outcome_code = error.code
            raise error(result.failure)
        except asyncio.CancelledError:
            outcome_code = "cancelled"
            raise
        finally:
            # Shielded: the cost of what already happened is recorded even if the
            # client went away and this task is being cancelled.
            await asyncio.shield(
                self._settle(
                    reservation,
                    attempts,
                    input_estimate=input_estimate,
                    outcome=outcome_code,
                    succeeded=succeeded,
                    prompt_version=prompt.version,
                    lesson=lesson,
                )
            )

    async def _settle(
        self,
        reservation: Reservation,
        attempts: list[Attempt],
        *,
        input_estimate: int,
        outcome: str,
        succeeded: bool,
        prompt_version: str,
        lesson: ApprovedLesson,
    ) -> None:
        max_output = self._d.settings.max_output_tokens
        spent = input_tokens = output_tokens = 0
        for attempt in attempts:
            if attempt.usage is not None:
                spent += attempt.price.cost_micro(attempt.usage)
                input_tokens += attempt.usage.input_tokens
                output_tokens += attempt.usage.output_tokens
            elif attempt.usage_unknown:
                # No figures, but the provider may have billed: charge the worst case.
                spent += self._d.gateway.attempt_worst_case_micro(
                    attempt, input_tokens=input_estimate, max_output_tokens=max_output
                )
        if not succeeded and spent == 0:
            # Provably nothing was spent (no call went out, or every call was refused
            # before any work): give the hold back, so the same request may be retried.
            await self._d.usage.release(reservation, outcome=outcome)
            return
        last = attempts[-1]
        await self._d.usage.settle(
            reservation,
            UsageOutcome(
                spent_micro=spent,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                attempts=len(attempts),
                outcome=outcome,
                counts_as_request=succeeded,
                provider=last.provider,
                model=last.model,
                price_version=last.price.price_version,
                prompt_version=prompt_version,
                lesson_revision_id=lesson.revision_id,
            ),
        )

    def _fixed(
        self,
        request: TutorRequest,
        status: ResponseStatus,
        message: FixedMessage,
        *,
        lesson: ApprovedLesson | None = None,
    ) -> TutorResponse:
        return TutorResponse(
            request_id=request.idempotency_key,
            status=status,
            source=ResponseSource.REVIEWED_TEMPLATE,
            grounding=Grounding.NONE,
            language=request.answer_locale,
            explanation=message.text,
            next_action=message.next_action,
            notices=[message.notice],
            lesson_revision_id=lesson.revision_id if lesson else None,
        )

    def _log(self, outcome: str, started: float) -> None:
        # Outcome and duration only. No learner id, no lesson text, no question, no answer.
        logger.info("tutor request outcome=%s ms=%d", outcome, (time.monotonic() - started) * 1000)
