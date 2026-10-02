from __future__ import annotations

import datetime as dt

from meetingbot.config import Settings
from meetingbot.scheduler.calendar_watcher import (
    CalendarWatcher,
    GoogleCalendarClient,
    parse_google_event,
)


def test_parse_datetime_event() -> None:
    item = {
        "id": "e1",
        "summary": "Sync",
        "start": {"dateTime": "2026-10-02T09:00:00+03:00"},
        "end": {"dateTime": "2026-10-02T10:00:00+03:00"},
        "hangoutLink": "https://meet.google.com/abc-defg-hij",
        "status": "confirmed",
    }
    event = parse_google_event(item)
    assert event.id == "e1"
    assert event.all_day is False
    assert event.meet_link == "https://meet.google.com/abc-defg-hij"
    assert event.start.tzinfo is not None


def test_parse_all_day_event() -> None:
    item = {"id": "e2", "summary": "Holiday", "start": {"date": "2026-10-02"}}
    event = parse_google_event(item)
    assert event.all_day is True


def test_parse_conference_entrypoint() -> None:
    item = {
        "id": "e3",
        "start": {"dateTime": "2026-10-02T09:00:00Z"},
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+1"},
                {"entryPointType": "video", "uri": "https://meet.google.com/zzz-yyyy-xxx"},
            ]
        },
    }
    event = parse_google_event(item)
    assert event.meet_link == "https://meet.google.com/zzz-yyyy-xxx"


class FakeClient:
    def __init__(self, events, on_add=None):
        self.events = events
        self.added: list[tuple[str, str]] = []
        self.on_add = on_add

    def list_events(self, time_min, time_max):
        return list(self.events)

    def add_attendee(self, event_id, email):
        self.added.append((event_id, email))
        if self.on_add:
            self.on_add(event_id, email)


def _settings(tmp_path, **overrides) -> Settings:
    settings = Settings(data_dir=tmp_path)
    settings.calendar.auto_invite = overrides.get("auto_invite", False)
    settings.bot.account_email = overrides.get("account_email", "bot@example.com")
    return settings


def test_joinable_filters_by_meet_link(tmp_path) -> None:
    from meetingbot.scheduler.rules import CalendarEvent

    with_link = CalendarEvent(id="a", summary="A", hangout_link="https://meet.google.com/abc-defg-hij")
    without = CalendarEvent(id="b", summary="B")
    watcher = CalendarWatcher(FakeClient([with_link, without]), _settings(tmp_path))
    joinable = watcher.joinable()
    assert [e.id for e, _ in joinable] == ["a"]


def test_invite_bot_only_when_organizer(tmp_path) -> None:
    from meetingbot.scheduler.rules import CalendarEvent

    organizer = CalendarEvent(
        id="a",
        summary="Mine",
        hangout_link="https://meet.google.com/abc-defg-hij",
        attendees=[{"email": "me@x.com", "self": True, "organizer": True}],
    )
    guest = CalendarEvent(
        id="b",
        summary="Theirs",
        hangout_link="https://meet.google.com/zzz-yyyy-xxx",
        attendees=[{"email": "me@x.com", "self": True}],
    )
    client = FakeClient([])
    watcher = CalendarWatcher(client, _settings(tmp_path, auto_invite=True))
    count = watcher.invite_bot([organizer, guest])
    assert count == 1
    assert client.added == [("a", "bot@example.com")]


def test_invite_bot_disabled(tmp_path) -> None:
    from meetingbot.scheduler.rules import CalendarEvent

    event = CalendarEvent(
        id="a",
        summary="Mine",
        hangout_link="https://meet.google.com/abc-defg-hij",
        attendees=[{"self": True, "organizer": True}],
    )
    client = FakeClient([])
    watcher = CalendarWatcher(client, _settings(tmp_path, auto_invite=False))
    assert watcher.invite_bot([event]) == 0
    assert client.added == []


def test_window_uses_lookahead(tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.calendar.lookahead_hours = 5
    watcher = CalendarWatcher(FakeClient([]), settings)
    now = dt.datetime(2026, 10, 2, 0, 0, tzinfo=dt.UTC)
    start, end = watcher.window(now)
    assert (end - start) == dt.timedelta(hours=5)


def test_google_client_list_events_shapes_params() -> None:
    captured = {}

    class Service:
        def events(self):
            return self

        def list(self, **kwargs):
            captured.update(kwargs)
            return self

        def execute(self):
            return {"items": [{"id": "x", "start": {"dateTime": "2026-10-02T09:00:00Z"}}]}

    client = GoogleCalendarClient(Service())
    now = dt.datetime(2026, 10, 2, 0, 0, tzinfo=dt.UTC)
    events = client.list_events(now, now + dt.timedelta(hours=1))
    assert events[0].id == "x"
    assert captured["calendarId"] == "primary"
    assert captured["singleEvents"] is True
