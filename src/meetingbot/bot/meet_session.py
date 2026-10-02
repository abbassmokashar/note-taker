"""Google Meet join/leave state machine.

The session talks to a small page abstraction (:class:`~meetingbot.bot.meet_selectors.PageLike`)
so its logic is unit-testable without a real browser. ``browser.py`` provides the
Playwright-backed implementation.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from meetingbot.bot import meet_selectors as S
from meetingbot.config import BotConfig

logger = logging.getLogger(__name__)


class SessionState:
    INIT = "INIT"
    NAVIGATING = "NAVIGATING"
    PRE_JOIN = "PRE_JOIN"
    WAITING_ADMIT = "WAITING_ADMIT"
    IN_MEETING = "IN_MEETING"
    LEAVING = "LEAVING"
    ENDED = "ENDED"
    FAILED = "FAILED"


class JoinDeniedError(RuntimeError):
    """The host denied the bot, or the meeting refused the join."""


class JoinTimeoutError(RuntimeError):
    """The bot was never admitted within the configured timeout."""


class MeetingEndedError(RuntimeError):
    """The meeting ended before/while we were joining."""


class Clock:
    """Injectable time source so tests can run without real delays."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass
class SessionHooks:
    on_state: Callable[[str], None] | None = None
    on_joined: Callable[[], None] | None = None
    on_left: Callable[[], None] | None = None
    should_stop: Callable[[], bool] | None = None


class MeetSession:
    """Join a Meet URL, announce, wait for the end, then leave."""

    def __init__(
        self,
        config: BotConfig,
        page: S.PageLike,
        *,
        hooks: SessionHooks | None = None,
        clock: Clock | None = None,
        debug_dir: Path | None = None,
        poll_seconds: float = 5.0,
    ) -> None:
        self.config = config
        self.page = page
        self.hooks = hooks or SessionHooks()
        self.clock = clock or Clock()
        self.debug_dir = debug_dir
        self.poll_seconds = poll_seconds
        self.state = SessionState.INIT
        self._alone_since: float | None = None

    # --- helpers -------------------------------------------------------
    def _set_state(self, state: str) -> None:
        logger.info("Meet session state -> %s", state)
        self.state = state
        if self.hooks.on_state:
            self.hooks.on_state(state)

    def _first(self, spec: S.Selector):
        return S.resolve(self.page, spec)

    def _present(self, spec: S.Selector) -> bool:
        return self._first(spec) is not None

    def _all(self, spec: S.Selector) -> list:
        return S.resolve_all(self.page, spec)

    def _click(self, spec: S.Selector) -> bool:
        element = self._first(spec)
        if element is None:
            return False
        try:
            element.click()
        except Exception as exc:  # noqa: BLE001 - clicks fail if the pane closes
            logger.debug("Click on %s failed: %s", spec.name, exc)
            return False
        return True

    # --- main flow -----------------------------------------------------
    def run(self, url: str, title: str = "") -> str:
        logger.info("Joining meeting: %s", url)
        try:
            self._set_state(SessionState.NAVIGATING)
            self.page.goto(url)

            self._set_state(SessionState.PRE_JOIN)
            self._dismiss_popups()
            joined = self._pre_join()

            if not joined:
                self._set_state(SessionState.WAITING_ADMIT)
                self._wait_to_be_admitted()

            self._set_state(SessionState.IN_MEETING)
            if self.hooks.on_joined:
                self.hooks.on_joined()
            self._announce()
            self._monitor_until_end()
        except Exception:  # noqa: BLE001 - capture debug art, then re-raise
            self._capture_debug("failure")
            self._set_state(SessionState.FAILED)
            raise

        self._set_state(SessionState.LEAVING)
        self._click(S.LEAVE_BUTTON)
        if self.hooks.on_left:
            self.hooks.on_left()
        self._set_state(SessionState.ENDED)
        return self.state

    # --- pre-join ------------------------------------------------------
    def _dismiss_popups(self) -> None:
        for _ in range(4):
            if not self._click(S.DISMISS_BUTTONS):
                break
            self.clock.sleep(0.2)

    def _pre_join(self) -> bool:
        self._set_display_name()
        self._mute_mic_and_camera()

        clicked = self._click(S.JOIN_NOW_BUTTON) or self._click(S.ASK_TO_JOIN_BUTTON)
        if not clicked:
            # Some UIs require pressing Enter in the name field.
            field = self._first(S.NAME_INPUT)
            if field is not None:
                try:
                    field.press("Enter")
                    clicked = True
                except Exception:  # noqa: BLE001
                    clicked = False
        if not clicked:
            raise JoinDeniedError(
                "Could not find a Join button. Meet's UI may have changed — "
                "check meet_selectors.py."
            )
        self.clock.sleep(1.0)
        # Admitted immediately if the leave button is already visible.
        return self._present(S.LEAVE_BUTTON)

    def _set_display_name(self) -> None:
        name = self.config.display_name
        field = self._first(S.NAME_INPUT)
        if field is None or not name:
            return
        try:
            field.fill(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not set display name: %s", exc)

    def _mute_mic_and_camera(self) -> None:
        # MIC_BUTTON_ON present == mic is currently on -> click to turn it off.
        self._click(S.MIC_BUTTON_ON)
        self._click(S.CAM_BUTTON_ON)

    # --- waiting room --------------------------------------------------
    def _wait_to_be_admitted(self) -> None:
        deadline = self.clock.now() + self.config.waiting_room_timeout_minutes * 60
        while True:
            if self._present(S.LEAVE_BUTTON):
                logger.info("Admitted to the meeting.")
                return
            if self._present(S.DENIED_INDICATORS):
                raise JoinDeniedError("The host denied the bot, or the meeting refused the join.")
            if self._present(S.MEETING_ENDED):
                raise MeetingEndedError("The meeting ended while waiting to be admitted.")
            if self.clock.now() >= deadline:
                raise JoinTimeoutError(
                    f"Not admitted within {self.config.waiting_room_timeout_minutes} minutes."
                )
            self.clock.sleep(self.poll_seconds)

    # --- in-meeting ----------------------------------------------------
    def _announce(self) -> None:
        if not self.config.announce_in_chat:
            return
        messages = [
            m for m in (self.config.announcement_en, self.config.announcement_ar) if m.strip()
        ]
        if not messages:
            return
        if not self._click(S.CHAT_BUTTON):
            logger.warning("Could not open chat to post the announcement.")
            return
        self.clock.sleep(1.0)
        for message in messages:
            self._send_chat(message)

    def _send_chat(self, message: str) -> None:
        field = self._first(S.CHAT_INPUT)
        if field is None:
            logger.warning("Could not find the chat input to post the announcement.")
            return
        try:
            field.fill(message)
            if not self._click(S.CHAT_SEND_BUTTON):
                field.press("Enter")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not post the chat announcement: %s", exc)

    def _participant_count(self) -> int:
        items = self._all(S.PARTICIPANT_ITEMS)
        return len(items) if items else 1

    def _monitor_until_end(self) -> None:
        started = self.clock.now()
        alone_limit = self.config.leave_when_alone_after_seconds
        max_seconds = self.config.max_meeting_hours * 3600
        self._alone_since = None

        while True:
            if self._present(S.MEETING_ENDED) or not self._present(S.LEAVE_BUTTON):
                logger.info("Meeting ended or the bot was removed.")
                return
            if self.clock.now() - started >= max_seconds:
                logger.info("Reached max_meeting_hours; leaving.")
                return
            if self.hooks.should_stop and self.hooks.should_stop():
                logger.info("Stop requested externally; leaving.")
                return

            if self._participant_count() <= 1:
                if self._alone_since is None:
                    self._alone_since = self.clock.now()
                elif self.clock.now() - self._alone_since >= alone_limit:
                    logger.info("Alone for %ss; leaving.", alone_limit)
                    return
            else:
                self._alone_since = None

            self.clock.sleep(self.poll_seconds)

    # --- debug ---------------------------------------------------------
    def _capture_debug(self, reason: str) -> None:
        if self.debug_dir is None:
            return
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            screenshot = getattr(self.page, "screenshot", None)
            if callable(screenshot):
                screenshot(str(self.debug_dir / f"{reason}.png"))
            content = getattr(self.page, "content", None)
            if callable(content):
                (self.debug_dir / f"{reason}.html").write_text(
                    content(), encoding="utf-8"
                )
        except Exception as exc:  # noqa: BLE001 - debug capture must never mask the error
            logger.debug("Debug capture failed: %s", exc)
