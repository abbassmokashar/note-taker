"""End-to-end join + record orchestration for one meeting."""

from __future__ import annotations

import json
import logging
import signal
import threading
import time

from sqlalchemy.orm import Session, sessionmaker

from meetingbot.bot.audio_capture import AudioCapture, ensure_null_sink
from meetingbot.bot.browser import open_meet_browser
from meetingbot.bot.caption_logger import CaptionLogger
from meetingbot.bot.health import has_disk_space
from meetingbot.bot.meet_session import MeetSession, SessionHooks
from meetingbot.config import Settings
from meetingbot.db import (
    Meeting,
    MeetingStatus,
    create_db_engine,
    init_db,
    make_session_factory,
    utcnow,
)
from meetingbot.pipeline.runner import meeting_dir, new_meeting_id

logger = logging.getLogger(__name__)


class RecordingRefusedError(RuntimeError):
    """Raised when recording should not start (e.g. low disk, no ffmpeg)."""


def _make_stop_event() -> threading.Event:
    stop = threading.Event()

    def _handler(signum, frame):  # pragma: no cover - signal path
        logger.info("Received signal %s; leaving the meeting gracefully.", signum)
        stop.set()

    try:
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):  # not in the main thread
        pass
    return stop


def join_meeting(
    settings: Settings,
    url: str,
    title: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    record_video: bool | None = None,
    process_after: bool = False,
) -> Meeting:
    """Join a Meet URL, record it, and (optionally) run the pipeline."""
    if session_factory is None:
        engine = create_db_engine(settings.db_path)
        init_db(engine)
        session_factory = make_session_factory(engine)
    settings.ensure_dirs()

    meeting_id = new_meeting_id(title)
    folder = meeting_dir(settings, meeting_id)
    debug_dir = folder / "debug"
    folder.mkdir(parents=True, exist_ok=True)

    with session_factory() as session:
        session.add(
            Meeting(
                id=meeting_id,
                title=title,
                meet_url=url,
                status=MeetingStatus.JOINING,
                folder=str(folder),
                actual_start=utcnow(),
            )
        )
        session.commit()

    if not has_disk_space(settings.data_dir):
        _fail(session_factory, meeting_id, "Not enough free disk space to record.")
        raise RecordingRefusedError("Not enough free disk space (need at least 5 GB).")

    ensure_null_sink()
    capture = AudioCapture(folder)
    stop_event = _make_stop_event()

    try:
        with open_meet_browser(settings) as (context, page):
            caption_logger = CaptionLogger(page, folder / "events.jsonl")

            def on_joined() -> None:
                _set_status(session_factory, meeting_id, MeetingStatus.RECORDING)
                # Wall-clock anchor so caption timestamps can be mapped to audio time.
                (folder / "recording_meta.json").write_text(
                    json.dumps({"start_wall": time.time()}), encoding="utf-8"
                )
                capture.start()
                caption_logger.install()

            def on_state(state: str) -> None:
                logger.info("[%s] state=%s", meeting_id, state)

            hooks = SessionHooks(
                on_state=on_state,
                on_joined=on_joined,
                on_left=lambda: capture.stop(),
                should_stop=stop_event.is_set,
            )
            session = MeetSession(
                settings.bot, page, hooks=hooks, debug_dir=debug_dir
            )
            try:
                session.run(url, title)
            finally:
                caption_logger.drain()
    except Exception as exc:  # noqa: BLE001 - record failure on the meeting
        capture.stop()
        capture.finalize()
        _fail(session_factory, meeting_id, str(exc))
        logger.exception("Recording failed for %s", meeting_id)
        raise
    finally:
        capture.stop()

    recording = capture.finalize()
    logger.info("Recording saved: %s", recording)

    ended = _set_status(session_factory, meeting_id, MeetingStatus.RECORDED, ended=True)

    if process_after:
        from meetingbot.pipeline.runner import PipelineRunner

        return PipelineRunner(settings, session_factory).run(meeting_id)
    return ended


def _set_status(
    session_factory: sessionmaker[Session],
    meeting_id: str,
    status: str,
    *,
    ended: bool = False,
) -> Meeting:
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        meeting.status = status
        if ended:
            meeting.actual_end = utcnow()
        session.commit()
        session.refresh(meeting)
        return meeting


def _fail(
    session_factory: sessionmaker[Session], meeting_id: str, error: str
) -> None:
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            return
        meeting.status = MeetingStatus.FAILED
        meeting.error = error
        meeting.actual_end = utcnow()
        session.commit()
