"""Join rules and event parsing.

Pure functions so the decision logic is unit-testable without any Google API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from meetingbot.config import JoinRules

_MEET_LINK_RE = re.compile(r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}")


@dataclass
class CalendarEvent:
    """A normalized calendar event."""

    id: str
    summary: str = ""
    description: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    hangout_link: str | None = None
    status: str = "confirmed"
    attendees: list[dict] = field(default_factory=list)

    @property
    def meet_link(self) -> str | None:
        if self.hangout_link:
            return self.hangout_link
        match = _MEET_LINK_RE.search(self.description or "")
        return match.group(0) if match else None

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def self_declined(self) -> bool:
        for attendee in self.attendees:
            if attendee.get("self") and attendee.get("responseStatus") == "declined":
                return True
        return False

    @property
    def self_is_organizer(self) -> bool:
        for attendee in self.attendees:
            if attendee.get("self") and attendee.get("organizer"):
                return True
        return False


def extract_meet_link(event: CalendarEvent) -> str | None:
    return event.meet_link


def should_join(event: CalendarEvent, rules: JoinRules) -> tuple[bool, str]:
    """Decide whether the bot should join ``event``. Returns (join, reason)."""
    if event.cancelled:
        return False, "event is cancelled"
    if not event.meet_link:
        return False, "no Google Meet link"

    haystack = f"{event.summary}\n{event.description}".lower()
    if rules.skip_tag and rules.skip_tag.lower() in haystack:
        return False, f"contains opt-out tag {rules.skip_tag}"

    if event.all_day and rules.skip_all_day:
        return False, "all-day event"

    if rules.skip_if_declined and event.self_declined:
        return False, "you declined this event"

    title = (event.summary or "").lower()
    for needle in rules.skip_title_contains:
        if needle and needle.lower() in title:
            return False, f"title contains '{needle}'"

    if rules.default == "skip":
        return False, "join rules default is skip"
    return True, "join rules matched"
