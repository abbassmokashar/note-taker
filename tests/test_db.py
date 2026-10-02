from __future__ import annotations

import datetime as dt

from meetingbot.db import (
    Meeting,
    MeetingStatus,
    Note,
    Segment,
    Stage,
    StageName,
    create_db_engine,
    get_or_create_stage,
    init_db,
    make_session_factory,
)


def _session():
    engine = create_db_engine(memory=True)
    init_db(engine)
    return make_session_factory(engine)


def test_create_and_load_meeting() -> None:
    session_factory = _session()
    with session_factory() as session:
        meeting = Meeting(
            id="2026-10-02_weekly-sync_ab12",
            title="Weekly sync",
            meet_url="https://meet.google.com/abc-defg-hij",
            status=MeetingStatus.SCHEDULED,
            scheduled_start=dt.datetime(2026, 10, 2, 9, 0, tzinfo=dt.UTC),
        )
        meeting.attendees = [{"email": "a@example.com", "response": "accepted"}]
        session.add(meeting)
        session.commit()

    with session_factory() as session:
        loaded = session.get(Meeting, "2026-10-02_weekly-sync_ab12")
        assert loaded is not None
        assert loaded.title == "Weekly sync"
        assert loaded.attendees == [{"email": "a@example.com", "response": "accepted"}]
        assert loaded.error is None


def test_get_or_create_stage_is_idempotent() -> None:
    session_factory = _session()
    with session_factory() as session:
        session.add(Meeting(id="m1", title="t"))
        session.flush()
        first = get_or_create_stage(session, "m1", StageName.TRANSCRIBE)
        second = get_or_create_stage(session, "m1", StageName.TRANSCRIBE)
        session.commit()
        assert first.id == second.id
        assert session.query(Stage).filter_by(meeting_id="m1").count() == 1


def test_segments_and_notes_roundtrip() -> None:
    session_factory = _session()
    with session_factory() as session:
        meeting = Meeting(id="m2", title="Bilingual")
        meeting.segments.append(
            Segment(
                start_s=0.0,
                end_s=3.5,
                speaker="Alice",
                lang="en",
                text_original="Hello",
                text_en="Hello",
                text_ar="مرحبا",
            )
        )
        note = Note(
            lang="ar",
            summary="ملخص",
            key_points_json='["نقطة"]',
            action_items_json='[{"task": "x"}]',
        )
        meeting.notes.append(note)
        session.add(meeting)
        session.commit()

    with session_factory() as session:
        loaded = session.get(Meeting, "m2")
        assert loaded is not None
        assert len(loaded.segments) == 1
        assert loaded.segments[0].text_ar == "مرحبا"
        assert loaded.notes[0].key_points == ["نقطة"]
        assert loaded.notes[0].action_items == [{"task": "x"}]


def test_cascade_delete() -> None:
    session_factory = _session()
    with session_factory() as session:
        meeting = Meeting(id="m3", title="x")
        meeting.segments.append(Segment(start_s=0, end_s=1))
        session.add(meeting)
        session.commit()
        session.delete(session.get(Meeting, "m3"))
        session.commit()
        assert session.query(Segment).count() == 0
