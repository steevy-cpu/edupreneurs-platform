"""Stable, typed failures of the Jude tutor.

Every failure a caller can see has a ``code`` the mobile app can switch on and
an HTTP status the (not yet registered) router maps it to. Messages are fixed
developer-facing strings: they never contain a student's text, a model's
output, a provider's error body or a secret.
"""

from __future__ import annotations

from typing import ClassVar


class TutorError(Exception):
    """Base class. Jude failures stay inside this hierarchy (its failure boundary)."""

    code: ClassVar[str] = "tutor_unavailable"
    http_status: ClassVar[int] = 503
    message: ClassVar[str] = "Jude is unavailable right now. Lessons and practice still work."
    #: Seconds a client should wait before retrying, when retrying can help.
    retry_after_s: ClassVar[int | None] = None

    def __init__(self, detail: str | None = None) -> None:
        # ``detail`` is for server-side logs and tests only; it is never sent to a client.
        super().__init__(detail or self.message)
        self.detail = detail


class TutorDisabled(TutorError):
    code = "tutor_disabled"
    message = "Jude is not enabled."


class TutorPaused(TutorError):
    """The kill switch is on: no provider call may start."""

    code = "tutor_paused"
    message = "Jude is paused. Lessons and practice still work."
    retry_after_s = 300


class ConsentRequired(TutorError):
    """Consent is denied OR unknown. Unknown is never treated as granted."""

    code = "tutor_consent_required"
    http_status = 403
    message = "Jude needs recorded consent before it can be used."


class NotEntitled(TutorError):
    code = "tutor_not_entitled"
    http_status = 403
    message = "This account may not use Jude."


class LessonUnavailable(TutorError):
    """Unknown, draft, rejected, withdrawn or not visible to this learner: one answer for all."""

    code = "tutor_lesson_unavailable"
    http_status = 404
    message = "No published lesson with this id and locale."


class LessonRevisionNotCurrent(TutorError):
    code = "tutor_lesson_revision_not_current"
    http_status = 409
    message = "This lesson has a newer published revision. Refresh the lesson and ask again."


class InvalidTutorRequest(TutorError):
    code = "tutor_invalid_request"
    http_status = 422
    message = "The request does not match this lesson."


class LearnerDailyLimitReached(TutorError):
    code = "tutor_daily_limit_reached"
    http_status = 429
    message = "Today's Jude allowance is used up. It resets tomorrow."


class LearnerMonthlyLimitReached(TutorError):
    code = "tutor_monthly_limit_reached"
    http_status = 429
    message = "This month's Jude allowance is used up."


class GlobalBudgetExhausted(TutorError):
    code = "tutor_budget_exhausted"
    message = "Jude has reached its spending ceiling for this period."
    retry_after_s = 3600


class TooManyConcurrentRequests(TutorError):
    code = "tutor_too_many_requests"
    http_status = 429
    message = "Wait for the previous answer before asking again."
    retry_after_s = 5


class TutorBusy(TutorError):
    code = "tutor_busy"
    message = "Jude is busy. Try again in a moment."
    retry_after_s = 10


class DuplicateRequest(TutorError):
    """This idempotency key was already answered and accounted for once."""

    code = "tutor_duplicate_request"
    http_status = 409
    message = "This request was already answered. It was not charged again."


class RequestInProgress(TutorError):
    code = "tutor_request_in_progress"
    http_status = 409
    message = "This request is still being answered."
    retry_after_s = 5


class ProviderTimeout(TutorError):
    code = "tutor_provider_timeout"
    http_status = 504
    message = "Jude took too long to answer. Try again."
    retry_after_s = 10


class ProviderUnavailable(TutorError):
    code = "tutor_provider_unavailable"
    message = "Jude cannot answer right now. Try again later."
    retry_after_s = 30


class InvalidModelOutput(TutorError):
    code = "tutor_invalid_model_output"
    http_status = 502
    message = "Jude could not produce a reliable answer. Try again."


class ReservationLost(TutorError):
    """The budget hold of this request is no longer active (expired or erased).

    No further provider call may start for it. Reported to the client as the
    generic "unavailable": it is an internal condition, not a new API code.
    """


class TutorConfigurationError(Exception):
    """Raised while WIRING the tutor (never per request): the configuration is unsafe."""


#: Every code a client may receive, for the contract file and the API proposal.
ALL_ERRORS: tuple[type[TutorError], ...] = (
    TutorError,
    TutorDisabled,
    TutorPaused,
    ConsentRequired,
    NotEntitled,
    LessonUnavailable,
    LessonRevisionNotCurrent,
    InvalidTutorRequest,
    LearnerDailyLimitReached,
    LearnerMonthlyLimitReached,
    GlobalBudgetExhausted,
    TooManyConcurrentRequests,
    TutorBusy,
    DuplicateRequest,
    RequestInProgress,
    ProviderTimeout,
    ProviderUnavailable,
    InvalidModelOutput,
)
