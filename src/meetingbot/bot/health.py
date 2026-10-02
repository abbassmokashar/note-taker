"""Failure artifacts, a heartbeat for detecting frozen capture, and a disk guard."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_FREE_GB = 5.0


def free_disk_gb(path: Path) -> float:
    usage = shutil.disk_usage(str(path))
    return usage.free / (1024**3)


def has_disk_space(path: Path, minimum_gb: float = MIN_FREE_GB) -> bool:
    try:
        free = free_disk_gb(path)
    except OSError:
        return True  # do not block recording if we cannot measure
    if free < minimum_gb:
        logger.error("Refusing to record: only %.1f GB free (< %.1f GB).", free, minimum_gb)
        return False
    return True


def capture_failure_artifacts(page, debug_dir: Path, name: str = "failure") -> list[Path]:
    """Write a screenshot and page HTML for debugging. Never raises."""
    written: list[Path] = []
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        screenshot = getattr(page, "screenshot", None)
        if callable(screenshot):
            shot = debug_dir / f"{name}.png"
            screenshot(str(shot))
            written.append(shot)
        content = getattr(page, "content", None)
        if callable(content):
            html = debug_dir / f"{name}.html"
            html.write_text(content(), encoding="utf-8")
            written.append(html)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not capture failure artifacts: %s", exc)
    return written


class Heartbeat:
    """Detects a frozen process by watching for a periodically-updated marker."""

    def __init__(self, stall_seconds: float = 60.0, *, now=time.monotonic) -> None:
        self.stall_seconds = stall_seconds
        self._now = now
        self._last = now()

    def beat(self) -> None:
        self._last = self._now()

    def seconds_since_beat(self) -> float:
        return self._now() - self._last

    def is_stalled(self) -> bool:
        return self.seconds_since_beat() >= self.stall_seconds
