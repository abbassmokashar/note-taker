"""Glossary handling: bias recognition, then optionally fix obvious ASR errors.

The glossary is a user-editable list of names/terms. It is used two ways:
  1. As an ``initial_prompt`` hint to the transcriber.
  2. As an optional LLM "fix obvious ASR errors, add nothing" pass.
"""

from __future__ import annotations

import json
import logging

from meetingbot.prompts import render
from meetingbot.providers.base import LLM, TranscriptSegment
from meetingbot.providers.llm_common import LLMError, parse_json_list

logger = logging.getLogger(__name__)


def build_initial_prompt(base_prompt: str | None, glossary: list[str]) -> str | None:
    """Append glossary terms to the base prompt so Whisper favors them."""
    terms = [t.strip() for t in glossary if t and t.strip()]
    if not terms:
        return base_prompt
    hint = "Glossary (spell these correctly): " + ", ".join(terms) + "."
    if base_prompt:
        return f"{base_prompt} {hint}"
    return hint


def apply_glossary_correction(
    llm: LLM,
    segments: list[TranscriptSegment],
    glossary: list[str],
    *,
    language: str | None = None,
) -> list[TranscriptSegment]:
    """Optional LLM pass to fix obvious ASR spelling errors. No-op without a glossary."""
    terms = [t.strip() for t in glossary if t and t.strip()]
    if not terms or not segments:
        return segments

    payload = [
        {"id": seg.id, "text": seg.text} for seg in segments if seg.text.strip()
    ]
    if not payload:
        return segments

    system = render("fix_asr")
    user = (
        "Glossary: " + ", ".join(terms) + "\n\n"
        "Segments:\n" + json.dumps(payload, ensure_ascii=False)
    )
    try:
        response = llm.complete(system=system, user=user, json_mode=True)
        data = parse_json_list(response)
    except LLMError as exc:
        logger.warning("Glossary correction skipped: %s", exc)
        return segments

    by_id = {item.get("id"): item.get("text") for item in data if isinstance(item, dict)}
    corrected = 0
    for seg in segments:
        new_text = by_id.get(seg.id)
        if isinstance(new_text, str) and new_text.strip() and new_text != seg.text:
            seg.text = new_text.strip()
            corrected += 1
    logger.info("Glossary pass corrected %d segments.", corrected)
    return segments
