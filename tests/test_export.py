from __future__ import annotations

import json
from pathlib import Path

from meetingbot.pipeline.export import (
    TranscriptMeta,
    export_transcript,
    format_timestamp_short,
    format_timestamp_srt,
    format_timestamp_vtt,
    segments_to_markdown,
    segments_to_srt,
    segments_to_vtt,
)
from meetingbot.providers.base import TranscriptSegment


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(id=0, start_s=0.0, end_s=2.5, text="Hello there", speaker="Alice"),
        TranscriptSegment(id=1, start_s=2.5, end_s=6.0, text="مرحبا", speaker="Bob"),
        TranscriptSegment(id=2, start_s=3661.5, end_s=3662.0, text="Bye"),
    ]


def test_timestamp_formats() -> None:
    assert format_timestamp_srt(0) == "00:00:00,000"
    assert format_timestamp_srt(3661.5) == "01:01:01,500"
    assert format_timestamp_vtt(3661.5) == "01:01:01.500"
    assert format_timestamp_short(3661) == "01:01:01"
    assert format_timestamp_short(65) == "01:05"


def test_srt_contents() -> None:
    srt = segments_to_srt(_segments())
    assert "1\n00:00:00,000 --> 00:00:02,500" in srt
    assert "Alice: Hello there" in srt
    assert "مرحبا" in srt


def test_vtt_contents() -> None:
    vtt = segments_to_vtt(_segments())
    assert vtt.startswith("WEBVTT")
    assert "<v Alice>Hello there" in vtt
    assert "-->" in vtt


def test_markdown_contents() -> None:
    md = segments_to_markdown(_segments(), "Weekly Sync", lang_label="en")
    assert md.startswith("# Weekly Sync")
    assert "[00:00] **Alice:** Hello there" in md


def test_export_writes_all_formats(tmp_path: Path) -> None:
    meta = TranscriptMeta(meeting_id="m1", title="T", language="en", duration_s=3662.0)
    written = export_transcript(_segments(), meta, tmp_path, stem="transcript.original")
    names = {p.name for p in written}
    assert names == {
        "transcript.original.md",
        "transcript.original.srt",
        "transcript.original.vtt",
        "transcript.original.json",
    }
    payload = json.loads((tmp_path / "transcript.original.json").read_text(encoding="utf-8"))
    assert payload["language"] == "en"
    assert len(payload["segments"]) == 3
    assert payload["segments"][1]["text"] == "مرحبا"


def test_export_formats_subset(tmp_path: Path) -> None:
    meta = TranscriptMeta(meeting_id="m1", title="T")
    written = export_transcript(_segments(), meta, tmp_path, formats=["json"])
    assert [p.name for p in written] == ["transcript.json"]
