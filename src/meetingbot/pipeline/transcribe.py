"""Transcription stage.

Long audio is split into chunks; each chunk's result is cached as JSON so a crash
mid-way resumes instead of re-transcribing from the start.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from meetingbot.pipeline.audio_prep import ffmpeg_path, probe_duration
from meetingbot.providers.base import (
    Transcriber,
    TranscriptionResult,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]


class AudioParts:
    """The list of (audio_file, offset_seconds) pieces to transcribe."""

    def __init__(self, parts: list[tuple[Path, float]]) -> None:
        self.parts = parts

    def __len__(self) -> int:
        return len(self.parts)


def split_chunks(audio_path: Path, out_dir: Path, chunk_seconds: int) -> AudioParts:
    """Split audio into <= ``chunk_seconds`` pieces. Returns [(path, offset_s)].

    Falls back to a single part when ffmpeg is unavailable or the file is short.
    """
    duration = probe_duration(audio_path)
    ffmpeg = ffmpeg_path()

    if ffmpeg is None or duration is None or duration <= chunk_seconds:
        return AudioParts([(audio_path, 0.0)])

    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(chunks_dir.glob("chunk_*.wav"))
    if not existing:
        pattern = chunks_dir / "chunk_%04d.wav"
        cmd = [
            ffmpeg, "-y", "-i", str(audio_path),
            "-f", "segment",
            "-segment_time", str(chunk_seconds),
            "-c", "copy",
            str(pattern),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
        if result.returncode != 0:
            logger.warning("ffmpeg chunking failed, using single part: %s", result.stderr[-500:])
            return AudioParts([(audio_path, 0.0)])
        existing = sorted(chunks_dir.glob("chunk_*.wav"))

    parts: list[tuple[Path, float]] = []
    offset = 0.0
    for chunk in existing:
        parts.append((chunk, offset))
        offset += probe_duration(chunk) or chunk_seconds
    return AudioParts(parts)


def _load_part(cache_file: Path) -> list[TranscriptSegment] | None:
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return [TranscriptSegment.from_dict(item) for item in data]


def _save_part(cache_file: Path, segments: list[TranscriptSegment]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = [seg.to_dict() for seg in segments]
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def transcribe_audio(
    transcriber: Transcriber,
    audio_path: Path,
    work_dir: Path,
    *,
    language: str | None = None,
    initial_prompt: str | None = None,
    chunk_seconds: int = 600,
    force: bool = False,
    progress_cb: ProgressCb | None = None,
) -> TranscriptionResult:
    """Transcribe ``audio_path``, caching per-chunk results under ``work_dir/parts``."""
    parts = split_chunks(audio_path, work_dir, chunk_seconds)
    parts_dir = work_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    merged: list[TranscriptSegment] = []
    detected_language: str | None = None
    total = len(parts)

    for index, (part_path, offset) in enumerate(parts.parts):
        cache_file = parts_dir / f"part_{index:04d}.json"
        cached = None if force else _load_part(cache_file)
        if progress_cb:
            progress_cb(index + 1, total, "cached" if cached is not None else "transcribing")

        if cached is not None:
            segments = cached
        else:
            logger.info("Transcribing part %d/%d: %s", index + 1, total, part_path.name)
            result = transcriber.transcribe(
                part_path, language=language, initial_prompt=initial_prompt
            )
            segments = result.segments
            if detected_language is None and result.language:
                detected_language = result.language
            _save_part(cache_file, segments)

        for seg in segments:
            seg.start_s += offset
            seg.end_s += offset
            merged.append(seg)

    merged.sort(key=lambda s: s.start_s)
    for new_id, seg in enumerate(merged):
        seg.id = new_id

    if detected_language is None:
        for seg in merged:
            if seg.language:
                detected_language = seg.language
                break

    duration = probe_duration(audio_path) or (merged[-1].end_s if merged else None)
    return TranscriptionResult(segments=merged, language=detected_language, duration_s=duration)
