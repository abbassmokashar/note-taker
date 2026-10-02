from __future__ import annotations

from pathlib import Path

import pytest

from meetingbot.bot.local_capture import (
    LocalCaptureError,
    record_local,
    system_audio_command,
)


def test_linux_command(tmp_path: Path) -> None:
    cmd = system_audio_command("linux", tmp_path / "out.wav")
    assert "-f" in cmd and "pulse" in cmd
    assert cmd[-1].endswith("out.wav")


def test_windows_command(tmp_path: Path) -> None:
    cmd = system_audio_command("win32", tmp_path / "out.wav", device="Stereo Mix")
    assert "dshow" in cmd
    assert "audio=Stereo Mix" in cmd


def test_macos_command(tmp_path: Path) -> None:
    cmd = system_audio_command("darwin", tmp_path / "out.wav")
    assert "avfoundation" in cmd


def test_seconds_adds_time_limit(tmp_path: Path) -> None:
    cmd = system_audio_command("linux", tmp_path / "out.wav", seconds=30)
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "30"


def test_unsupported_platform(tmp_path: Path) -> None:
    with pytest.raises(LocalCaptureError):
        system_audio_command("plan9", tmp_path / "out.wav")


def test_record_local_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    class Result:
        returncode = 0
        stderr = ""

    output = record_local(
        tmp_path / "rec.wav", seconds=1, platform="linux", run=lambda *a, **k: Result()
    )
    assert output == tmp_path / "rec.wav"


def test_record_local_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    class Result:
        returncode = 1
        stderr = "boom"

    with pytest.raises(LocalCaptureError):
        record_local(tmp_path / "rec.wav", platform="linux", run=lambda *a, **k: Result())


def test_record_local_without_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(LocalCaptureError):
        record_local(tmp_path / "rec.wav", platform="linux")
