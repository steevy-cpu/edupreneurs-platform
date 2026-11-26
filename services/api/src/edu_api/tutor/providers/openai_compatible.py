"""Adapter for OpenAI-compatible chat completion APIs (OpenRouter and similar).

NOT CONNECTED. No live call is authorised: the service factory refuses to build
or accept this adapter unless the owner has explicitly authorised live provider
calls, and the test suite drives it only through an in-memory
``httpx.MockTransport``.

DESTINATION
-----------
The adapter is bound to ONE https origin, taken from the client's ``base_url``
when it is constructed. Every request goes to that origin, redirects are never
followed, and a response that did not come from it is refused. Only status 200
is a completion.

METERING
--------
Usage figures must be real non-negative integers. Anything else (a boolean, a
fraction, a string, a missing field) is ``ProviderMeteringError``: the call is
charged as unknown usage instead of being rounded into a smaller bill.

The adapter never logs request or response bodies, and its errors carry a
category only — a provider's error text can echo the prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from edu_api.tutor.errors import TutorConfigurationError
from edu_api.tutor.providers.base import (
    ModelRequest,
    ModelResult,
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderDestinationError,
    ProviderMeteringError,
    ProviderRateLimitedError,
    ProviderRedirectError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderUnexpectedStatusError,
    TokenUsage,
    parse_token_count,
)

_RESERVED_BODY_FIELDS = frozenset({"model", "messages", "max_tokens", "stream"})


def https_origin(url: httpx.URL | str) -> tuple[str, int]:
    """(host, port) of an absolute https URL, or ``TutorConfigurationError``."""
    parsed = httpx.URL(str(url))
    if parsed.scheme != "https" or not parsed.host:
        raise TutorConfigurationError("a model endpoint must be an absolute https URL")
    if parsed.userinfo:
        raise TutorConfigurationError("a model endpoint URL must not carry credentials")
    return parsed.host.lower(), parsed.port or 443


class OpenAICompatibleProvider:
    #: This adapter sends data to a real endpoint. See ``providers.base.is_live_capable``.
    live_capable = True

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        name: str = "openrouter",
        path: str = "/chat/completions",
        extra_body: Mapping[str, Any] | None = None,
    ) -> None:
        """``client`` carries the base URL (the approved endpoint) and the Authorization header.

        The caller owns the client (its lifetime, timeouts and transport). The
        base URL must be absolute https and the client must not follow redirects.
        ``extra_body`` adds fixed provider-specific fields to every request; it
        may not replace the fields the tutor controls.
        """
        self._origin = https_origin(client.base_url)
        if client.follow_redirects:
            raise TutorConfigurationError("the model client must not follow redirects")
        if not path.startswith("/") or "://" in path:
            raise TutorConfigurationError("the completion path must be a path on the endpoint")
        if extra_body and _RESERVED_BODY_FIELDS & set(extra_body):
            raise ValueError("extra_body may not set model, messages, max_tokens or stream")
        self.name = name
        self._client = client
        self._url = client.base_url.join(client.base_url.path.rstrip("/") + path)
        if https_origin(self._url) != self._origin:
            raise TutorConfigurationError("the completion path leaves the approved endpoint")
        self._extra_body = dict(extra_body or {})

    @property
    def origin(self) -> tuple[str, int]:
        return self._origin

    async def complete(self, request: ModelRequest) -> ModelResult:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": False,
        }
        if request.json_output:
            payload["response_format"] = {"type": "json_object"}
        payload.update(self._extra_body)
        try:
            response = await self._client.post(self._url, json=payload, follow_redirects=False)
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.HTTPError:
            raise ProviderUnavailableError() from None

        status = response.status_code
        if response.history or _origin_or_none(response.url) != self._origin:
            raise ProviderDestinationError()
        if 300 <= status < 400:
            raise ProviderRedirectError()
        if status in (401, 403):
            raise ProviderAuthError()
        if status == 429:
            raise ProviderRateLimitedError()
        if status in (408, 504):
            raise ProviderTimeoutError()
        if status >= 500:
            raise ProviderUnavailableError()
        if status >= 400:
            raise ProviderRejectedError()
        if status != 200:
            raise ProviderUnexpectedStatusError()

        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderBadResponseError() from None
        if not isinstance(text, str):
            raise ProviderBadResponseError()
        try:
            usage = body["usage"]
            metered = TokenUsage(
                parse_token_count(usage["prompt_tokens"]),
                parse_token_count(usage["completion_tokens"]),
            )
        except (ValueError, KeyError, TypeError):
            raise ProviderMeteringError() from None
        return ModelResult(text=text, usage=metered, provider=self.name, model=request.model)


def _origin_or_none(url: httpx.URL) -> tuple[str, int] | None:
    try:
        return https_origin(url)
    except TutorConfigurationError:
        return None
