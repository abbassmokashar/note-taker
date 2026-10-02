from __future__ import annotations

import datetime as dt
from pathlib import Path

from meetingbot.config import Settings
from meetingbot.db import Meeting, create_db_engine, init_db, make_session_factory
from meetingbot.maintenance import cleanup_old_audio


def _setup(tmp_path: Path, *, days_old: int, retention: int):
    settings = Settings(data_dir=tmp_path / "data")
    settings.outputs.delete_audio_after_days = retention
    settings.ensure_dirs()
    folder = settings.meetings_dir / "m1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "recording.wav").write_bytes(b"audio")

    engine = create_db_engine(memory=True)
    init_db(engine)
    sf = make_session_factory(engine)
    past = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=days_old)
    with sf() as session:
        session.add(Meeting(id="m1", title="Old", folder=str(folder), actual_end=past))
        session.commit()
    return settings, sf, folder


def test_cleanup_deletes_old_recording(tmp_path: Path) -> None:
    settings, sf, folder = _setup(tmp_path, days_old=100, retention=90)
    removed = cleanup_old_audio(settings, sf)
    assert removed == 1
    assert not (folder / "recording.wav").exists()


def test_cleanup_keeps_recent_recording(tmp_path: Path) -> None:
    settings, sf, folder = _setup(tmp_path, days_old=5, retention=90)
    removed = cleanup_old_audio(settings, sf)
    assert removed == 0
    assert (folder / "recording.wav").exists()


def test_cleanup_disabled_when_zero(tmp_path: Path) -> None:
    settings, sf, folder = _setup(tmp_path, days_old=1000, retention=0)
    assert cleanup_old_audio(settings, sf) == 0
    assert (folder / "recording.wav").exists()
