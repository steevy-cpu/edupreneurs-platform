"""Adapter for OpenAI-compatible chat completion APIs (OpenRouter and similar).

NOT CONNECTED. No live call is authorised in Jude-01: the service factory
refuses to build this adapter unless the owner has explicitly authorised live
provider calls, and the test suite drives it only through an in-memory
``httpx.MockTransport``.

The adapter never logs request or response bodies, and its errors carry a
category only — a provider's error text can echo the prompt.
"""

from __future__ import annotations

from typing import Any

import httpx

from edu_api.tutor.providers.base import (
    ModelRequest,
    ModelResult,
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    TokenUsage,
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        name: str = "openrouter",
        path: str = "/chat/completions",
    ) -> None:
        """``client`` carries the base URL and the Authorization header.

        The caller owns the client (and its lifetime, timeouts and transport).
        """
        self.name = name
        self._client = client
        self._path = path

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
        try:
            response = await self._client.post(self._path, json=payload)
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.HTTPError:
            raise ProviderUnavailableError() from None

        status = response.status_code
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

        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
            usage = body["usage"]
            input_tokens = int(usage["prompt_tokens"])
            output_tokens = int(usage["completion_tokens"])
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderBadResponseError() from None
        if not isinstance(text, str) or input_tokens < 0 or output_tokens < 0:
            raise ProviderBadResponseError()
        return ModelResult(
            text=text,
            usage=TokenUsage(input_tokens, output_tokens),
            provider=self.name,
            model=request.model,
        )
