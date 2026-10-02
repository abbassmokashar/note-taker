"""Local capture fallback (Phase 9).

For meetings where the bot cannot get in (blocked external accounts), record the
user's own computer audio and feed it through the same pipeline. OS-specific ffmpeg
input is documented in docs/TROUBLESHOOTING.md.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DEVICES = {
    "linux": "default",
    "darwin": ":1",           # BlackHole 2ch (install a loopback device)
    "win32": "Stereo Mix",    # or "virtual-audio-capturer"
}


class LocalCaptureError(RuntimeError):
    """Raised when local capture cannot start."""


def system_audio_command(
    platform: str,
    output: Path,
    *,
    device: str | None = None,
    seconds: int = 0,
    ffmpeg: str = "ffmpeg",
    sample_rate: int = 16000,
) -> list[str]:
    """Build the ffmpeg command to record system audio on this platform."""
    device = device or DEFAULT_DEVICES.get(platform, "default")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]

    if platform == "linux":
        cmd += ["-f", "pulse", "-i", device]
    elif platform == "darwin":
        cmd += ["-f", "avfoundation", "-i", device]
    elif platform == "win32":
        cmd += ["-f", "dshow", "-i", f"audio={device}"]
    else:
        raise LocalCaptureError(f"Unsupported platform for local capture: {platform}")

    if seconds > 0:
        cmd += ["-t", str(seconds)]
    cmd += ["-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(output)]
    return cmd


def record_local(
    output: Path,
    *,
    seconds: int = 0,
    device: str | None = None,
    platform: str | None = None,
    run=subprocess.run,
) -> Path:
    """Record system audio to ``output``. ``seconds=0`` records until Ctrl+C."""
    if shutil.which("ffmpeg") is None:
        raise LocalCaptureError("ffmpeg is required for local capture but was not found.")
    platform = platform or sys.platform
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = system_audio_command(platform, output, device=device, seconds=seconds)
    logger.info("Recording system audio: %s", " ".join(cmd))
    result = run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise LocalCaptureError(f"ffmpeg local capture failed: {result.stderr[-1000:]}")
    return output
