from __future__ import annotations

from pathlib import Path

from meetingbot.bot.health import Heartbeat, free_disk_gb, has_disk_space


def test_heartbeat_detects_stall() -> None:
    current = {"t": 0.0}
    beat = Heartbeat(stall_seconds=10.0, now=lambda: current["t"])
    assert not beat.is_stalled()
    current["t"] = 9.0
    assert not beat.is_stalled()
    current["t"] = 11.0
    assert beat.is_stalled()
    beat.beat()
    assert not beat.is_stalled()


def test_heartbeat_seconds_since_beat() -> None:
    current = {"t": 0.0}
    beat = Heartbeat(stall_seconds=5.0, now=lambda: current["t"])
    current["t"] = 3.0
    assert beat.seconds_since_beat() == 3.0


def test_free_disk_gb_positive(tmp_path: Path) -> None:
    assert free_disk_gb(tmp_path) > 0


def test_has_disk_space_normal(tmp_path: Path) -> None:
    assert has_disk_space(tmp_path, minimum_gb=0.001) is True


def test_has_disk_space_refuses_when_low(tmp_path: Path) -> None:
    # Require an impossibly large amount to force the refusal branch.
    assert has_disk_space(tmp_path, minimum_gb=10**9) is False
