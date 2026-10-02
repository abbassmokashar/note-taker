from __future__ import annotations

import json
from pathlib import Path

from meetingbot.pipeline.speakers import (
    CaptionEvent,
    align_speakers,
    load_caption_events,
    load_recording_start_wall,
    merge_consecutive,
)
from meetingbot.providers.base import TranscriptSegment


def _seg(
    start: float, end: float, text: str = "x", speaker: str | None = None
) -> TranscriptSegment:
    return TranscriptSegment(start_s=start, end_s=end, text=text, speaker=speaker)


def test_load_caption_events_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"t_wall": 2.0, "speaker_name": "Bob", "caption_text": "b"}),
                "not json",
                json.dumps({"t_wall": 1.0, "speaker_name": "Alice", "caption_text": "a"}),
                json.dumps({"speaker_name": "Missing"}),
            ]
        ),
        encoding="utf-8",
    )
    events = load_caption_events(path)
    assert [e.speaker_name for e in events] == ["Alice", "Bob"]  # sorted by time


def test_load_caption_events_missing_file(tmp_path: Path) -> None:
    assert load_caption_events(tmp_path / "nope.jsonl") == []


def test_recording_start_wall(tmp_path: Path) -> None:
    (tmp_path / "recording_meta.json").write_text('{"start_wall": 1000.0}', encoding="utf-8")
    assert load_recording_start_wall(tmp_path) == 1000.0
    assert load_recording_start_wall(tmp_path / "other") is None


def test_align_assigns_by_overlap() -> None:
    events = [
        CaptionEvent(t_wall=1000.0, speaker_name="Alice"),
        CaptionEvent(t_wall=1010.0, speaker_name="Bob"),
    ]
    segments = [_seg(0, 5, "hello"), _seg(12, 15, "hi")]
    align_speakers(segments, events, recording_start_wall=1000.0)
    assert segments[0].speaker == "Alice"
    assert segments[1].speaker == "Bob"


def test_align_without_events_leaves_none() -> None:
    segments = [_seg(0, 5)]
    align_speakers(segments, [], recording_start_wall=1000.0)
    assert segments[0].speaker is None


def test_align_without_start_wall_leaves_none() -> None:
    events = [CaptionEvent(t_wall=1000.0, speaker_name="Alice")]
    segments = [_seg(0, 5)]
    align_speakers(segments, events, recording_start_wall=None)
    assert segments[0].speaker is None


def test_merge_consecutive_same_speaker() -> None:
    segments = [
        _seg(0, 5, "a", speaker="Alice"),
        _seg(5.5, 8, "b", speaker="Alice"),
        _seg(10, 12, "c", speaker="Bob"),
    ]
    merged = merge_consecutive(segments, gap_seconds=2.0)
    assert len(merged) == 2
    assert merged[0].speaker == "Alice"
    assert merged[0].text == "a b"
    assert merged[0].end_s == 8
    assert merged[1].speaker == "Bob"
    assert [s.id for s in merged] == [0, 1]


def test_merge_does_not_merge_across_speakers() -> None:
    segments = [
        _seg(0, 5, "a", speaker="Alice"),
        _seg(5.5, 8, "b", speaker="Bob"),
    ]
    assert len(merge_consecutive(segments)) == 2
