"""Provider factories."""

from __future__ import annotations

import logging

from meetingbot.config import Secrets, Settings
from meetingbot.providers.base import LLM
from meetingbot.providers.llm_common import LLMUnavailableError, ResilientLLM

logger = logging.getLogger(__name__)


def _make_llm(provider: str, settings: Settings, secrets: Secrets) -> LLM:
    cfg = settings.llm
    if provider == "gemini":
        from meetingbot.providers.llm_gemini import GeminiLLM

        if not secrets.gemini_api_key:
            raise LLMUnavailableError("GEMINI_API_KEY is not set.")
        return GeminiLLM(
            cfg.gemini_model, secrets.gemini_api_key, temperature=cfg.temperature
        )
    if provider == "ollama":
        from meetingbot.providers.llm_ollama import OllamaLLM

        return OllamaLLM(cfg.ollama_model, cfg.ollama_host, temperature=cfg.temperature)
    raise LLMUnavailableError(f"Unknown LLM provider '{provider}'.")


def build_llm(settings: Settings, secrets: Secrets) -> LLM:
    """Build the configured LLM, with fallback when the primary is unusable."""
    cfg = settings.llm
    candidates = [cfg.provider]
    if cfg.fallback_provider and cfg.fallback_provider != cfg.provider:
        candidates.append(cfg.fallback_provider)

    providers: list[tuple[str, LLM]] = []
    errors: list[str] = []
    for name in candidates:
        try:
            providers.append((name, _make_llm(name, settings, secrets)))
        except LLMUnavailableError as exc:
            errors.append(f"{name}: {exc}")
            logger.warning("LLM provider '%s' unavailable: %s", name, exc)

    if not providers:
        raise LLMUnavailableError(
            "No LLM provider is available. Set GEMINI_API_KEY in .env, or install and "
            "start Ollama for local mode.\n" + "\n".join(errors)
        )

    primary_name, primary = providers[0]
    fallback = providers[1][1] if len(providers) > 1 else None
    logger.info(
        "LLM primary=%s fallback=%s",
        primary_name,
        providers[1][0] if len(providers) > 1 else None,
    )
    return ResilientLLM(primary, fallback=fallback, max_retries=cfg.max_retries)
