from __future__ import annotations

import datetime as dt

from meetingbot.config import JoinRules
from meetingbot.scheduler.rules import CalendarEvent, extract_meet_link, should_join


def _event(**overrides) -> CalendarEvent:
    defaults = dict(
        id="e1",
        summary="Weekly sync",
        description="",
        start=dt.datetime(2026, 10, 2, 9, 0),
        end=dt.datetime(2026, 10, 2, 10, 0),
        hangout_link="https://meet.google.com/abc-defg-hij",
    )
    defaults.update(overrides)
    return CalendarEvent(**defaults)


def test_joins_normal_event() -> None:
    join, reason = should_join(_event(), JoinRules())
    assert join is True
    assert "matched" in reason


def test_skips_without_meet_link() -> None:
    join, reason = should_join(_event(hangout_link=None), JoinRules())
    assert join is False
    assert "Meet link" in reason


def test_extracts_meet_link_from_description() -> None:
    event = _event(
        hangout_link=None,
        description="Join here: https://meet.google.com/xyz-abcd-efg thanks",
    )
    assert extract_meet_link(event) == "https://meet.google.com/xyz-abcd-efg"


def test_skips_cancelled() -> None:
    join, reason = should_join(_event(status="cancelled"), JoinRules())
    assert join is False
    assert "cancelled" in reason


def test_skips_opt_out_tag() -> None:
    join, reason = should_join(_event(description="please #nobot"), JoinRules())
    assert join is False
    assert "#nobot" in reason


def test_skips_all_day() -> None:
    join, reason = should_join(_event(all_day=True), JoinRules())
    assert join is False
    assert "all-day" in reason


def test_skips_declined() -> None:
    event = _event(attendees=[{"self": True, "responseStatus": "declined"}])
    join, reason = should_join(event, JoinRules())
    assert join is False
    assert "declined" in reason


def test_skips_title_contains() -> None:
    join, reason = should_join(_event(summary="Team lunch"), JoinRules())
    assert join is False
    assert "lunch" in reason


def test_default_skip() -> None:
    join, reason = should_join(_event(), JoinRules(default="skip"))
    assert join is False
    assert "default" in reason


def test_self_is_organizer() -> None:
    assert _event(attendees=[{"self": True, "organizer": True}]).self_is_organizer is True
    assert _event(attendees=[{"self": True}]).self_is_organizer is False
