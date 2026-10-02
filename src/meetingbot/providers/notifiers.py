"""Delivery providers: local files, email, Google Drive."""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from meetingbot.config import S3Config, Secrets, Settings

# Extensions small/safe enough to attach to email (never the recording).
EMAIL_ATTACH_SUFFIXES = {".md", ".txt", ".srt", ".vtt", ".json", ".pdf"}

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
            if not path.exists() or path.suffix not in EMAIL_ATTACH_SUFFIXES:
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


class S3Uploader:
    """Uploads a meeting's files to any S3-compatible store.

    Works with Cloudflare R2, Backblaze B2, MinIO, and AWS S3 (all support the
    S3 API). ``client_factory`` is injectable for tests.
    """

    def __init__(
        self,
        cfg: S3Config,
        access_key_id: str | None,
        secret_access_key: str | None,
        *,
        client_factory=None,
    ) -> None:
        self.cfg = cfg
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self._client_factory = client_factory
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory()
            return self._client
        try:
            import boto3  # lazy: optional dependency
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "boto3 is required for S3 upload. Install it with: pip install boto3"
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self.cfg.endpoint_url or None,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.cfg.region or "auto",
        )
        return self._client

    def object_key(self, meeting_id: str, filename: str) -> str:
        prefix = self.cfg.prefix.strip("/")
        return f"{prefix}/{meeting_id}/{filename}" if prefix else f"{meeting_id}/{filename}"

    def notify(
        self, meeting_id: str, subject: str, body: str, attachments: list[Path] | None = None
    ) -> None:
        client = self._get_client()
        uploaded = 0
        for path in attachments or []:
            if not path.exists():
                continue
            key = self.object_key(meeting_id, path.name)
            client.upload_file(str(path), self.cfg.bucket, key)
            uploaded += 1
        logger.info("Uploaded %d file(s) for %s to s3://%s", uploaded, meeting_id, self.cfg.bucket)


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

    s3 = settings.delivery.s3
    if s3.enabled:
        import os

        access = os.environ.get(s3.access_key_env) or secrets.s3_access_key_id
        secret = os.environ.get(s3.secret_key_env) or secrets.s3_secret_access_key
        if access and secret:
            notifiers.append(S3Uploader(s3, access, secret))
        else:
            logger.warning(
                "S3 delivery is enabled but %s / %s are not set.",
                s3.access_key_env,
                s3.secret_key_env,
            )
    return notifiers
