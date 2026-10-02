"""Administrative pipeline actions used by the web UI: speaker rename and delivery."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from meetingbot.config import Secrets, Settings
from meetingbot.db import (
    Meeting,
    Segment,
    StageName,
    StageStatus,
    get_or_create_stage,
)
from meetingbot.pipeline.runner import PipelineRunner
from meetingbot.providers.notifiers import build_notifiers

logger = logging.getLogger(__name__)


def _rewrite_speakers(path: Path, old: str, new: str) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    for seg in data.get("segments", []):
        if seg.get("speaker") == old:
            seg["speaker"] = new
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rename_speaker(
    settings: Settings,
    session_factory: sessionmaker[Session],
    meeting_id: str,
    old: str,
    new: str,
) -> int:
    """Rename a speaker everywhere and re-export. Returns the number of segments changed."""
    with session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise KeyError(meeting_id)
        changed = (
            session.query(Segment)
            .filter(Segment.meeting_id == meeting_id, Segment.speaker == old)
            .update({Segment.speaker: new})
        )
        session.commit()
        folder = Path(meeting.folder) if meeting.folder else None

    if folder is not None:
        _rewrite_speakers(folder / "transcript.raw.json", old, new)
        _rewrite_speakers(folder / "transcript.translated.json", old, new)
        # Only re-export when the pipeline outputs already exist.
        if (folder / "transcript.translated.json").exists():
            with session_factory() as session:
                row = get_or_create_stage(session, meeting_id, StageName.EXPORT)
                row.status = StageStatus.PENDING
                session.commit()
            PipelineRunner(settings, session_factory).run(
                meeting_id, from_stage=StageName.EXPORT
            )

    logger.info("Renamed speaker '%s' -> '%s' in %s (%d segments).", old, new, meeting_id, changed)
    return changed


def deliver_meeting(settings: Settings, secrets: Secrets, meeting_id: str) -> list[str]:
    """Send the notes + transcripts via the configured notifiers. Returns sent labels."""
    with session_factory_for(settings) as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise KeyError(meeting_id)
        folder = Path(meeting.folder) if meeting.folder else None
        title = meeting.title

    if folder is None or not folder.exists():
        return []

    bodies: dict[str, str] = {}
    for lang in ("en", "ar"):
        notes = folder / f"notes.{lang}.md"
        if notes.exists():
            bodies[lang] = notes.read_text(encoding="utf-8")

    attachments = [
        p
        for p in (
            folder / "notes.en.md",
            folder / "notes.ar.md",
            folder / "transcript.en.md",
            folder / "transcript.ar.md",
            folder / "transcript.original.srt",
        )
        if p.exists()
    ]

    body_parts = [f"# {title}\n"]
    if "en" in bodies:
        body_parts.append("## English notes\n\n" + bodies["en"])
    if "ar" in bodies:
        body_parts.append("## ملاحظات بالعربية\n\n" + bodies["ar"])
    body = "\n\n".join(body_parts)

    sent: list[str] = []
    for notifier in build_notifiers(settings, secrets):
        try:
            notifier.notify(meeting_id, f"Meeting notes: {title}", body, attachments)
            sent.append(type(notifier).__name__)
        except Exception:  # noqa: BLE001 - one failing channel must not block the others
            logger.exception("Notifier %s failed for %s", type(notifier).__name__, meeting_id)
    return sent


def session_factory_for(settings: Settings) -> sessionmaker[Session]:
    from meetingbot.db import create_db_engine, init_db, make_session_factory

    engine = create_db_engine(settings.db_path)
    init_db(engine)
    return make_session_factory(engine)
