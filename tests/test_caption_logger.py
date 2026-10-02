from __future__ import annotations

from pathlib import Path

from meetingbot.bot.caption_logger import (
    append_jsonl,
    normalize_events,
    read_events,
)


def test_normalize_filters_invalid() -> None:
    raw = [
        {"t_wall": 1.0, "speaker_name": "Alice", "caption_text": "Hello"},
        {"t_wall": "bad", "speaker_name": "Bob", "caption_text": "Hi"},
        {"t_wall": 2.0, "speaker_name": "Carol", "caption_text": "   "},
        "not a dict",
        {"t_wall": 3.5, "speaker_name": "", "caption_text": "مرحبا"},
    ]
    events = normalize_events(raw)
    assert len(events) == 2
    assert events[0]["speaker_name"] == "Alice"
    assert events[1]["speaker_name"] == "Unknown"
    assert events[1]["caption_text"] == "مرحبا"


def test_normalize_non_list_returns_empty() -> None:
    assert normalize_events(None) == []
    assert normalize_events({"a": 1}) == []


def test_append_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    events = [
        {"t_wall": 1.0, "speaker_name": "Alice", "caption_text": "Hello"},
        {"t_wall": 2.0, "speaker_name": "Bob", "caption_text": "مرحبا"},
    ]
    written = append_jsonl(path, events)
    assert written == 2
    assert append_jsonl(path, []) == 0
    loaded = read_events(path)
    assert len(loaded) == 2
    assert loaded[1]["caption_text"] == "مرحبا"


def test_read_missing_file(tmp_path: Path) -> None:
    assert read_events(tmp_path / "nope.jsonl") == []
