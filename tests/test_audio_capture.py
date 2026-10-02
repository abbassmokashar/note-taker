from __future__ import annotations

from pathlib import Path

import pytest

from meetingbot.bot.audio_capture import AudioCapture, CaptureError


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self._running = True

    def poll(self):
        return None if self._running else 0

    def terminate(self) -> None:
        self.terminated = True
        self._running = False

    def kill(self) -> None:
        self.killed = True
        self._running = False

    def wait(self, timeout=None) -> int:
        self._running = False
        return 0


def test_command_targets_null_sink_monitor(tmp_path: Path) -> None:
    capture = AudioCapture(tmp_path, sink_name="meet_sink", segment_seconds=600)
    cmd = capture.command()
    assert "meet_sink.monitor" in cmd
    assert "libopus" in cmd
    assert "segment" in cmd
    assert "600" in cmd
    assert cmd[-1].endswith("part_%03d.opus")


def test_start_and_stop(tmp_path: Path) -> None:
    started: dict = {}

    def fake_popen(cmd, **kwargs):
        started["cmd"] = cmd
        return FakeProcess()

    capture = AudioCapture(tmp_path, popen=fake_popen)
    capture.start()
    assert capture.is_running()
    assert (tmp_path / "parts").exists()
    capture.stop()
    assert not capture.is_running()


def test_start_twice_raises(tmp_path: Path) -> None:
    capture = AudioCapture(tmp_path, popen=lambda *a, **k: FakeProcess())
    capture.start()
    with pytest.raises(CaptureError):
        capture.start()
    capture.stop()


def test_finalize_single_segment_copies(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "part_000.opus").write_bytes(b"audio")
    capture = AudioCapture(tmp_path)
    output = capture.finalize()
    assert output is not None
    assert output.read_bytes() == b"audio"


def test_finalize_without_segments_returns_none(tmp_path: Path) -> None:
    capture = AudioCapture(tmp_path)
    assert capture.finalize() is None
