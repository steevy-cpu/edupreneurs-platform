"""The tutoring pipeline, end to end.

    request
      -> enabled?                      (master switch)
      -> safety screen                 (a message the phrase list recognises gets the
                                        fixed supportive text even when everything
                                        else is refused; no data leaves the server
                                        for it. The list and the text are NOT yet
                                        professionally reviewed.)
      -> kill switch -> consent -> entitlement
      -> manipulation / inappropriate  (fixed message, no model call)
      -> approved lesson, as the learner (row-level security decides)
      -> retrieve relevant passages    (none -> "not in this lesson", no model call)
      -> build prompt                  (trusted system message + untrusted DATA)
      -> reserve the assumed worst case (atomic; refuses before any provider call)
      -> authorise each provider call  (kill switch + hold re-checked every time)
      -> provider via gateway          (timeout, bounded retries, explicit fallback)
      -> validate output               (shape, language, citations, safety)
      -> settle real cost              (exactly once, also on failure or cancellation)
      -> cited answer

ACCOUNTING RULE: a hold is given back only when no provider call that could be
billed was made. A call whose answer was thrown away — rejected, or lost to a
fault in this server — is still charged: at its reported usage when there is
one, at the bound when there is not.

PRIVACY: this module never logs, stores or returns to anyone else the student's
message or the model's text. Log lines carry codes, counts and durations only.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from edu_api.tutor.budget import AttemptCharge, Reservation, UsageOutcome, UsageStore
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
from edu_api.tutor.metering import AttemptBound, InputBound
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
    # A fault in this server's own check: the generic "unavailable".
    "validation_failed": TutorError,
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
    input_bound: InputBound


class TutorService:
    def __init__(self, deps: TutorDependencies) -> None:
        self._d = deps
        #: Clean-up of holds whose admission was cancelled. Ids only, no text.
        self._background: set[asyncio.Task[None]] = set()

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
        else:
            self._log(response.status.value, started)
            return response
        # Raised OUTSIDE the handler, so the error handed to the caller does not
        # carry the original exception and, through its traceback, the prompt.
        raise TutorError()

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
        usage = self._d.usage
        # The most ONE call is assumed to bill; the hold is that, for every permitted call.
        bound = AttemptBound(
            input_tokens=self._d.input_bound.tokens(prompt.messages),
            output_tokens=settings.max_output_tokens,
        )
        reservation = await self._reserve(
            learner_id, request.idempotency_key, gateway.worst_case_micro(bound)
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

        async def authorize() -> None:
            await usage.authorize_dispatch(reservation)

        attempts: list[Attempt] = []
        outcome_code = TutorError.code
        succeeded = False
        try:
            result = await gateway.run(build, parse, attempts, authorize=authorize, bound=bound)
            if result.value is not None:
                succeeded = True
                outcome_code = "answered"
                return result.value
            error = _FAILURE_ERRORS.get(result.failure or "", ProviderUnavailable)
            outcome_code = error.code
            raise error(result.failure)
        except TutorError as exc:
            outcome_code = exc.code
            raise
        except asyncio.CancelledError:
            outcome_code = "cancelled"
            raise
        finally:
            # Shielded: the cost of what already happened is recorded even if the
            # client went away and this task is being cancelled.
            await asyncio.shield(
                self._finalize(
                    reservation,
                    attempts,
                    bound=bound,
                    outcome=outcome_code,
                    succeeded=succeeded,
                    prompt_version=prompt.version,
                    lesson=lesson,
                )
            )

    async def _reserve(
        self, learner_id: uuid.UUID, request_key: uuid.UUID, estimate_micro: int
    ) -> Reservation:
        """Take the hold. If the caller goes away meanwhile, give it straight back.

        Without this a cancelled request could leave a hold nobody knows about,
        which would then expire and be charged in full although nothing was sent.
        """
        admission = asyncio.ensure_future(
            self._d.usage.reserve(
                learner_id=learner_id, request_key=request_key, estimate_micro=estimate_micro
            )
        )
        try:
            return await asyncio.shield(admission)
        except asyncio.CancelledError:
            cleanup = asyncio.ensure_future(self._release_orphan(admission))
            self._background.add(cleanup)
            cleanup.add_done_callback(self._background.discard)
            raise

    async def _release_orphan(self, admission: asyncio.Future[Reservation]) -> None:
        try:
            reservation = await admission
        except BaseException:
            return  # the hold was refused or never made: nothing to give back
        try:
            await self._d.usage.release(reservation, outcome="cancelled", refused_attempts=0)
        except Exception as exc:
            # The hold stays and expires at its full amount: the safe direction.
            logger.error("tutor orphan hold not released: %s", type(exc).__name__)

    async def _finalize(
        self,
        reservation: Reservation,
        attempts: list[Attempt],
        *,
        bound: AttemptBound,
        outcome: str,
        succeeded: bool,
        prompt_version: str,
        lesson: ApprovedLesson,
    ) -> None:
        """Settle or release ONE reservation, exactly once, from the attempt list.

        * a call that reported usage is charged that usage at its own price;
        * a call that may have been billed without figures is charged the bound;
        * only when NO call could have been billed is the hold given back.
        """
        charges: list[AttemptCharge] = []
        for attempt in attempts:
            if not attempt.billable:
                continue
            metered = attempt.usage is not None
            usage = attempt.usage if attempt.usage is not None else bound.as_usage()
            charges.append(
                AttemptCharge(
                    provider=attempt.provider,
                    model=attempt.model,
                    price_version=attempt.price.price_version,
                    outcome=attempt.outcome,
                    metered=metered,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_micro=attempt.price.cost_micro(usage),
                    over_bound=attempt.over_bound,
                )
            )
        if not charges:
            # Every dispatched call (if any) was refused by the provider before it did
            # any work. The store cross-checks that count against its own.
            released = await self._d.usage.release(
                reservation,
                outcome=outcome,
                refused_attempts=sum(1 for a in attempts if a.refused_by_provider),
            )
            if released != "released":
                logger.warning("tutor hold not released: result=%s", released)
            return
        last = charges[-1]
        violations = sum(1 for c in charges if c.over_bound)
        settled = await self._d.usage.settle(
            reservation,
            UsageOutcome(
                spent_micro=sum(c.cost_micro for c in charges),
                input_tokens=sum(c.input_tokens for c in charges if c.metered),
                output_tokens=sum(c.output_tokens for c in charges if c.metered),
                attempts=sum(1 for a in attempts if a.dispatched),
                outcome=outcome,
                counts_as_request=succeeded,
                provider=last.provider,
                model=last.model,
                price_version=last.price_version,
                prompt_version=prompt_version,
                lesson_revision_id=lesson.revision_id,
                unmetered_attempts=sum(1 for c in charges if not c.metered),
                bound_violations=violations,
                charges=tuple(charges),
            ),
        )
        if settled != "settled" or violations:
            # Codes and counts only.
            logger.warning("tutor settlement result=%s bound_violations=%d", settled, violations)

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
            source=ResponseSource.FIXED_TEMPLATE,
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
