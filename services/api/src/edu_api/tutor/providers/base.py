"""The provider contract: what the tutor needs from any language model.

Nothing outside ``edu_api.tutor.providers`` knows which company or model is
behind a ``ModelProvider``. Errors are typed so the gateway can decide, without
string matching, whether to retry and whether money may have been spent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[ChatMessage, ...]
    model: str
    max_output_tokens: int
    temperature: float = 0.2
    json_output: bool = True


#: Largest token count accepted from a provider for one call. Far above any real
#: request here; a larger figure is treated as broken metering, not as a bill.
MAX_TOKEN_COUNT = 10_000_000


def parse_token_count(value: object) -> int:
    """A provider-reported token count, or ``ValueError``.

    Only a real, non-negative ``int`` is a count. ``True`` (which Python treats
    as 1), ``1.5``, ``"12"``, ``None`` and negative numbers are all refused:
    rounding or coercing a malformed figure would silently understate a charge.
    """
    if type(value) is not int or not 0 <= value <= MAX_TOKEN_COUNT:
        raise ValueError("not a valid token count")
    return value


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        parse_token_count(self.input_tokens)
        parse_token_count(self.output_tokens)


@dataclass(frozen=True)
class ModelResult:
    text: str
    usage: TokenUsage
    provider: str
    model: str


class ProviderError(Exception):
    """A provider call failed.

    ``retryable``      — another attempt may succeed.
    ``usage_unknown``  — the provider may have billed for this call even though
                         no usable result came back. The budget then charges
                         the attempt at its reserved worst case.
    """

    kind: str = "provider_error"
    retryable: bool = False
    usage_unknown: bool = False

    def __init__(self, kind_detail: str = "") -> None:
        # Deliberately no provider response body here: it may echo the prompt.
        super().__init__(kind_detail or self.kind)


class ProviderTimeoutError(ProviderError):
    kind = "timeout"
    retryable = True
    usage_unknown = True


class ProviderUnavailableError(ProviderError):
    kind = "unavailable"
    retryable = True
    usage_unknown = True


class ProviderRateLimitedError(ProviderError):
    """Rejected before any work was done; nothing was billed."""

    kind = "rate_limited"
    retryable = True


class ProviderAuthError(ProviderError):
    kind = "auth"


class ProviderRejectedError(ProviderError):
    """The provider refused the request as invalid; retrying the same request cannot help."""

    kind = "rejected"


class ProviderBadResponseError(ProviderError):
    """A response arrived but could not be read (no text, no usage figures)."""

    kind = "bad_response"
    retryable = True
    usage_unknown = True


class ProviderMeteringError(ProviderBadResponseError):
    """An answer arrived but its usage figures are missing or malformed.

    The call was served, so it is charged as unknown usage, and it is NOT
    retried: a provider whose metering cannot be read is not called again
    inside the same request.
    """

    kind = "bad_metering"
    retryable = False


class ProviderRedirectError(ProviderError):
    """The endpoint answered with a redirect. It is never followed and never a completion."""

    kind = "redirect"


class ProviderUnexpectedStatusError(ProviderError):
    """A status that is neither the one success status nor a known refusal.

    The provider may have done the work, so the cost is unknown.
    """

    kind = "unexpected_status"
    usage_unknown = True


class ProviderDestinationError(ProviderError):
    """The response did not come from the approved endpoint."""

    kind = "unexpected_destination"
    usage_unknown = True


class ModelProvider(Protocol):
    """``name`` and ``complete`` are required.

    A provider that can send data off this machine MUST also declare
    ``live_capable = True``; the wiring refuses such a provider unless the
    owner has authorised live calls (see ``is_live_capable``).
    """

    name: str

    async def complete(self, request: ModelRequest) -> ModelResult:
        """One completion. Raises ``ProviderError`` subclasses; honours task cancellation."""
        ...


def is_live_capable(provider: object) -> bool:
    """Whether ``provider`` declares that it can reach a real model endpoint.

    This is a declaration, not a proof: an object that opens connections
    without declaring it is not detected here. Wiring is trusted code and is
    reviewed; the tutor test suites also refuse every socket connection.
    """
    return bool(getattr(provider, "live_capable", False))
