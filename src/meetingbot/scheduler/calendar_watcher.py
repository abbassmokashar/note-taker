"""Calendar event fetching and normalization.

The Google API call sits behind :class:`CalendarClient` so the watcher can be tested
with a fake client and no network access.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Protocol

from meetingbot.config import Settings
from meetingbot.scheduler.rules import CalendarEvent, should_join

logger = logging.getLogger(__name__)


class CalendarClient(Protocol):
    def list_events(self, time_min: dt.datetime, time_max: dt.datetime) -> list[CalendarEvent]:
        ...

    def add_attendee(self, event_id: str, email: str) -> None:  # pragma: no cover
        ...


def _parse_dt(value: dict | None) -> tuple[dt.datetime | None, bool]:
    """Return (datetime, all_day) for a Google start/end object."""
    if not value:
        return None, False
    if "dateTime" in value:
        return dt.datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")), False
    if "date" in value:
        return dt.datetime.fromisoformat(value["date"]), True
    return None, False


def parse_google_event(item: dict) -> CalendarEvent:
    start, all_day = _parse_dt(item.get("start"))
    end, _ = _parse_dt(item.get("end"))
    conference = item.get("conferenceData") or {}
    hangout = item.get("hangoutLink")
    if not hangout:
        for entry in conference.get("entryPoints", []) or []:
            if entry.get("entryPointType") == "video" and entry.get("uri"):
                hangout = entry["uri"]
                break
    return CalendarEvent(
        id=item.get("id", ""),
        summary=item.get("summary", "") or "",
        description=item.get("description", "") or "",
        start=start,
        end=end,
        all_day=all_day,
        hangout_link=hangout,
        status=item.get("status", "confirmed"),
        attendees=list(item.get("attendees", []) or []),
    )


class GoogleCalendarClient:
    """Real client backed by an authenticated googleapiclient service."""

    def __init__(self, service) -> None:
        self.service = service

    def list_events(
        self, time_min: dt.datetime, time_max: dt.datetime
    ) -> list[CalendarEvent]:
        response = (
            self.service.events()
            .list(
                calendarId="primary",
                timeMin=time_min.astimezone(dt.UTC).isoformat(),
                timeMax=time_max.astimezone(dt.UTC).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )
        return [parse_google_event(item) for item in response.get("items", [])]

    def add_attendee(self, event_id: str, email: str) -> None:
        event = self.service.events().get(calendarId="primary", eventId=event_id).execute()
        attendees = event.get("attendees", []) or []
        if any(a.get("email", "").lower() == email.lower() for a in attendees):
            logger.info("Bot %s already invited to %s", email, event_id)
            return
        attendees.append({"email": email})
        self.service.events().patch(
            calendarId="primary",
            eventId=event_id,
            body={"attendees": attendees},
            sendUpdates="none",
        ).execute()
        logger.info("Added %s as a guest to event %s", email, event_id)


class CalendarWatcher:
    """Fetches upcoming events and applies join rules / auto-invite."""

    def __init__(self, client: CalendarClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    def window(self, now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
        now = now or dt.datetime.now(dt.UTC)
        return now, now + dt.timedelta(hours=self.settings.calendar.lookahead_hours)

    def upcoming(self, now: dt.datetime | None = None) -> list[CalendarEvent]:
        time_min, time_max = self.window(now)
        return self.client.list_events(time_min, time_max)

    def joinable(
        self, now: dt.datetime | None = None
    ) -> list[tuple[CalendarEvent, str]]:
        """Return (event, reason) pairs the bot should join."""
        cfg = self.settings.calendar
        results: list[tuple[CalendarEvent, str]] = []
        for event in self.upcoming(now):
            if cfg.only_events_with_meet_link and not event.meet_link:
                continue
            join, reason = should_join(event, cfg.join_rules)
            if join:
                results.append((event, reason))
            else:
                logger.debug("Skipping '%s': %s", event.summary, reason)
        return results

    def invite_bot(self, events: list[CalendarEvent]) -> int:
        """Add the bot as a guest to each event (auto_invite mode). Returns count."""
        if not self.settings.calendar.auto_invite:
            return 0
        email = self.settings.bot.account_email
        if not email:
            logger.warning("calendar.auto_invite is on but bot.account_email is empty.")
            return 0
        invited = 0
        for event in events:
            # Only events you organize can be modified; others use "Ask to join".
            if not event.self_is_organizer:
                logger.debug("Not inviting bot to %s (you are not the organizer)", event.id)
                continue
            try:
                self.client.add_attendee(event.id, email)
                invited += 1
            except Exception as exc:  # noqa: BLE001 - a failed invite must not stop the poll
                logger.warning("Could not invite the bot to %s: %s", event.id, exc)
        return invited
