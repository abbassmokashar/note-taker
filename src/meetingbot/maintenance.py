"""Maintenance tasks: retention cleanup of old audio."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from meetingbot.config import Settings
from meetingbot.db import create_db_engine, init_db, make_session_factory
from meetingbot.pipeline.runner import find_recording

logger = logging.getLogger(__name__)


def cleanup_old_audio(
    settings: Settings,
    session_factory: sessionmaker[Session] | None = None,
    *,
    now: dt.datetime | None = None,
) -> int:
    """Delete recordings older than ``outputs.delete_audio_after_days``. Returns count."""
    days = settings.outputs.delete_audio_after_days
    if days <= 0:
        return 0

    if session_factory is None:
        engine = create_db_engine(settings.db_path)
        init_db(engine)
        session_factory = make_session_factory(engine)

    now = now or dt.datetime.now(dt.UTC).replace(tzinfo=None)
    cutoff = now - dt.timedelta(days=days)

    deleted = 0
    with session_factory() as session:
        from meetingbot.db import Meeting

        for meeting in session.query(Meeting).all():
            reference = meeting.actual_end or meeting.scheduled_end or meeting.created_at
            if reference is None or reference >= cutoff:
                continue
            folder = Path(meeting.folder) if meeting.folder else settings.meetings_dir / meeting.id
            recording = find_recording(folder)
            if recording is not None and recording.exists():
                try:
                    recording.unlink()
                    deleted += 1
                    logger.info("Deleted old recording %s", recording)
                except OSError as exc:  # pragma: no cover
                    logger.warning("Could not delete %s: %s", recording, exc)
    logger.info("Retention cleanup removed %d recording(s).", deleted)
    return deleted
