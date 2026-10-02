"""Delivery providers: local files, email, Google Drive."""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from meetingbot.config import Secrets, Settings

logger = logging.getLogger(__name__)


class LocalFilesNotifier:
    """No-op notifier: results are already written to the meeting folder."""

    def notify(
        self, meeting_id: str, subject: str, body: str, attachments: list[Path] | None = None
    ) -> None:
        logger.info("[local] %s: %s (%d attachments)", meeting_id, subject, len(attachments or []))


@dataclass
class SmtpSettings:
    host: str = "smtp.gmail.com"
    port: int = 465
    user: str = ""
    password: str = ""
    to: str = ""


class EmailNotifier:
    """Sends notes + transcript attachments via SMTP (Gmail app password)."""

    def __init__(self, smtp: SmtpSettings) -> None:
        self.smtp = smtp

    def _message(
        self, subject: str, body: str, attachments: list[Path] | None
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.smtp.user
        message["To"] = self.smtp.to
        message["Subject"] = subject
        message.set_content(body)
        for path in attachments or []:
            if not path.exists():
                continue
            data = path.read_bytes()
            if path.suffix == ".pdf":
                maintype, subtype = "application", "pdf"
            elif path.suffix in (".md", ".txt"):
                maintype, subtype = "text", "markdown"
            else:
                maintype, subtype = "application", "octet-stream"
            message.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)
        return message

    def notify(
        self, meeting_id: str, subject: str, body: str, attachments: list[Path] | None = None
    ) -> None:
        message = self._message(subject, body, attachments)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.smtp.host, self.smtp.port, context=context) as server:
            if self.smtp.user:
                server.login(self.smtp.user, self.smtp.password)
            server.send_message(message)
        logger.info("Emailed notes for %s to %s", meeting_id, self.smtp.to)


class DriveUploader:
    """Placeholder for Google Drive upload (Phase 6 optional)."""

    def notify(
        self, meeting_id: str, subject: str, body: str, attachments: list[Path] | None = None
    ) -> None:
        logger.warning(
            "Drive upload is not implemented yet; files for %s remain local.", meeting_id
        )


def build_notifiers(settings: Settings, secrets: Secrets) -> list:
    """Return the configured notifiers (local is always included)."""
    notifiers: list = [LocalFilesNotifier()]
    email = settings.delivery.email
    if email.enabled and email.to and email.smtp_user and secrets.smtp_app_password:
        notifiers.append(
            EmailNotifier(
                SmtpSettings(
                    user=email.smtp_user,
                    password=secrets.smtp_app_password,
                    to=email.to,
                )
            )
        )
    elif email.enabled:
        logger.warning(
            "Email delivery is enabled but incomplete (need to, smtp_user, SMTP_APP_PASSWORD)."
        )
    if settings.delivery.drive.enabled:
        notifiers.append(DriveUploader())
    return notifiers
