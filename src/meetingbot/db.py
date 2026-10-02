"""SQLite data model and engine helpers.

Tables map to the plan's data model: meetings, stages, segments, notes.
The schema is created with ``Base.metadata.create_all`` (no migration tool yet).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --- status / stage constants -----------------------------------------
class MeetingStatus:
    SCHEDULED = "scheduled"
    JOINING = "joining"
    RECORDING = "recording"
    RECORDED = "recorded"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    SUMMARIZING = "summarizing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    ALL = [
        SCHEDULED, JOINING, RECORDING, RECORDED, TRANSCRIBING,
        TRANSLATING, SUMMARIZING, DONE, FAILED, SKIPPED,
    ]


class StageName:
    NORMALIZE = "normalize"
    TRANSCRIBE = "transcribe"
    ALIGN_SPEAKERS = "align_speakers"
    TRANSLATE = "translate"
    SUMMARIZE = "summarize"
    EXPORT = "export"

    ORDERED = [NORMALIZE, TRANSCRIBE, ALIGN_SPEAKERS, TRANSLATE, SUMMARIZE, EXPORT]


class StageStatus:
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Base(DeclarativeBase):
    pass


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, default="")
    meet_url: Mapped[str | None] = mapped_column(String, nullable=True)
    scheduled_start: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_end: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    actual_start: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    actual_end: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default=MeetingStatus.SCHEDULED, index=True)
    attendees_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    stages: Mapped[list[Stage]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    segments: Mapped[list[Segment]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    notes: Mapped[list[Note]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )

    @property
    def attendees(self) -> list[Any]:
        try:
            return json.loads(self.attendees_json or "[]")
        except json.JSONDecodeError:
            return []

    @attendees.setter
    def attendees(self, value: list[Any]) -> None:
        self.attendees_json = json.dumps(value, ensure_ascii=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Meeting {self.id} status={self.status}>"


class Stage(Base):
    __tablename__ = "stages"
    __table_args__ = (UniqueConstraint("meeting_id", "stage", name="uq_stage_meeting_stage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    stage: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default=StageStatus.PENDING)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    meeting: Mapped[Meeting] = relationship(back_populates="stages")


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    speaker: Mapped[str | None] = mapped_column(String, nullable=True)
    lang: Mapped[str | None] = mapped_column(String, nullable=True)
    text_original: Mapped[str] = mapped_column(Text, default="")
    text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_ar: Mapped[str | None] = mapped_column(Text, nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="segments")


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (UniqueConstraint("meeting_id", "lang", name="uq_note_meeting_lang"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    lang: Mapped[str] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_points_json: Mapped[str] = mapped_column(Text, default="[]")
    decisions_json: Mapped[str] = mapped_column(Text, default="[]")
    action_items_json: Mapped[str] = mapped_column(Text, default="[]")
    open_questions_json: Mapped[str] = mapped_column(Text, default="[]")

    meeting: Mapped[Meeting] = relationship(back_populates="notes")


def _json_list(value: str | None) -> list[Any]:
    try:
        return json.loads(value or "[]")
    except json.JSONDecodeError:
        return []


# expose helpers on Note for convenience
Note.key_points = property(lambda self: _json_list(self.key_points_json))  # type: ignore[attr-defined]
Note.decisions = property(lambda self: _json_list(self.decisions_json))  # type: ignore[attr-defined]
Note.action_items = property(lambda self: _json_list(self.action_items_json))  # type: ignore[attr-defined]
Note.open_questions = property(lambda self: _json_list(self.open_questions_json))  # type: ignore[attr-defined]


def create_db_engine(db_path: str | Path | None = None, *, memory: bool = False) -> Engine:
    """Create a SQLite engine. ``memory=True`` yields an in-memory test engine."""
    if memory or db_path is None:
        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def get_or_create_stage(session: Session, meeting_id: str, stage: str) -> Stage:
    row = (
        session.query(Stage)
        .filter_by(meeting_id=meeting_id, stage=stage)
        .one_or_none()
    )
    if row is None:
        row = Stage(meeting_id=meeting_id, stage=stage, status=StageStatus.PENDING)
        session.add(row)
        session.flush()
    return row
