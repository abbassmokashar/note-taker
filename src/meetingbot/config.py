"""Configuration loading and validation.

Settings come from a YAML file (``config.yaml``) with secrets supplied via the
environment / ``.env`` file. Validation errors are surfaced as :class:`ConfigError`
with a readable message rather than a raw pydantic traceback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

DEFAULT_CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG_PATH = Path("config.example.yaml")


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


class BotConfig(BaseModel):
    display_name: str = "Notetaker (recording this meeting)"
    account_email: str = ""
    announce_in_chat: bool = True
    announcement_en: str = (
        "Hi, I'm an automated notetaker. This meeting is being recorded and "
        "transcribed. Please tell the host if you object."
    )
    announcement_ar: str = (
        "مرحبا، أنا مساعد آلي لتدوين الملاحظات. هذا الاجتماع قيد التسجيل والتفريغ "
        "النصي. الرجاء إبلاغ المضيف إذا كان لديكم اعتراض."
    )
    join_early_seconds: int = Field(default=30, ge=0)
    waiting_room_timeout_minutes: int = Field(default=10, ge=0)
    leave_when_alone_after_seconds: int = Field(default=120, ge=0)
    max_meeting_hours: float = Field(default=4.0, gt=0)
    record_video: bool = False
    video_resolution: str = "1280x720"
    language: str = "en-US"


class JoinRules(BaseModel):
    default: Literal["join", "skip"] = "join"
    skip_title_contains: list[str] = Field(default_factory=lambda: ["[private]", "lunch"])
    skip_if_declined: bool = True
    skip_all_day: bool = True
    skip_tag: str = "#nobot"


class CalendarConfig(BaseModel):
    poll_seconds: int = Field(default=60, ge=10)
    only_events_with_meet_link: bool = True
    timezone: str = "Asia/Beirut"
    lookahead_hours: int = Field(default=24, ge=1)
    max_concurrent_bots: int = Field(default=2, ge=1)
    auto_invite: bool = False
    join_rules: JoinRules = Field(default_factory=JoinRules)


class TranscriptionConfig(BaseModel):
    provider: Literal["faster_whisper", "groq_whisper"] = "faster_whisper"
    model: str = "auto"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    compute_type: str = "auto"
    language: str | None = None
    beam_size: int = Field(default=5, ge=1)
    vad_filter: bool = True
    # Optional pyannote diarization fallback when captions are unavailable.
    diarization: bool = False
    initial_prompt_ar: str = (
        "اجتماع عمل بالعربية اللبنانية مع بعض الكلمات الإنكليزية والفرنسية."
    )
    glossary: list[str] = Field(default_factory=list)
    # Optional LLM pass to fix obvious ASR spelling errors using the glossary.
    glossary_correction: bool = False


class LLMConfig(BaseModel):
    provider: Literal["gemini", "ollama"] = "gemini"
    gemini_model: str = "gemini-2.5-flash"
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_host: str = "http://localhost:11434"
    fallback_provider: Literal["gemini", "ollama"] | None = "ollama"
    chunk_chars: int = Field(default=6000, ge=500)
    max_retries: int = Field(default=5, ge=0)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class OutputsConfig(BaseModel):
    languages: list[str] = Field(default_factory=lambda: ["en", "ar"])
    arabic_style: Literal["msa_simple", "lebanese_colloquial"] = "msa_simple"
    formats: list[str] = Field(default_factory=lambda: ["md", "srt", "vtt", "json", "pdf"])
    keep_video: bool = False
    delete_audio_after_days: int = Field(default=90, ge=0)


class EmailConfig(BaseModel):
    enabled: bool = False
    to: str = ""
    smtp_user: str = ""
    smtp_app_password_env: str = "SMTP_APP_PASSWORD"


class DriveConfig(BaseModel):
    enabled: bool = False
    folder_name: str = "MeetingBot"


class S3Config(BaseModel):
    """Any S3-compatible store: Cloudflare R2, Backblaze B2, MinIO, AWS S3."""

    enabled: bool = False
    endpoint_url: str = ""        # e.g. https://<account>.r2.cloudflarestorage.com
    bucket: str = "meetingbot"
    prefix: str = "meetings"
    region: str = "auto"
    access_key_env: str = "S3_ACCESS_KEY_ID"
    secret_key_env: str = "S3_SECRET_ACCESS_KEY"


class WebUIConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)


class DeliveryConfig(BaseModel):
    email: EmailConfig = Field(default_factory=EmailConfig)
    drive: DriveConfig = Field(default_factory=DriveConfig)
    s3: S3Config = Field(default_factory=S3Config)
    web_ui: WebUIConfig = Field(default_factory=WebUIConfig)


class Settings(BaseModel):
    """Fully validated application settings."""

    bot: BotConfig = Field(default_factory=BotConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    outputs: OutputsConfig = Field(default_factory=OutputsConfig)
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)

    data_dir: Path = Path("data")
    log_level: str = "INFO"

    # --- derived paths -------------------------------------------------
    @property
    def meetings_dir(self) -> Path:
        return self.data_dir / "meetings"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "meetingbot.db"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser_profile"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.meetings_dir):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Secrets:
    """Secret values read from the environment only."""

    gemini_api_key: str | None = None
    hf_token: str | None = None
    smtp_app_password: str | None = None
    groq_api_key: str | None = None
    web_token: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    @classmethod
    def from_env(cls) -> Secrets:
        def get(name: str) -> str | None:
            value = os.environ.get(name, "").strip()
            return value or None

        return cls(
            gemini_api_key=get("GEMINI_API_KEY"),
            hf_token=get("HF_TOKEN"),
            smtp_app_password=get("SMTP_APP_PASSWORD"),
            groq_api_key=get("GROQ_API_KEY"),
            web_token=get("MEETINGBOT_WEB_TOKEN"),
            s3_access_key_id=get("S3_ACCESS_KEY_ID"),
            s3_secret_access_key=get("S3_SECRET_ACCESS_KEY"),
        )


def _read_yaml(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read config file '{path}': {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file '{path}' is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config file '{path}' must contain a YAML mapping at the top level.")
    return data


def load_settings(
    config_path: str | Path | None = None,
    *,
    env_file: str | Path | None = ".env",
    require_file: bool = False,
) -> Settings:
    """Load and validate settings from YAML + environment.

    If ``config_path`` is not given, ``config.yaml`` is used when present,
    otherwise built-in defaults. Set ``require_file=True`` to make a missing
    file an error (useful for explicit CLI invocations).
    """

    if env_file is not None:
        load_dotenv(env_file, override=False)

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    raw: dict = {}
    if path.exists():
        raw = _read_yaml(path)
    elif require_file:
        raise ConfigError(
            f"Config file '{path}' not found. Copy '{EXAMPLE_CONFIG_PATH}' to '{path}' first."
        )

    # Allow a top-level data_dir / log_level override from the environment.
    if env_data_dir := os.environ.get("MEETINGBOT_DATA_DIR"):
        raw["data_dir"] = env_data_dir
    if env_log_level := os.environ.get("MEETINGBOT_LOG_LEVEL"):
        raw["log_level"] = env_log_level

    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc, path)) from exc


def _format_validation_error(exc: ValidationError, path: Path) -> str:
    lines = [f"Invalid configuration in '{path}':"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
