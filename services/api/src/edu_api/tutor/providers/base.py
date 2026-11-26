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


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


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


class ModelProvider(Protocol):
    name: str

    async def complete(self, request: ModelRequest) -> ModelResult:
        """One completion. Raises ``ProviderError`` subclasses; honours task cancellation."""
        ...
