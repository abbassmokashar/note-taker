from __future__ import annotations

from pathlib import Path

import pytest

from meetingbot.config import ConfigError, Secrets, Settings, load_settings


def test_defaults_when_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings(env_file=None)
    assert isinstance(settings, Settings)
    assert settings.calendar.auto_invite is False
    assert settings.llm.provider == "gemini"
    assert settings.outputs.arabic_style == "msa_simple"
    assert settings.data_dir == Path("data")


def test_derived_paths() -> None:
    settings = Settings()
    assert settings.meetings_dir == Path("data/meetings")
    assert settings.db_path == Path("data/meetingbot.db")
    assert settings.browser_profile_dir == Path("data/browser_profile")


def test_valid_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
bot:
  display_name: "Recorder"
  account_email: "bot@example.com"
calendar:
  auto_invite: true
  timezone: "Asia/Beirut"
llm:
  provider: ollama
outputs:
  arabic_style: lebanese_colloquial
""",
        encoding="utf-8",
    )
    settings = load_settings(cfg, env_file=None)
    assert settings.bot.display_name == "Recorder"
    assert settings.bot.account_email == "bot@example.com"
    assert settings.calendar.auto_invite is True
    assert settings.llm.provider == "ollama"
    assert settings.outputs.arabic_style == "lebanese_colloquial"


def test_missing_file_with_require(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_settings(tmp_path / "nope.yaml", env_file=None, require_file=True)
    assert "not found" in str(exc.value)


def test_invalid_yaml_root(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_settings(cfg, env_file=None)
    assert "mapping" in str(exc.value)


def test_validation_error_is_readable(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("calendar:\n  poll_seconds: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_settings(cfg, env_file=None)
    message = str(exc.value)
    assert "calendar.poll_seconds" in message
    assert "Invalid configuration" in message


def test_env_override_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "custom"
    monkeypatch.setenv("MEETINGBOT_DATA_DIR", str(target))
    settings = load_settings(env_file=None)
    assert settings.data_dir == target


def test_secrets_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "  abc123  ")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    secrets = Secrets.from_env()
    assert secrets.gemini_api_key == "abc123"
    assert secrets.hf_token is None
