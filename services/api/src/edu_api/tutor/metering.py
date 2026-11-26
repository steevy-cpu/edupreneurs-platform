"""How many tokens the server ASSUMES one provider call can bill, before it is made.

THE CONTRACT
------------
The budget holds money before a call. For that hold to mean anything it must be
at least what the provider can charge. The server cannot run every provider's
tokenizer, so it uses a bound that does not depend on one:

    input tokens  <=  UTF-8 bytes of every message's content
                      + ``tokens_per_message`` for each message   (role markers)
                      + ``tokens_per_request``                    (start/end markers,
                                                                   reply priming,
                                                                   JSON-mode preamble)
    output tokens <=  the ``max_tokens`` sent with the request

"One token per byte" holds for tokenizers whose every token covers at least one
byte of the text (byte-level BPE, and SentencePiece with or without byte
fallback). The two framing allowances are CONFIGURATION, sized by the owner for
the models in use.

WHAT THIS IS NOT
----------------
It is an assumption about somebody else's meter, not a proof. A provider can
add text of its own, count differently, or bill above ``max_tokens``. The
server therefore also CHECKS every reported usage against the bound
(``AttemptBound.exceeded_by``): a call that reports more is recorded at its
real cost, flagged, and stops further dispatch. The only hard dollar ceiling
for a live provider is a limit enforced on the provider's side.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from edu_api.tutor.providers.base import ChatMessage, TokenUsage


@dataclass(frozen=True)
class InputBound:
    """Framing allowances added to the byte count of the message contents."""

    tokens_per_message: int = 16
    tokens_per_request: int = 64

    def __post_init__(self) -> None:
        if self.tokens_per_message < 0 or self.tokens_per_request < 0:
            raise ValueError("framing allowances cannot be negative")

    def tokens(self, messages: Sequence[ChatMessage]) -> int:
        """The assumed ceiling on billable input tokens for ``messages``."""
        return self.tokens_per_request + sum(
            self.tokens_per_message + len(message.content.encode("utf-8")) for message in messages
        )


@dataclass(frozen=True)
class AttemptBound:
    """The most one provider call is assumed to bill, in tokens."""

    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("a bound cannot be negative")

    def as_usage(self) -> TokenUsage:
        """The bound as a usage figure: what an unmetered call is charged."""
        return TokenUsage(self.input_tokens, self.output_tokens)

    def exceeded_by(self, usage: TokenUsage) -> bool:
        """True when a provider reported more than the server assumed possible."""
        return usage.input_tokens > self.input_tokens or usage.output_tokens > self.output_tokens
