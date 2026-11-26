"""Who may use Jude, and the privacy duties around it — as explicit interfaces.

Consent policy, entitlements and account lifecycle are owner decisions that are
not settled (PO-11) and whose backend lives in unmerged work (#5 account
lifecycle, #10 entitlements). Until they exist, the defaults here DENY:
unknown consent is not consent, and an unknown entitlement is no entitlement.
The tutor is therefore unusable in production wiring until someone deliberately
plugs in real implementations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ConsentState(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    #: No record, a failed lookup, or a policy version that is no longer current.
    UNKNOWN = "unknown"


class ConsentGate(Protocol):
    async def tutor_consent(self, learner_id: uuid.UUID) -> ConsentState:
        """Whether sending this learner's text to an AI provider is consented to.

        Must return ``UNKNOWN`` rather than guess: for a minor the answer
        depends on a guardian or school record that only the privacy module knows.
        """
        ...


class EntitlementGate(Protocol):
    async def may_use_tutor(self, learner_id: uuid.UUID) -> bool: ...


class DenyByDefaultConsent:
    """Production default until the consent module exists: nobody has consented."""

    async def tutor_consent(self, learner_id: uuid.UUID) -> ConsentState:
        return ConsentState.UNKNOWN


class DenyByDefaultEntitlements:
    """Production default until entitlements (#10) are merged: nobody is entitled."""

    async def may_use_tutor(self, learner_id: uuid.UUID) -> bool:
        return False


@dataclass
class StaticConsent:
    """Test double: an explicit table of consent states."""

    states: dict[uuid.UUID, ConsentState] = field(default_factory=dict)

    async def tutor_consent(self, learner_id: uuid.UUID) -> ConsentState:
        return self.states.get(learner_id, ConsentState.UNKNOWN)


@dataclass
class StaticEntitlements:
    """Test double: an explicit set of entitled learners."""

    entitled: set[uuid.UUID] = field(default_factory=set)

    async def may_use_tutor(self, learner_id: uuid.UUID) -> bool:
        return learner_id in self.entitled


class LearnerDataEraser(Protocol):
    """Called by the account-erasure orchestrator (Platform-00 §privacy) for each module."""

    async def erase_learner(self, learner_id: uuid.UUID, *, actor: str) -> int:
        """Remove every tutor record that names the learner. Returns rows removed."""
        ...


class UsageRetention(Protocol):
    """Called by a scheduled job with the cutoff the owner's retention rule gives."""

    async def purge_older_than(self, cutoff: datetime, *, actor: str) -> int: ...


class PrivilegedOperations(Protocol):
    """Operations only staff may perform. Every implementation must audit each call."""

    async def set_paused(self, paused: bool, *, actor: str) -> None: ...
