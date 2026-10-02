from __future__ import annotations

from pathlib import Path

from meetingbot.config import Secrets, Settings
from meetingbot.providers.notifiers import (
    EmailNotifier,
    LocalFilesNotifier,
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
