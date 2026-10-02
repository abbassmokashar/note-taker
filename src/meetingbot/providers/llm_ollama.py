"""Ollama LLM provider (fully local fallback / private mode)."""

from __future__ import annotations

import logging

from meetingbot.providers.llm_common import (
    LLMError,
    LLMRateLimitError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)


class OllamaLLM:
    """Calls a local Ollama server via the ``ollama`` Python client."""

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        *,
        temperature: float = 0.2,
    ) -> None:
        self.model = model
        self.host = host
        self.temperature = temperature
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import ollama
        except ImportError as exc:  # pragma: no cover - depends on env
            raise LLMUnavailableError(
                "the ollama package is not installed. Install it with: "
                "pip install 'meetingbot[llm]' and run `ollama serve`."
            ) from exc
        self._client = ollama.Client(host=self.host)
        return self._client

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> str:
        client = self._ensure_client()
        try:
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                options={"temperature": self.temperature},
                format="json" if json_mode else None,
            )
        except Exception as exc:  # noqa: BLE001 - client raises many types
            text = str(exc).lower()
            if "429" in text or "rate limit" in text:
                raise LLMRateLimitError(str(exc)) from exc
            raise LLMUnavailableError(str(exc)) from exc

        content = _extract_content(response)
        if not content:
            raise LLMError("Ollama returned an empty response.")
        return content


def _extract_content(response) -> str:
    """Handle both dict and object responses across ollama client versions."""
    if isinstance(response, dict):
        message = response.get("message") or {}
        return message.get("content", "") if isinstance(message, dict) else ""
    message = getattr(response, "message", None)
    if message is None:
        return ""
    return getattr(message, "content", "") or ""
