"""Speaker attribution.

Primary method: align Whisper segments to the caption timeline (captions give speaker
names and timing, not the transcript). If caption events are missing, segments keep a
null speaker and the pipeline still completes. Optional pyannote diarization is a
future fallback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from meetingbot.providers.base import TranscriptSegment

logger = logging.getLogger(__name__)

CAPTION_HOLD_SECONDS = 6.0


@dataclass
class CaptionEvent:
    t_wall: float
    speaker_name: str
    caption_text: str = ""


def load_caption_events(path: Path) -> list[CaptionEvent]:
    """Read ``events.jsonl``; returns [] if the file is missing/unreadable."""
    if not path.exists():
        return []
    events: list[CaptionEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            events.append(
                CaptionEvent(
                    t_wall=float(item["t_wall"]),
                    speaker_name=str(item.get("speaker_name") or "Unknown"),
                    caption_text=str(item.get("caption_text") or ""),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    events.sort(key=lambda e: e.t_wall)
    return events


def load_recording_start_wall(folder: Path) -> float | None:
    """Read the wall-clock start time recorded when capture began."""
    meta = folder / "recording_meta.json"
    if not meta.exists():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        return float(data["start_wall"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _intervals(
    events: list[CaptionEvent], start_wall: float
) -> list[tuple[float, float, str]]:
    intervals: list[tuple[float, float, str]] = []
    for index, event in enumerate(events):
        start = event.t_wall - start_wall
        if index + 1 < len(events):
            end = events[index + 1].t_wall - start_wall
        else:
            end = start + CAPTION_HOLD_SECONDS
        intervals.append((start, max(end, start), event.speaker_name))
    return intervals


def _best_speaker(
    seg: TranscriptSegment, intervals: list[tuple[float, float, str]]
) -> str | None:
    best_overlap = 0.0
    best_speaker: str | None = None
    for start, end, speaker in intervals:
        overlap = min(seg.end_s, end) - max(seg.start_s, start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    return best_speaker


def align_speakers(
    segments: list[TranscriptSegment],
    events: list[CaptionEvent],
    recording_start_wall: float | None,
) -> list[TranscriptSegment]:
    """Assign ``speaker`` by maximum time overlap with the caption timeline."""
    if not events or recording_start_wall is None:
        logger.info("No caption events available; leaving speakers unlabeled.")
        return segments

    intervals = _intervals(events, recording_start_wall)
    attributed = 0
    for seg in segments:
        speaker = _best_speaker(seg, intervals)
        if speaker:
            seg.speaker = speaker
            attributed += 1
    logger.info("Attributed %d/%d segments to speakers.", attributed, len(segments))
    return segments


def merge_consecutive(
    segments: list[TranscriptSegment], gap_seconds: float = 2.0
) -> list[TranscriptSegment]:
    """Merge adjacent same-speaker segments separated by less than ``gap_seconds``."""
    if not segments:
        return []
    merged: list[TranscriptSegment] = []
    for seg in segments:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.speaker
            and previous.speaker == seg.speaker
            and (seg.start_s - previous.end_s) < gap_seconds
        ):
            previous.end_s = max(previous.end_s, seg.end_s)
            previous.text = f"{previous.text} {seg.text}".strip()
            if seg.text_en:
                previous.text_en = f"{previous.text_en or ''} {seg.text_en}".strip()
            if seg.text_ar:
                previous.text_ar = f"{previous.text_ar or ''} {seg.text_ar}".strip()
            continue
        merged.append(seg)
    for index, seg in enumerate(merged):
        seg.id = index
    return merged
