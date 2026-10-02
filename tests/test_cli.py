from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from meetingbot.cli import app

runner = CliRunner()


def test_help_works() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "record" in result.stdout.lower()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "meetingbot" in result.stdout


def test_init_creates_data_dir_and_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEETINGBOT_DATA_DIR", str(tmp_path / "data"))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "data" / "meetingbot.db").exists()


def test_doctor_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEETINGBOT_DATA_DIR", str(tmp_path / "data"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout
    assert "transcription provider" in result.stdout


def test_list_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEETINGBOT_DATA_DIR", str(tmp_path / "data"))
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0, result.stdout
    assert "No meetings yet" in result.stdout


def test_run_without_google_libs_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEETINGBOT_DATA_DIR", str(tmp_path / "data"))
    # `run` requires a config file to exist (it is the production entry point).
    (tmp_path / "config.yaml").write_text("bot:\n  display_name: Test\n", encoding="utf-8")
    result = runner.invoke(app, ["run"])
    # No Calendar token/libs here, so it fails with a clear message.
    assert result.exit_code == 1
    assert "Calendar auth failed" in result.stdout


def test_join_without_browser_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEETINGBOT_DATA_DIR", str(tmp_path / "data"))
    result = runner.invoke(app, ["join", "https://meet.google.com/abc-defg-hij"])
    # Without Playwright installed the join fails with a clear, actionable message.
    assert result.exit_code == 1
    assert "Join failed" in result.stdout


def test_invalid_config_reports_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text("calendar:\n  poll_seconds: 1\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "--config", str(bad)])
    assert result.exit_code == 2
    assert "poll_seconds" in result.stdout
