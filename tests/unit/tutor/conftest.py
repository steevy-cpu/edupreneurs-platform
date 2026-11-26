"""Shared pieces for the Jude tutor tests.

Everything is in memory: synthetic lessons, a deterministic mock model, an
in-memory usage ledger, a fake clock. Any attempt to open a network connection
fails the test that made it.
"""

from __future__ import annotations

import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from edu_api.tutor import demo_content
from edu_api.tutor.budget import InMemoryUsageStore
from edu_api.tutor.config import TutorSettings
from edu_api.tutor.content import InMemoryLessonSource
from edu_api.tutor.factory import build_tutor_service
from edu_api.tutor.governance import ConsentState, StaticConsent, StaticEntitlements
from edu_api.tutor.providers.base import ModelProvider
from edu_api.tutor.providers.mock import Behaviour
from edu_api.tutor.service import TutorService
from edu_api.tutor.types import TutorRequest
from tests.unit.tutor.spies import RecordingMockProvider

LEARNER_A = uuid.UUID("d0000000-0000-4000-8000-00000000000a")
LEARNER_B = uuid.UUID("d0000000-0000-4000-8000-00000000000b")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this folder may reach a network, least of all an AI provider."""

    def refuse(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"a tutor test tried to open a network connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


class FakeClock:
    def __init__(self) -> None:
        # Noon in Port-au-Prince, mid-month: far from any day or month boundary.
        self.now = datetime(2026, 11, 15, 17, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


async def no_sleep(_: float) -> None:
    return None


@dataclass
class Harness:
    service: TutorService
    #: An explicitly injected recording spy; the factory's own mock records nothing.
    provider: RecordingMockProvider
    usage: InMemoryUsageStore
    lessons: InMemoryLessonSource
    consent: StaticConsent
    entitlements: StaticEntitlements
    settings: TutorSettings
    clock: FakeClock


def make_settings(**overrides: Any) -> TutorSettings:
    values: dict[str, Any] = {"enabled": True}
    values.update(overrides)
    return TutorSettings(_env_file=None, **values)


def build_harness(
    *,
    script: tuple[Behaviour, ...] = (),
    default: Behaviour = "ok",
    provider: ModelProvider | None = None,
    fallback_provider: ModelProvider | None = None,
    learners: tuple[uuid.UUID, ...] = (LEARNER_A, LEARNER_B),
    **settings_overrides: Any,
) -> Harness:
    settings = make_settings(**settings_overrides)
    clock = FakeClock()
    lessons = InMemoryLessonSource()
    lessons.add(demo_content.equations_fr())
    lessons.add(demo_content.equations_ht())
    lessons.add(demo_content.photosynthesis_fr())
    usage = InMemoryUsageStore(settings.budget_policy(), clock=clock)
    consent = StaticConsent({learner: ConsentState.GRANTED for learner in learners})
    entitlements = StaticEntitlements(set(learners))
    mock = RecordingMockProvider(script=script, default=default)
    service = build_tutor_service(
        settings,
        lessons=lessons,
        usage=usage,
        consent=consent,
        entitlements=entitlements,
        provider=provider or mock,
        fallback_provider=fallback_provider,
        retry_sleep=no_sleep,
    )
    return Harness(service, mock, usage, lessons, consent, entitlements, settings, clock)


def ask(**fields: Any) -> TutorRequest:
    """A valid request about the French equations lesson, with overrides."""
    values: dict[str, Any] = {
        "idempotency_key": uuid.uuid4(),
        "lesson_id": demo_content.EQUATIONS_LESSON_ID,
        "locale": "fr",
        "intent": "ask_question",
        "message": "Pourquoi on soustrait 5 des deux côtés ?",
    }
    values.update(fields)
    return TutorRequest.model_validate(values)


@pytest.fixture
def harness() -> Harness:
    return build_harness()
