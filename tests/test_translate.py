from __future__ import annotations

import json

from meetingbot.pipeline.translate import translate_transcript
from meetingbot.providers.base import TranscriptSegment


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(id=0, start_s=0, end_s=1, text="Hello", language="en"),
        TranscriptSegment(id=1, start_s=1, end_s=2, text="مرحبا", language="ar"),
        TranscriptSegment(id=2, start_s=2, end_s=3, text="How are you", language="en"),
    ]


def test_translate_fills_both_targets(mock_llm) -> None:
    segments = _segments()
    translate_transcript(mock_llm, segments)

    # English source segments are copied; Arabic source is translated to English.
    assert segments[0].text_en == "Hello"
    assert segments[1].text_en == "en:مرحبا"
    # English source segments are translated to Arabic; Arabic source copied.
    assert segments[0].text_ar == "ar:Hello"
    assert segments[1].text_ar == "مرحبا"
    assert len(segments) == 3


def test_context_is_sent_to_model(mock_llm) -> None:
    translate_transcript(mock_llm, _segments())
    assert any("Context (do not translate)" in user for _, user, _ in mock_llm.calls)


def test_malformed_output_falls_back_without_losing_segments() -> None:
    class BadLLM:
        def complete(self, *, system, user, json_mode=False):
            return "not json at all"

    segments = _segments()
    translate_transcript(BadLLM(), segments)
    # Every segment still has both targets, falling back to the original text.
    for seg in segments:
        assert seg.text_en
        assert seg.text_ar


def test_id_mismatch_falls_back() -> None:
    class MismatchedLLM:
        def complete(self, *, system, user, json_mode=False):
            return json.dumps([{"id": 999, "text": "wrong"}])

    segments = _segments()
    translate_transcript(MismatchedLLM(), segments)
    assert segments[0].text_ar == segments[0].text
