from __future__ import annotations

from pathlib import Path

import pytest

from meetingbot.bot.meet_session import (
    JoinDeniedError,
    JoinTimeoutError,
    MeetSession,
    SessionHooks,
    SessionState,
)
from meetingbot.config import BotConfig
from tests.conftest import FakeClock, FakePage

JOIN = 'text="Join now"'
ASK = 'text="Ask to join"'
LEAVE = '[aria-label="Leave call"]'
DENIED = 'text="Your request to join was denied"'
ENDED = 'text="You left the meeting"'
CHAT_BUTTON = '[aria-label="Chat with everyone"]'
CHAT_INPUT = 'textarea[aria-label*="message"]'
CHAT_SEND = '[aria-label="Send a message"]'


def _config(**overrides) -> BotConfig:
    defaults = dict(
        display_name="Notetaker (recording)",
        waiting_room_timeout_minutes=1,
        leave_when_alone_after_seconds=120,
        announce_in_chat=True,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def test_happy_path_joins_announces_and_leaves(tmp_path: Path) -> None:
    page = FakePage(present={JOIN, CHAT_BUTTON, CHAT_INPUT, CHAT_SEND})
    page.counts['[data-participant-id]'] = 3
    ticks = {"n": 0}

    def on_sleep() -> None:
        if ticks["n"] == 0:
            page.present.add(LEAVE)  # admitted after clicking join
        elif ticks["n"] >= 1:
            page.present.add(ENDED)
        ticks["n"] += 1

    states: list[str] = []
    session = MeetSession(
        _config(),
        page,
        hooks=SessionHooks(on_state=states.append),
        clock=FakeClock(on_sleep=on_sleep),
        poll_seconds=1.0,
    )
    final = session.run("https://meet.google.com/abc-defg-hij", "Test")

    assert final == SessionState.ENDED
    assert page.goto_url == "https://meet.google.com/abc-defg-hij"
    assert page.element(CHAT_INPUT).fills[0].startswith("Hi, I'm an automated notetaker")
    assert len(page.element(CHAT_INPUT).fills) == 2  # EN + AR
    assert page.element(LEAVE).click_count >= 1
    assert SessionState.IN_MEETING in states


def test_denied_marks_failed_and_screenshots(tmp_path: Path) -> None:
    page = FakePage(present={ASK})
    ticks = {"n": 0}

    def on_sleep() -> None:
        if ticks["n"] >= 1:
            page.present.add(DENIED)
        ticks["n"] += 1

    session = MeetSession(
        _config(),
        page,
        clock=FakeClock(on_sleep=on_sleep),
        debug_dir=tmp_path / "debug",
        poll_seconds=1.0,
    )
    with pytest.raises(JoinDeniedError):
        session.run("https://meet.google.com/abc-defg-hij")
    assert session.state == SessionState.FAILED
    assert page.screenshots  # debug artifact captured


def test_waiting_room_timeout() -> None:
    page = FakePage(present={ASK})
    session = MeetSession(
        _config(waiting_room_timeout_minutes=0),
        page,
        clock=FakeClock(),
        poll_seconds=1.0,
    )
    with pytest.raises(JoinTimeoutError):
        session.run("https://meet.google.com/abc-defg-hij")


def test_no_join_button_raises() -> None:
    page = FakePage(present=set())
    session = MeetSession(_config(), page, clock=FakeClock(), poll_seconds=1.0)
    with pytest.raises(JoinDeniedError):
        session.run("https://meet.google.com/abc-defg-hij")


def test_mutes_microphone_before_joining() -> None:
    page = FakePage(present={JOIN, '[aria-label="Turn off microphone"]'})
    page.counts['[data-participant-id]'] = 3

    def on_sleep() -> None:
        page.present.add(LEAVE)
        page.present.add(ENDED)

    session = MeetSession(
        _config(announce_in_chat=False),
        page,
        clock=FakeClock(on_sleep=on_sleep),
        poll_seconds=1.0,
    )
    session.run("https://meet.google.com/abc-defg-hij")
    assert page.element('[aria-label="Turn off microphone"]').click_count == 1
