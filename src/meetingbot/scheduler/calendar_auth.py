"""Google Calendar OAuth (free Desktop client) and service construction.

Scopes:
  - ``calendar.readonly``  always.
  - ``calendar.events``    only when ``calendar.auto_invite`` is enabled, so the bot
    can add itself as a guest to events you organize.
"""

from __future__ import annotations

import logging
from pathlib import Path

from meetingbot.config import Settings

logger = logging.getLogger(__name__)

SCOPE_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
SCOPE_EVENTS = "https://www.googleapis.com/auth/calendar.events"


class CalendarAuthError(RuntimeError):
    """Raised when credentials are missing or the OAuth flow cannot run."""


def scopes_for(settings: Settings) -> list[str]:
    scopes = [SCOPE_READONLY]
    if settings.calendar.auto_invite:
        scopes.append(SCOPE_EVENTS)
    return scopes


def credentials_path(settings: Settings) -> Path:
    return settings.data_dir / "credentials.json"


def token_path(settings: Settings) -> Path:
    return settings.data_dir / "token.json"


def build_service(settings: Settings, *, service_name: str = "calendar", version: str = "v3"):
    """Build an authenticated Google API service, refreshing the token if needed."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise CalendarAuthError(
            "Google API libraries are not installed. Install them with: "
            "pip install 'meetingbot[calendar]'"
        ) from exc

    token = token_path(settings)
    if not token.exists():
        raise CalendarAuthError(
            f"No token found at {token}. Run `meetingbot auth calendar` first."
        )

    creds = Credentials.from_authorized_user_file(str(token), scopes_for(settings))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise CalendarAuthError(
                "Stored credentials are invalid. Re-run `meetingbot auth calendar`."
            )
    return build(service_name, version, credentials=creds, cache_discovery=False)


def run_oauth_flow(settings: Settings) -> Path:
    """Run the desktop OAuth flow and write the token file. Returns the token path."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise CalendarAuthError(
            "google-auth-oauthlib is not installed. Install: pip install 'meetingbot[calendar]'"
        ) from exc

    creds_file = credentials_path(settings)
    if not creds_file.exists():
        raise CalendarAuthError(
            f"Missing {creds_file}. Download the OAuth Desktop client JSON from Google "
            "Cloud Console and save it there (see docs/SETUP.md)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), scopes_for(settings))
    creds = flow.run_local_server(port=0)
    token = token_path(settings)
    token.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Saved Google credentials to %s", token)
    return token
