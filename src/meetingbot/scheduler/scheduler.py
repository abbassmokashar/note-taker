"""The scheduler: turn calendar events into meeting jobs and run bot workers.

``sync_jobs`` is pure-ish (DB + a calendar client) and unit-testable with a fake
client. ``run_forever`` polls and spawns join workers, bounded by
``calendar.max_concurrent_bots``.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from meetingbot.config import Settings
from meetingbot.db import (
    Meeting,
    MeetingStatus,
    create_db_engine,
    init_db,
    make_session_factory,
)
from meetingbot.pipeline.runner import new_meeting_id
from meetingbot.scheduler.calendar_watcher import CalendarWatcher
from meetingbot.scheduler.rules import CalendarEvent

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {MeetingStatus.SCHEDULED, MeetingStatus.JOINING, MeetingStatus.RECORDING}


def _naive_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    return value


@dataclass
class SyncResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    invited: int = 0

    def __str__(self) -> str:  # pragma: no cover - logging helper
        return (
            f"created={len(self.created)} updated={len(self.updated)} "
            f"skipped={len(self.skipped)} invited={self.invited}"
        )


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        watcher: CalendarWatcher,
        session_factory: sessionmaker[Session] | None = None,
        *,
        join_func=None,
    ) -> None:
        self.settings = settings
        self.watcher = watcher
        if session_factory is None:
            engine = create_db_engine(settings.db_path)
            init_db(engine)
            session_factory = make_session_factory(engine)
        self.session_factory = session_factory
        self._join_func = join_func
        self._stop = threading.Event()

    # --- job synchronization ------------------------------------------
    def sync_jobs(self, now: dt.datetime | None = None) -> SyncResult:
        result = SyncResult()
        now = now or dt.datetime.now(dt.UTC)
        joinable = self.watcher.joinable(now)
        wanted = {event.id: event for event, _ in joinable}

        with self.session_factory() as session:
            for event_id, event in wanted.items():
                existing = (
                    session.query(Meeting)
                    .filter(Meeting.calendar_event_id == event_id)
                    .one_or_none()
                )
                if existing is None:
                    meeting_id = new_meeting_id(event.summary or "Meeting", event.start)
                    session.add(
                        Meeting(
                            id=meeting_id,
                            calendar_event_id=event_id,
                            title=event.summary,
                            meet_url=event.meet_link,
                            scheduled_start=_naive_utc(event.start),
                            scheduled_end=_naive_utc(event.end),
                            status=MeetingStatus.SCHEDULED,
                        )
                    )
                    _set_attendees(session, meeting_id, event)
                    result.created.append(meeting_id)
                elif existing.status == MeetingStatus.SCHEDULED:
                    existing.title = event.summary
                    existing.meet_url = event.meet_link
                    existing.scheduled_start = _naive_utc(event.start)
                    existing.scheduled_end = _naive_utc(event.end)
                    _set_attendees(session, existing.id, event)
                    result.updated.append(existing.id)

            # Cancel jobs whose events are gone or no longer joinable.
            for meeting in (
                session.query(Meeting)
                .filter(Meeting.status == MeetingStatus.SCHEDULED)
                .filter(Meeting.calendar_event_id.isnot(None))
                .all()
            ):
                if meeting.calendar_event_id not in wanted:
                    meeting.status = MeetingStatus.SKIPPED
                    meeting.error = "event removed or no longer joinable"
                    result.skipped.append(meeting.id)
            session.commit()

        result.invited = self.watcher.invite_bot(list(wanted.values()))
        logger.info("Calendar sync: %s", result)
        return result

    def due_meetings(self, now: dt.datetime | None = None) -> list[Meeting]:
        """Scheduled meetings whose start time is within join_early_seconds."""
        now = now or dt.datetime.now(dt.UTC)
        threshold = (now + dt.timedelta(seconds=self.settings.bot.join_early_seconds)).replace(
            tzinfo=None
        )
        with self.session_factory() as session:
            return (
                session.query(Meeting)
                .filter(Meeting.status == MeetingStatus.SCHEDULED)
                .filter(Meeting.scheduled_start.isnot(None))
                .filter(Meeting.scheduled_start <= threshold)
                .all()
            )

    # --- workers -------------------------------------------------------
    def _join(self, meeting: Meeting) -> None:
        if self._join_func is None:
            from meetingbot.bot.joiner import join_meeting

            self._join_func = join_meeting
        try:
            logger.info("Joining meeting %s (%s)", meeting.id, meeting.title)
            self._join_func(self.settings, meeting.meet_url, meeting.title)
        except Exception:  # noqa: BLE001 - a failed join must not stop the scheduler
            logger.exception("Join worker failed for %s", meeting.id)

    def poll_once(self, now: dt.datetime | None = None) -> list[Meeting]:
        """Sync jobs and return the ones that are due to start now."""
        self.sync_jobs(now)
        return self.due_meetings(now)

    def run_forever(self, *, max_iterations: int | None = None) -> None:
        max_workers = self.settings.calendar.max_concurrent_bots
        interval = self.settings.calendar.poll_seconds
        iterations = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            while not self._stop.is_set():
                try:
                    due = self.poll_once()
                except Exception:  # noqa: BLE001 - keep the scheduler alive
                    logger.exception("Scheduler poll failed")
                    due = []
                for meeting in due:
                    # Mark as joining immediately so it is not picked up twice.
                    with self.session_factory() as session:
                        row = session.get(Meeting, meeting.id)
                        if row is None or row.status != MeetingStatus.SCHEDULED:
                            continue
                        row.status = MeetingStatus.JOINING
                        session.commit()
                        session.refresh(row)
                    pool.submit(self._join, row)

                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()


def _set_attendees(session: Session, meeting_id: str, event: CalendarEvent) -> None:
    meeting = session.get(Meeting, meeting_id)
    if meeting is not None:
        meeting.attendees = event.attendees
