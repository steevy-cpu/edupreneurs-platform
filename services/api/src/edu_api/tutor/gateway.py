"""Calling a model provider safely: timeout, bounded retries, explicit fallback, metering.

The gateway never decides to spend more than it was configured to:

* the number of calls is bounded (``max_calls``), so the service can reserve
  the assumed worst case before the first call;
* a fallback route exists only when it was configured, and one that costs more
  than the primary is refused at wiring time unless explicitly allowed;
* EVERY call is authorised first (``authorize``): the kill switch and the state
  of the budget hold are re-checked before the first call, each retry and the
  fallback;
* a call that reports more usage than the hold assumed stops all further calls.

ONE CALL, FIVE SEPARATE STEPS
-----------------------------
Each step is written to an ``Attempt`` in a list the CALLER owns, as it happens:

    1. authorising   the attempt exists before anything is asked
    2. dispatched    permission given; from here the provider may bill
    3. completed     a response arrived; its usage figures are recorded
    4. validated     the caller's parser accepted or rejected the text
    5. (settlement is the caller's job, from the list)

So whatever fails or is cancelled afterwards — the parser crashing included —
the list still says that a call went out and what it reported. An attempt
that never got past step 1 or 2 counts as "the provider may have billed".
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from edu_api.tutor.budget import ModelPrice
from edu_api.tutor.errors import TutorConfigurationError, TutorError
from edu_api.tutor.metering import AttemptBound
from edu_api.tutor.providers.base import (
    ModelProvider,
    ModelRequest,
    ModelResult,
    ProviderError,
    ProviderTimeoutError,
    TokenUsage,
)


class OutputRejected(Exception):
    """Raised by a parser: the model answered, but the answer may not be used."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Route:
    """One provider + model + price + time limit."""

    provider: ModelProvider
    model: str
    price: ModelPrice
    timeout_s: float

    def __post_init__(self) -> None:
        if self.price.model != self.model:
            raise TutorConfigurationError(
                f"price {self.price.price_version!r} is for {self.price.model!r}, "
                f"not {self.model!r}"
            )
        if self.timeout_s <= 0:
            raise TutorConfigurationError("timeout_s must be positive")


@dataclass(frozen=True)
class RetryPolicy:
    #: Calls allowed on the primary route (first try included).
    max_attempts: int = 2
    base_delay_s: float = 0.25
    max_delay_s: float = 2.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 4:
            raise TutorConfigurationError("max_attempts must be between 1 and 4")

    def delay(self, attempt: int) -> float:
        """Wait before attempt number ``attempt`` (2 = first retry). No jitter: deterministic."""
        return float(min(self.base_delay_s * (2 ** max(attempt - 2, 0)), self.max_delay_s))


@dataclass
class Attempt:
    """One provider call, updated in place as it progresses (see the module docstring)."""

    provider: str
    model: str
    price: ModelPrice
    #: ``authorizing``, ``not_dispatched``, ``dispatched``, ``completed``, ``ok``,
    #: ``output_rejected``, ``validation_failed``, ``cancelled`` or a ``ProviderError.kind``.
    outcome: str = "authorizing"
    #: False only when permission was refused: no call was made for this attempt.
    dispatched: bool = True
    #: The provider's own figures, once a response has been read.
    usage: TokenUsage | None = None
    #: True while the provider may have billed without the server knowing how much.
    usage_unknown: bool = True
    #: The provider reported more than ``AttemptBound`` allows.
    over_bound: bool = False
    detail: str = ""

    @property
    def billable(self) -> bool:
        """The provider may have charged for this attempt."""
        return self.dispatched and (self.usage is not None or self.usage_unknown)

    @property
    def refused_by_provider(self) -> bool:
        """Dispatched, and turned away before any work (rate limit, auth, invalid request)."""
        return self.dispatched and not self.billable


@dataclass(frozen=True)
class GatewayResult[T]:
    value: T | None
    #: ``None`` on success, else the outcome of the last attempt.
    failure: str | None


#: Asks the budget for permission to make one more provider call. Raises a
#: ``TutorError`` (paused, hold lost) to refuse.
Authorizer = Callable[[], Awaitable[None]]


class ModelGateway:
    def __init__(
        self,
        primary: Route,
        *,
        retry: RetryPolicy | None = None,
        fallback: Route | None = None,
        allow_costlier_fallback: bool = False,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if fallback is not None and not allow_costlier_fallback:
            costlier = (
                fallback.price.input_micro_per_mtok > primary.price.input_micro_per_mtok
                or fallback.price.output_micro_per_mtok > primary.price.output_micro_per_mtok
            )
            if costlier:
                raise TutorConfigurationError(
                    "the fallback model costs more than the primary; refusing to switch to "
                    "it silently. Set allow_costlier_fallback explicitly if this is intended."
                )
        self._primary = primary
        self._fallback = fallback
        self._retry = retry or RetryPolicy()
        self._sleep = sleep

    @property
    def primary(self) -> Route:
        return self._primary

    @property
    def routes(self) -> tuple[Route, ...]:
        return (self._primary,) if self._fallback is None else (self._primary, self._fallback)

    @property
    def max_calls(self) -> int:
        return self._retry.max_attempts + (1 if self._fallback is not None else 0)

    def worst_case_micro(self, bound: AttemptBound) -> int:
        """The hold for one request: every permitted call, each at the full bound.

        Every primary attempt at the primary's price plus the fallback call at
        the fallback's own price, whichever is dearer.
        """
        usage = bound.as_usage()
        total = self._retry.max_attempts * self._primary.price.cost_micro(usage)
        if self._fallback is not None:
            total += self._fallback.price.cost_micro(usage)
        return total

    async def run[T](
        self,
        build: Callable[[Route], ModelRequest],
        parse: Callable[[ModelResult], T],
        attempts: list[Attempt],
        *,
        authorize: Authorizer,
        bound: AttemptBound,
    ) -> GatewayResult[T]:
        """Try the primary route (with retries), then the fallback once if configured.

        ``parse`` turns a raw result into a validated value or raises
        ``OutputRejected``; a rejected output is retried like a failed call.
        Provider trouble is returned, not raised. A refusal by ``authorize``
        (a ``TutorError``) and task cancellation propagate, after the attempt
        has been recorded.
        """
        failure = "no_attempt"
        plan: list[Route] = [self._primary] * self._retry.max_attempts
        if self._fallback is not None:
            plan.append(self._fallback)
        primary_exhausted = False
        for number, route in enumerate(plan, start=1):
            on_primary = route is self._primary
            if on_primary and primary_exhausted:
                continue
            if on_primary and number > 1:
                await self._sleep(self._retry.delay(number))
            outcome = await self._call(route, build, parse, attempts, authorize, bound)
            if isinstance(outcome, _Success):
                return GatewayResult(outcome.value, None)
            failure = outcome.failure
            if outcome.stop:
                break
            if on_primary and not outcome.retryable:
                # Retrying the same route cannot help; a configured fallback still may.
                primary_exhausted = True
        return GatewayResult(None, failure)

    async def _call[T](
        self,
        route: Route,
        build: Callable[[Route], ModelRequest],
        parse: Callable[[ModelResult], T],
        attempts: list[Attempt],
        authorize: Authorizer,
        bound: AttemptBound,
    ) -> _Success[T] | _Failure:
        # 1. The attempt is on record before anything is asked. If this task dies
        #    from here on, the caller sees an attempt the provider may have billed.
        attempt = Attempt(route.provider.name, route.model, route.price)
        attempts.append(attempt)
        try:
            await authorize()
        except asyncio.CancelledError:
            # Permission may have been granted and counted; no call was made, but
            # the two cannot be told apart from here. Left as "may have billed".
            raise
        except TutorError:
            # A definite refusal (paused, hold no longer active): nothing was sent.
            attempt.outcome, attempt.dispatched, attempt.usage_unknown = (
                "not_dispatched",
                False,
                False,
            )
            raise
        except Exception:
            # The budget could not be asked. Nothing was sent; whether a dispatch
            # was counted is unknown, and the caller's release will find out.
            attempt.outcome, attempt.dispatched, attempt.usage_unknown = (
                "not_dispatched",
                False,
                False,
            )
            raise TutorError("dispatch could not be authorised") from None

        # 2. Dispatched.
        attempt.outcome = "dispatched"
        try:
            async with asyncio.timeout(route.timeout_s):
                result = await route.provider.complete(build(route))
        except asyncio.CancelledError:
            attempt.outcome = "cancelled"
            raise
        except TimeoutError:
            attempt.outcome = ProviderTimeoutError.kind
            return _Failure(ProviderTimeoutError.kind, retryable=True)
        except ProviderError as exc:
            attempt.outcome, attempt.usage_unknown = exc.kind, exc.usage_unknown
            return _Failure(exc.kind, retryable=exc.retryable)
        except Exception:
            # An adapter bug. The call may have gone out, so the cost stays unknown.
            # Nothing from the exception is recorded: its text could contain the prompt.
            attempt.outcome = "provider_crashed"
            return _Failure("provider_crashed", retryable=False)

        # 3. Completed: the usage is on record BEFORE the text is looked at.
        attempt.outcome, attempt.usage, attempt.usage_unknown = "completed", result.usage, False
        attempt.over_bound = bound.exceeded_by(result.usage)

        # 4. Validated.
        try:
            value = parse(result)
        except OutputRejected as exc:
            attempt.outcome, attempt.detail = "output_rejected", exc.reason
            return _Failure("output_rejected", retryable=True, stop=attempt.over_bound)
        except Exception:
            # The server's own check failed. Calling the provider again would not
            # repair it, and the completed call stays chargeable. The exception is
            # dropped: its text could quote the model's answer.
            attempt.outcome = "validation_failed"
            return _Failure("validation_failed", retryable=False, stop=True)
        attempt.outcome = "ok"
        return _Success(value)


@dataclass(frozen=True)
class _Success[T]:
    value: T


@dataclass(frozen=True)
class _Failure:
    failure: str
    retryable: bool
    #: No further call on ANY route (local fault, or usage above the bound).
    stop: bool = False
