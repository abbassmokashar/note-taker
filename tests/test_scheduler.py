from __future__ import annotations

import datetime as dt

from meetingbot.config import Settings
from meetingbot.db import Meeting, MeetingStatus
from meetingbot.scheduler.calendar_watcher import CalendarWatcher
from meetingbot.scheduler.rules import CalendarEvent
from meetingbot.scheduler.scheduler import Scheduler

NOW = dt.datetime(2026, 10, 2, 8, 0, tzinfo=dt.UTC)


class FakeClient:
    def __init__(self, events=None):
        self.events = events or []
        self.added = []

    def list_events(self, time_min, time_max):
        return list(self.events)

    def add_attendee(self, event_id, email):
        self.added.append((event_id, email))


def _event(event_id="e1", minutes=10, summary="Weekly Sync") -> CalendarEvent:
    start = NOW + dt.timedelta(minutes=minutes)
    return CalendarEvent(
        id=event_id,
        summary=summary,
        start=start,
        end=start + dt.timedelta(hours=1),
        hangout_link="https://meet.google.com/abc-defg-hij",
    )


def _make(tmp_path, events):
    settings = Settings(data_dir=tmp_path)
    settings.calendar.join_rules.skip_title_contains = []
    client = FakeClient(events)
    watcher = CalendarWatcher(client, settings)
    return settings, client, watcher


def test_sync_creates_job(tmp_path) -> None:
    settings, _, watcher = _make(tmp_path, [_event()])
    sf = joiner_session(tmp_path)
    scheduler = Scheduler(settings, watcher, sf)
    result = scheduler.sync_jobs(NOW)
    assert len(result.created) == 1

    with sf() as session:
        rows = session.query(Meeting).all()
        assert len(rows) == 1
        assert rows[0].status == MeetingStatus.SCHEDULED
        assert rows[0].calendar_event_id == "e1"
        assert rows[0].meet_url.endswith("abc-defg-hij")


def test_sync_is_idempotent(tmp_path) -> None:
    settings, _, watcher = _make(tmp_path, [_event()])
    sf = joiner_session(tmp_path)
    scheduler = Scheduler(settings, watcher, sf)
    scheduler.sync_jobs(NOW)
    result2 = scheduler.sync_jobs(NOW)
    assert result2.created == []
    assert len(result2.updated) == 1
    with sf() as session:
        assert session.query(Meeting).count() == 1


def test_sync_skips_removed_event(tmp_path) -> None:
    settings, client, watcher = _make(tmp_path, [_event()])
    sf = joiner_session(tmp_path)
    scheduler = Scheduler(settings, watcher, sf)
    scheduler.sync_jobs(NOW)

    client.events = []  # the event disappeared
    result = scheduler.sync_jobs(NOW)
    assert len(result.skipped) == 1
    with sf() as session:
        assert session.query(Meeting).one().status == MeetingStatus.SKIPPED


def test_sync_ignores_no_meet_link(tmp_path) -> None:
    event = CalendarEvent(id="e9", summary="No link", start=NOW)
    settings, _, watcher = _make(tmp_path, [event])
    sf = joiner_session(tmp_path)
    result = Scheduler(settings, watcher, sf).sync_jobs(NOW)
    assert result.created == []


def test_due_meetings_respects_join_early(tmp_path) -> None:
    settings, _, watcher = _make(tmp_path, [_event(minutes=10)])
    settings.bot.join_early_seconds = 30
    sf = joiner_session(tmp_path)
    scheduler = Scheduler(settings, watcher, sf)
    scheduler.sync_jobs(NOW)

    # 10 minutes away is not due yet with a 30s lead.
    assert scheduler.due_meetings(NOW) == []
    # At 9m30s later it is within the lead window.
    later = NOW + dt.timedelta(minutes=9, seconds=35)
    assert len(scheduler.due_meetings(later)) == 1


def test_poll_once_returns_due(tmp_path) -> None:
    settings, _, watcher = _make(tmp_path, [_event(minutes=0)])
    sf = joiner_session(tmp_path)
    scheduler = Scheduler(settings, watcher, sf)
    due = scheduler.poll_once(NOW)
    assert len(due) == 1


def test_auto_invite_called_on_sync(tmp_path) -> None:
    event = _event()
    event.attendees = [{"email": "me@x.com", "self": True, "organizer": True}]
    settings, client, watcher = _make(tmp_path, [event])
    settings.calendar.auto_invite = True
    settings.bot.account_email = "bot@example.com"
    sf = joiner_session(tmp_path)
    result = Scheduler(settings, watcher, sf).sync_jobs(NOW)
    assert result.invited == 1
    assert client.added == [("e1", "bot@example.com")]


# --- helper -----------------------------------------------------------
def joiner_session(tmp_path):
    from meetingbot.db import create_db_engine, init_db, make_session_factory

    engine = create_db_engine(tmp_path / "meetingbot.db")
    init_db(engine)
    return make_session_factory(engine)
