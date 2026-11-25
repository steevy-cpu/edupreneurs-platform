"""Request/response models for the ``account`` routes.

The learner's identity is NEVER part of these models: it comes from the
verified access token only.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic.json_schema import SkipJsonSchema

DISPLAY_NAME_MAX_CHARS = 80
#: Longest raw value we are willing to normalise (the body-size middleware
#: already bounds the request; this bounds the work done per field).
_DISPLAY_NAME_MAX_RAW_CHARS = 400
#: Cc = control characters (includes tab, CR, LF, NEL), Zl / Zp = line and
#: paragraph separators, Cs = lone surrogates (not encodable as UTF-8).
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Zl", "Zp", "Cs"})

OnboardingState = Literal["new", "profile_selected", "downloads_informed", "ready"]


def normalise_display_name(value: str) -> str:
    """Trim and NFC-normalise a display name, or raise ``ValueError``.

    The error messages never contain the submitted value.
    """
    if len(value) > _DISPLAY_NAME_MAX_RAW_CHARS:
        raise ValueError(f"display_name must be at most {DISPLAY_NAME_MAX_CHARS} characters")
    name = unicodedata.normalize("NFC", value).strip()
    if not name:
        raise ValueError("display_name must not be empty; send null to clear it")
    if len(name) > DISPLAY_NAME_MAX_CHARS:
        raise ValueError(f"display_name must be at most {DISPLAY_NAME_MAX_CHARS} characters")
    if any(unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in name):
        raise ValueError("display_name must not contain control characters or line breaks")
    return name


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfilePatch(_Strict):
    """Fields of the caller's own profile to change. Omitted fields are kept."""

    # `None` only means "not sent": an explicit JSON null is rejected below, and
    # the null branch is kept out of the published schema.
    grade_code: (
        Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2,8}$")] | SkipJsonSchema[None]
    ) = Field(
        default=None,
        description="Code of an existing, active grade (for example `9AF`).",
        examples=["9AF"],
    )
    preferred_locale: Literal["fr", "ht"] | SkipJsonSchema[None] = Field(
        default=None, description="`fr` (French) or `ht` (Haitian Creole)."
    )
    display_name: str | None = Field(
        default=None,
        description="Private study name shown only to the learner: 1-80 characters after "
        "trimming, no control characters or line breaks. `null` clears it. "
        "It is never a public name.",
    )

    @field_validator("grade_code", "preferred_locale", mode="before")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must not be null; omit the field to keep the current value")
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, value: str | None) -> str | None:
        return None if value is None else normalise_display_name(value)

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return {name: getattr(self, name) for name in sorted(self.model_fields_set)}


class OnboardingUpdate(_Strict):
    """Progress to record. Everything merges monotonically on the server."""

    state: OnboardingState | None = Field(
        default=None,
        description="The furthest step this device has reached. A value behind the stored "
        "state is accepted and ignored. Omit to report only tour fields.",
    )
    onboarding_version: int = Field(
        ge=1, le=10000, description="Version of the onboarding flow built into this app."
    )
    tour_version_seen: int | None = Field(
        default=None, ge=0, le=10000, description="Highest product-tour version shown."
    )
    tour_dismissed: bool | None = Field(
        default=None, description="`true` once the learner asked not to see the tour again."
    )


class OnboardingResponse(BaseModel):
    """Not a consent record: nothing here means the learner agreed to anything."""

    state: OnboardingState
    onboarding_version: int = Field(description="0 until any device has reported.")
    tour_version_seen: int
    tour_dismissed: bool
    completed_at: datetime | None
    updated_at: datetime | None
