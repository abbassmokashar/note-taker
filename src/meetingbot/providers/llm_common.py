"""Shared LLM plumbing: errors, JSON parsing/repair, retry + fallback."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable

from meetingbot.providers.base import LLM

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Base class for LLM provider failures."""


class LLMRateLimitError(LLMError):
    """Provider signalled a rate limit / quota problem (retryable, then fall back)."""


class LLMUnavailableError(LLMError):
    """Provider is unreachable or not configured (falls back immediately)."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> str:
    """Best-effort extraction of a JSON value from a model response."""
    stripped = text.strip()
    fenced = _FENCE_RE.search(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    # Fall back to the outermost array or object.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end != -1 and end > start:
            return stripped[start : end + 1]
    return stripped


def parse_json_list(text: str) -> list[dict]:
    """Parse a model response into a list of objects, or raise LLMError."""
    candidate = extract_json(text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model returned invalid JSON: {exc}\n---\n{text[:500]}") from exc
    if isinstance(data, dict) and "segments" in data:
        data = data["segments"]
    if not isinstance(data, list):
        raise LLMError(f"Expected a JSON array, got {type(data).__name__}.")
    return data


class ResilientLLM:
    """Wraps a primary LLM with retry/backoff and an optional fallback provider."""

    def __init__(
        self,
        primary: LLM,
        *,
        fallback: LLM | None = None,
        max_retries: int = 5,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep

    def _call_with_retries(self, provider: LLM, **kwargs) -> str:
        delay = self.base_delay
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return provider.complete(**kwargs)
            except (LLMRateLimitError, LLMUnavailableError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                logger.warning(
                    "LLM call failed (%s); retrying in %.1fs (attempt %d/%d)",
                    exc, delay, attempt + 1, self.max_retries,
                )
                self._sleep(delay)
                delay = min(delay * 2, self.max_delay)
            except LLMError:
                raise
        assert last_error is not None
        raise last_error

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> str:
        try:
            return self._call_with_retries(
                self.primary, system=system, user=user, json_mode=json_mode
            )
        except LLMError as exc:
            if self.fallback is None:
                raise
            logger.warning("Primary LLM failed (%s); falling back to %s", exc, type(self.fallback).__name__)
            return self._call_with_retries(
                self.fallback, system=system, user=user, json_mode=json_mode
            )
