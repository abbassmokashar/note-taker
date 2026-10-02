"""Audio normalization.

Extracts/creates a 16 kHz mono PCM WAV suitable for speech recognition, with
optional loudness normalization. Uses ffmpeg when available.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg is required but not installed."""


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def wav_format(path: Path) -> tuple[int, int]:
    """Return (sample_rate, channels) for a WAV file."""
    with contextlib.closing(wave.open(str(path), "rb")) as handle:
        return handle.getframerate(), handle.getnchannels()


def is_target_wav(path: Path) -> bool:
    if path.suffix.lower() != ".wav":
        return False
    try:
        rate, channels = wav_format(path)
    except (wave.Error, OSError):
        return False
    return rate == TARGET_SAMPLE_RATE and channels == TARGET_CHANNELS


def probe_duration(path: Path) -> float | None:
    """Duration in seconds, or None if it cannot be determined."""
    if path.suffix.lower() == ".wav":
        try:
            with contextlib.closing(wave.open(str(path), "rb")) as handle:
                frames = handle.getnframes()
                rate = handle.getframerate()
                if rate:
                    return frames / float(rate)
        except (wave.Error, OSError):
            pass

    ffprobe = ffprobe_path()
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        return float(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def normalize_audio(src: Path, dest: Path, *, sample_rate: int = TARGET_SAMPLE_RATE) -> Path:
    """Convert ``src`` to mono 16-bit PCM WAV at ``sample_rate`` with loudnorm."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise FFmpegNotFoundError(
            "ffmpeg is required to normalize audio but was not found on PATH."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-ac", str(TARGET_CHANNELS),
        "-ar", str(sample_rate),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "pcm_s16le",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to normalize audio: {result.stderr[-2000:]}")
    return dest


def ensure_16k_mono(src: Path, work_dir: Path) -> Path:
    """Return a 16 kHz mono WAV for ``src``, reusing it if already in that format."""
    if is_target_wav(src):
        return src
    dest = work_dir / "audio16k.wav"
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Reusing existing normalized audio: %s", dest)
        return dest
    logger.info("Normalizing %s -> %s", src, dest)
    return normalize_audio(src, dest)
