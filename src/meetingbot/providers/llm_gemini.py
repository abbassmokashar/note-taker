"""Gemini LLM provider (Google AI Studio free tier) via the google-genai SDK."""

from __future__ import annotations

import logging

from meetingbot.providers.llm_common import (
    LLMError,
    LLMRateLimitError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_MARKERS = ("429", "quota", "rate limit", "resource_exhausted", "rate_limit")


def _classify(exc: Exception) -> LLMError:
    text = str(exc).lower()
    if any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return LLMRateLimitError(str(exc))
    return LLMUnavailableError(str(exc))


class GeminiLLM:
    """Calls ``gemini-*`` models through the official google-genai client."""

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        temperature: float = 0.2,
    ) -> None:
        if not api_key:
            raise LLMUnavailableError(
                "GEMINI_API_KEY is not set. Add it to .env or switch llm.provider to ollama."
            )
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on env
            raise LLMUnavailableError(
                "google-genai is not installed. Install it with: pip install 'meetingbot[llm]'"
            ) from exc
        self._client = genai.Client(api_key=self.api_key)
        return self._client

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> str:
        client = self._ensure_client()
        try:
            from google.genai import types
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailableError("google-genai SDK is incomplete.") from exc

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            response_mime_type="application/json" if json_mode else None,
        )
        try:
            response = client.models.generate_content(
                model=self.model, contents=user, config=config
            )
        except Exception as exc:  # noqa: BLE001 - SDK raises many types
            raise _classify(exc) from exc

        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini returned an empty response.")
        return text
