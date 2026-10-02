from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetingbot.config import Settings
from meetingbot.db import (
    Meeting,
    MeetingStatus,
    Note,
    Segment,
    create_db_engine,
    init_db,
    make_session_factory,
)
from meetingbot.web.app import create_app


@pytest.fixture
def web(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    folder = settings.meetings_dir / "2026-10-02_sync_abcd"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "recording.opus").write_bytes(b"fake-audio")
    (folder / "notes.en.md").write_text("# Notes\n", encoding="utf-8")

    engine = create_db_engine(memory=True)
    init_db(engine)
    sf = make_session_factory(engine)
    with sf() as session:
        session.add(
            Meeting(
                id="2026-10-02_sync_abcd",
                title="Weekly Sync",
                status=MeetingStatus.DONE,
                folder=str(folder),
            )
        )
        session.add(
            Segment(
                meeting_id="2026-10-02_sync_abcd",
                start_s=0.0,
                end_s=2.0,
                speaker="Alice",
                text_original="Hello",
                text_en="Hello",
                text_ar="مرحبا",
            )
        )
        session.add(
            Segment(
                meeting_id="2026-10-02_sync_abcd",
                start_s=2.0,
                end_s=4.0,
                speaker="Alice",
                text_original="Again",
                text_en="Again",
                text_ar="مرة أخرى",
            )
        )
        session.add(
            Note(
                meeting_id="2026-10-02_sync_abcd",
                lang="en",
                summary="Short summary",
                key_points_json='["a point"]',
            )
        )
        session.commit()

    app = create_app(settings, sf)
    client = TestClient(app)
    return client, settings, folder


def test_health(web) -> None:
    client, _, _ = web
    assert client.get("/health").json() == {"status": "ok"}


def test_index_lists_meeting(web) -> None:
    client, _, _ = web
    response = client.get("/")
    assert response.status_code == 200
    assert "Weekly Sync" in response.text


def test_detail_renders_rtl_and_segments(web) -> None:
    client, _, _ = web
    response = client.get("/meetings/2026-10-02_sync_abcd")
    assert response.status_code == 200
    assert 'dir="rtl"' in response.text  # Arabic blocks
    assert "مرحبا" in response.text
    assert "Short summary" in response.text


def test_detail_404(web) -> None:
    client, _, _ = web
    assert client.get("/meetings/nope").status_code == 404


def test_audio_endpoint(web) -> None:
    client, _, _ = web
    response = client.get("/meetings/2026-10-02_sync_abcd/audio")
    assert response.status_code == 200
    assert response.content == b"fake-audio"


def test_file_download(web) -> None:
    client, _, _ = web
    response = client.get("/meetings/2026-10-02_sync_abcd/files/notes.en.md")
    assert response.status_code == 200
    assert "# Notes" in response.text


def test_file_path_traversal_blocked(web) -> None:
    client, _, _ = web
    response = client.get("/meetings/2026-10-02_sync_abcd/files/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)


def test_rename_speaker(web) -> None:
    client, _, _ = web
    response = client.post(
        "/meetings/2026-10-02_sync_abcd/speaker?old=Alice&new=Alicia"
    )
    assert response.status_code == 200
    assert response.json()["renamed"] == 2


def test_rename_requires_new_name(web) -> None:
    client, _, _ = web
    response = client.post("/meetings/2026-10-02_sync_abcd/speaker?old=Alice&new=")
    assert response.status_code == 400


def test_reprocess_queues(web) -> None:
    client, _, _ = web
    response = client.post("/meetings/2026-10-02_sync_abcd/reprocess")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
