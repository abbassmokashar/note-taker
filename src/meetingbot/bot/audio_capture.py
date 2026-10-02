"""Audio capture: PulseAudio null sink + ffmpeg.

Meet's audio is routed to a PulseAudio null sink; ffmpeg records the sink's monitor.
Output is written as short Opus segments so a crash loses at most one segment, then
concatenated into ``recording.opus`` when the meeting ends.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SINK = "meet_sink"


class CaptureError(RuntimeError):
    """Raised when audio capture cannot start or stop."""


def pulse_available() -> bool:
    return shutil.which("pactl") is not None and shutil.which("pulseaudio") is not None


def ensure_null_sink(sink_name: str = DEFAULT_SINK, *, run=subprocess.run) -> bool:
    """Create + load a PulseAudio null sink and make it the default. Returns success."""
    if not shutil.which("pactl"):
        logger.warning("pactl not found; skipping PulseAudio null-sink setup.")
        return False
    try:
        run(["pactl", "load-module", "module-null-sink", f"sink_name={sink_name}"], check=False)
        run(["pactl", "set-default-sink", sink_name], check=False)
        return True
    except OSError as exc:  # pragma: no cover - depends on environment
        logger.warning("Could not set up PulseAudio null sink: %s", exc)
        return False


class AudioCapture:
    """Controls an ffmpeg process recording from a PulseAudio monitor."""

    def __init__(
        self,
        out_dir: Path,
        *,
        sink_name: str = DEFAULT_SINK,
        segment_seconds: int = 600,
        bitrate: str = "32k",
        sample_rate: int = 16000,
        ffmpeg_bin: str = "ffmpeg",
        popen=subprocess.Popen,
        run=subprocess.run,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.sink_name = sink_name
        self.segment_seconds = segment_seconds
        self.bitrate = bitrate
        self.sample_rate = sample_rate
        self.ffmpeg_bin = ffmpeg_bin
        self._popen = popen
        self._run = run
        self._process = None

    @property
    def segment_pattern(self) -> Path:
        return self.out_dir / "parts" / "part_%03d.opus"

    def command(self) -> list[str]:
        return [
            self.ffmpeg_bin, "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "pulse", "-i", f"{self.sink_name}.monitor",
            "-ac", "1", "-ar", str(self.sample_rate),
            "-c:a", "libopus", "-b:a", self.bitrate,
            "-f", "segment",
            "-segment_time", str(self.segment_seconds),
            "-reset_timestamps", "1",
            str(self.segment_pattern),
        ]

    def start(self) -> None:
        if self._process is not None:
            raise CaptureError("Audio capture is already running.")
        (self.out_dir / "parts").mkdir(parents=True, exist_ok=True)
        logger.info("Starting audio capture: %s", " ".join(self.command()))
        try:
            self._process = self._popen(
                self.command(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        except OSError as exc:
            raise CaptureError(f"Could not start ffmpeg: {exc}") from exc

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self, timeout: float = 10.0) -> None:
        if self._process is None:
            return
        logger.info("Stopping audio capture.")
        try:
            self._process.terminate()
            self._process.wait(timeout=timeout)
        except Exception:  # noqa: BLE001 - kill if terminate is ignored
            try:
                self._process.kill()
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._process = None

    def segments(self) -> list[Path]:
        return sorted((self.out_dir / "parts").glob("part_*.opus"))

    def finalize(self, filename: str = "recording.opus") -> Path | None:
        """Concatenate segments into a single Opus file. Returns the output path."""
        parts = self.segments()
        if not parts:
            logger.warning("No audio segments were produced.")
            return None
        output = self.out_dir / filename
        if len(parts) == 1:
            shutil.copyfile(parts[0], output)
            return output

        list_file = self.out_dir / "parts" / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8"
        )
        cmd = [
            self.ffmpeg_bin, "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(output),
        ]
        result = self._run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise CaptureError(f"ffmpeg concat failed: {result.stderr[-1000:]}")
        return output
