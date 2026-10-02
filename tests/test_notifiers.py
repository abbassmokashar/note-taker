from __future__ import annotations

from pathlib import Path

from meetingbot.config import S3Config, Secrets, Settings
from meetingbot.providers.notifiers import (
    EmailNotifier,
    LocalFilesNotifier,
    S3Uploader,
    SmtpSettings,
    build_notifiers,
)


def test_local_notifier_noop() -> None:
    LocalFilesNotifier().notify("m1", "subject", "body", [])


def test_email_message_builds_with_attachments(tmp_path: Path) -> None:
    attachment = tmp_path / "notes.en.md"
    attachment.write_text("# Notes", encoding="utf-8")
    notifier = EmailNotifier(SmtpSettings(user="me@x.com", password="pw", to="you@x.com"))
    message = notifier._message("Subject", "Body text", [attachment, tmp_path / "missing.pdf"])
    assert message["To"] == "you@x.com"
    assert message["Subject"] == "Subject"
    payloads = [p.get_filename() for p in message.iter_attachments()]
    assert payloads == ["notes.en.md"]


def test_email_skips_large_binary_recording(tmp_path: Path) -> None:
    notes = tmp_path / "notes.en.md"
    notes.write_text("# Notes", encoding="utf-8")
    recording = tmp_path / "recording.opus"
    recording.write_bytes(b"\x00" * 100)
    notifier = EmailNotifier(SmtpSettings(user="me@x.com", password="pw", to="you@x.com"))
    message = notifier._message("S", "B", [notes, recording])
    # The recording must never be attached to email.
    assert [p.get_filename() for p in message.iter_attachments()] == ["notes.en.md"]


def test_s3_object_key() -> None:
    uploader = S3Uploader(S3Config(bucket="b", prefix="meetings"), "ak", "sk")
    assert uploader.object_key("abc", "notes.en.md") == "meetings/abc/notes.en.md"


def test_s3_uploads_all_attachments(tmp_path: Path) -> None:
    notes = tmp_path / "notes.en.md"
    notes.write_text("# Notes", encoding="utf-8")
    recording = tmp_path / "recording.opus"
    recording.write_bytes(b"audio")

    uploaded: list[tuple] = []

    class FakeClient:
        def upload_file(self, filename, bucket, key):
            uploaded.append((filename, bucket, key))

    uploader = S3Uploader(
        S3Config(bucket="mybucket", prefix="meetings"),
        "ak",
        "sk",
        client_factory=FakeClient,
    )
    uploader.notify("m1", "subject", "body", [notes, recording])
    keys = sorted(k for _, _, k in uploaded)
    assert keys == ["meetings/m1/notes.en.md", "meetings/m1/recording.opus"]
    assert all(bucket == "mybucket" for _, bucket, _ in uploaded)


def test_build_notifiers_includes_s3(monkeypatch) -> None:
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    settings = Settings()
    settings.delivery.s3.enabled = True
    notifiers = build_notifiers(settings, Secrets())
    assert any(isinstance(n, S3Uploader) for n in notifiers)


def test_build_notifiers_skips_s3_without_credentials() -> None:
    settings = Settings()
    settings.delivery.s3.enabled = True
    notifiers = build_notifiers(settings, Secrets())
    assert not any(isinstance(n, S3Uploader) for n in notifiers)


def test_build_notifiers_local_only_by_default() -> None:
    settings = Settings()
    notifiers = build_notifiers(settings, Secrets())
    assert len(notifiers) == 1
    assert isinstance(notifiers[0], LocalFilesNotifier)


def test_build_notifiers_email_when_configured() -> None:
    settings = Settings()
    settings.delivery.email.enabled = True
    settings.delivery.email.to = "you@x.com"
    settings.delivery.email.smtp_user = "me@x.com"
    notifiers = build_notifiers(settings, Secrets(smtp_app_password="app-pw"))
    assert any(isinstance(n, EmailNotifier) for n in notifiers)


def test_email_enabled_but_missing_password_is_skipped() -> None:
    settings = Settings()
    settings.delivery.email.enabled = True
    settings.delivery.email.to = "you@x.com"
    settings.delivery.email.smtp_user = "me@x.com"
    notifiers = build_notifiers(settings, Secrets())
    assert not any(isinstance(n, EmailNotifier) for n in notifiers)
