"""Calling a model provider safely: timeout, bounded retries, explicit fallback, metering.

The gateway never decides to spend more than it was configured to:

* the number of calls is bounded (``max_calls``), so the service can reserve
  the worst case before the first call;
* a fallback route exists only when it was configured, and one that costs more
  than the primary is refused at wiring time unless explicitly allowed;
* every attempt, successful or not, is appended to a list the CALLER owns, so
  the cost of a request is known even when the task is cancelled mid-call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from edu_api.tutor.budget import ModelPrice
from edu_api.tutor.errors import TutorConfigurationError
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


@dataclass(frozen=True)
class Attempt:
    provider: str
    model: str
    price: ModelPrice
    #: ``ok``, ``output_rejected``, ``cancelled`` or a ``ProviderError.kind``.
    outcome: str
    usage: TokenUsage | None
    #: True when the provider may have billed but reported nothing.
    usage_unknown: bool
    detail: str = ""


@dataclass(frozen=True)
class GatewayResult[T]:
    value: T | None
    #: ``None`` on success, else the outcome of the last attempt.
    failure: str | None


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
    def max_calls(self) -> int:
        return self._retry.max_attempts + (1 if self._fallback is not None else 0)

    def worst_case_micro(self, *, input_tokens: int, max_output_tokens: int) -> int:
        """Most this gateway can spend on one request: every call, full input and output."""
        usage = TokenUsage(input_tokens, max_output_tokens)
        total = self._retry.max_attempts * self._primary.price.cost_micro(usage)
        if self._fallback is not None:
            total += self._fallback.price.cost_micro(usage)
        return total

    def attempt_worst_case_micro(
        self, attempt: Attempt, *, input_tokens: int, max_output_tokens: int
    ) -> int:
        return attempt.price.cost_micro(TokenUsage(input_tokens, max_output_tokens))

    async def run[T](
        self,
        build: Callable[[Route], ModelRequest],
        parse: Callable[[ModelResult], T],
        attempts: list[Attempt],
    ) -> GatewayResult[T]:
        """Try the primary route (with retries), then the fallback once if configured.

        ``parse`` turns a raw result into a validated value or raises
        ``OutputRejected``; a rejected output is retried like a failed call.
        Never raises for provider trouble. Cancellation propagates after the
        in-flight attempt has been recorded.
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
            outcome = await self._call(route, build, parse, attempts)
            if isinstance(outcome, _Success):
                return GatewayResult(outcome.value, None)
            failure = outcome.failure
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
    ) -> _Success[T] | _Failure:
        name = route.provider.name

        def record(outcome: str, usage: TokenUsage | None, unknown: bool, detail: str = "") -> None:
            attempts.append(
                Attempt(name, route.model, route.price, outcome, usage, unknown, detail)
            )

        try:
            async with asyncio.timeout(route.timeout_s):
                result = await route.provider.complete(build(route))
        except asyncio.CancelledError:
            record("cancelled", None, True)
            raise
        except TimeoutError:
            record(ProviderTimeoutError.kind, None, True)
            return _Failure(ProviderTimeoutError.kind, retryable=True)
        except ProviderError as exc:
            record(exc.kind, None, exc.usage_unknown)
            return _Failure(exc.kind, retryable=exc.retryable)
        except Exception:
            # An adapter bug. The call may have gone out, so treat the cost as unknown.
            # Nothing from the exception is recorded: its text could contain the prompt.
            record("provider_crashed", None, True)
            return _Failure("provider_crashed", retryable=False)
        try:
            value = parse(result)
        except OutputRejected as exc:
            record("output_rejected", result.usage, False, exc.reason)
            return _Failure("output_rejected", retryable=True)
        record("ok", result.usage, False)
        return _Success(value)


@dataclass(frozen=True)
class _Success[T]:
    value: T


@dataclass(frozen=True)
class _Failure:
    failure: str
    retryable: bool
