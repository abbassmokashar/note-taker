"""Translation stage: produce ``text_en`` and ``text_ar`` for every segment."""

from __future__ import annotations

import json
import logging

from meetingbot.prompts import render
from meetingbot.providers.base import LLM, TranscriptSegment
from meetingbot.providers.llm_common import LLMError, parse_json_list

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 40
VALIDATION_ATTEMPTS = 3


def _needs_translation(seg: TranscriptSegment, target: str) -> bool:
    return (seg.language or "").lower() != target


def _format_context(segments: list[TranscriptSegment]) -> str:
    lines = [f"  {i}: {s.text}" for i, s in enumerate(segments)]
    return "\n".join(lines)


def _format_batch(batch: list[TranscriptSegment]) -> str:
    payload = [{"id": seg.id, "text": seg.text} for seg in batch]
    return json.dumps(payload, ensure_ascii=False)


def _apply_response(
    batch: list[TranscriptSegment], response: str, attr: str
) -> None:
    data = parse_json_list(response)
    by_id = {}
    for item in data:
        if not isinstance(item, dict) or "id" not in item or "text" not in item:
            raise LLMError(f"Malformed translation item: {item!r}")
        by_id[item["id"]] = str(item["text"])

    expected_ids = [seg.id for seg in batch]
    if sorted(by_id) != sorted(expected_ids):
        raise LLMError(
            f"Translation id mismatch: expected {len(expected_ids)} ids, got {len(by_id)}."
        )
    for seg in batch:
        setattr(seg, attr, by_id[seg.id])


def _translate_batch(
    llm: LLM,
    batch: list[TranscriptSegment],
    target: str,
    context: list[TranscriptSegment],
) -> None:
    """Translate one batch, retrying on malformed output; never lose segments."""
    attr = "text_en" if target == "en" else "text_ar"
    system = render(f"translate_to_{target}")

    user_parts: list[str] = []
    if context:
        user_parts.append("Context (do not translate):\n" + _format_context(context))
    user_parts.append(f"Translate to {target}:\n" + _format_batch(batch))
    user = "\n\n".join(user_parts)

    last_error: Exception | None = None
    for attempt in range(VALIDATION_ATTEMPTS):
        try:
            response = llm.complete(system=system, user=user, json_mode=True)
            _apply_response(batch, response, attr)
            return
        except LLMError as exc:
            last_error = exc
            logger.warning("Translation attempt %d failed: %s", attempt + 1, exc)

    logger.error("Translation failed for batch; keeping original text. %s", last_error)
    for seg in batch:
        setattr(seg, attr, seg.text)


def translate_transcript(
    llm: LLM,
    segments: list[TranscriptSegment],
    *,
    targets: tuple[str, ...] = ("en", "ar"),
    batch_size: int = DEFAULT_BATCH_SIZE,
    context_segments: int = 3,
) -> list[TranscriptSegment]:
    """Fill in ``text_en`` / ``text_ar`` for every segment. Returns the same objects."""
    for target in targets:
        attr = "text_en" if target == "en" else "text_ar"
        for start, end in _pending_batches(segments, target, batch_size):
            batch = [seg for seg in segments[start:end] if _needs_translation(seg, target)]
            context = segments[max(0, start - context_segments) : start]
            _translate_batch(llm, batch, target, context)
        for seg in segments:
            if not _needs_translation(seg, target):
                setattr(seg, attr, seg.text)

    return segments


def _pending_batches(
    segments: list[TranscriptSegment], target: str, batch_size: int
) -> list[tuple[int, int]]:
    """Return (start, end) index ranges covering segments needing translation."""
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    count = 0
    for index, seg in enumerate(segments):
        if not _needs_translation(seg, target):
            if start is not None:
                ranges.append((start, index))
                start, count = None, 0
            continue
        if start is None:
            start, count = index, 0
        count += 1
        if count >= batch_size:
            ranges.append((start, index + 1))
            start, count = None, 0
    if start is not None:
        ranges.append((start, len(segments)))
    return ranges
