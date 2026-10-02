from __future__ import annotations

from meetingbot.pipeline.notes import (
    chunk_transcript,
    generate_notes,
    parse_notes_markdown,
    transcript_to_text,
)
from meetingbot.providers.base import TranscriptSegment


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            id=0, start_s=0, end_s=5, text="Hello", text_en="Hello", text_ar="مرحبا"
        ),
        TranscriptSegment(
            id=1, start_s=65, end_s=70, text="Bye", text_en="Bye", text_ar="إلى اللقاء"
        ),
    ]


def test_transcript_to_text_uses_lang_and_timestamps() -> None:
    text = transcript_to_text(_segments(), "ar")
    assert "[00:00] مرحبا" in text
    assert "[01:05] إلى اللقاء" in text


def test_chunk_transcript_splits_on_size() -> None:
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(20))
    chunks = chunk_transcript(text, chunk_chars=200)
    assert len(chunks) > 1
    assert all(len(c) <= 260 for c in chunks)  # allows one line of slack


def test_parse_notes_markdown() -> None:
    md = (
        "# Meeting\n\n"
        "## TL;DR\nShort summary line.\n\n"
        "## Key discussion points\n- point one\n- point two\n\n"
        "## Decisions\n- decided A [00:10]\n\n"
        "## Action items\n| Task | Owner | Due | [mm:ss] |\n"
        "| --- | --- | --- | --- |\n| Do it | Alice | Fri | [00:20] |\n\n"
        "## Open questions\n- why?\n"
    )
    parsed = parse_notes_markdown(md)
    assert parsed["summary"] == "Short summary line."
    assert parsed["key_points"] == ["point one", "point two"]
    assert parsed["decisions"] == ["decided A [00:10]"]
    assert parsed["open_questions"] == ["why?"]
    assert any("Do it" in row for row in parsed["action_items"])
    # separator rows are not action items
    assert not any("---" in row for row in parsed["action_items"])


def test_generate_notes_single_chunk(mock_llm) -> None:
    markdown = generate_notes(mock_llm, _segments(), "Meeting", lang="en")
    assert markdown.startswith("# Test Meeting")
    # Single pass: exactly one model call.
    assert len(mock_llm.calls) == 1


def test_generate_notes_map_reduce(mock_llm) -> None:
    segments = [
        TranscriptSegment(id=i, start_s=i, end_s=i + 1, text="word " * 30, language="en")
        for i in range(40)
    ]
    generate_notes(mock_llm, segments, "Long", lang="en", chunk_chars=500)
    # map over several chunks + one merge call
    assert len(mock_llm.calls) > 2


def test_generate_notes_empty_transcript(mock_llm) -> None:
    markdown = generate_notes(mock_llm, [], "Empty", lang="en")
    assert "not stated" in markdown
    assert mock_llm.calls == []
