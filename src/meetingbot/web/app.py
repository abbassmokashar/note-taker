"""FastAPI web UI: browse meetings, transcripts, bilingual notes, and files."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from meetingbot.config import Secrets, Settings, load_settings
from meetingbot.db import (
    Meeting,
    Note,
    Segment,
    create_db_engine,
    init_db,
    make_session_factory,
)
from meetingbot.pipeline.admin import deliver_meeting, rename_speaker
from meetingbot.pipeline.runner import find_recording, meeting_dir

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    if session_factory is None:
        engine = create_db_engine(settings.db_path)
        init_db(engine)
        session_factory = make_session_factory(engine)

    app = FastAPI(title="MeetingBot", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    secrets = Secrets.from_env()

    def _check_auth(request: Request) -> None:
        """Require a token only when the UI is exposed beyond localhost."""
        host = settings.delivery.web_ui.host
        if host in _LOCAL_HOSTS:
            return
        if not secrets.web_token:
            raise HTTPException(
                status_code=503,
                detail="Web UI is exposed beyond localhost; set MEETINGBOT_WEB_TOKEN in .env.",
            )
        supplied = request.query_params.get("token") or request.headers.get("X-MeetingBot-Token")
        if supplied != secrets.web_token:
            raise HTTPException(status_code=401, detail="Invalid or missing token.")

    def _get_meeting(session: Session, meeting_id: str) -> Meeting:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return meeting

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        _check_auth(request)
        with session_factory() as session:
            meetings = (
                session.query(Meeting).order_by(Meeting.created_at.desc()).limit(200).all()
            )
            rows = [
                {
                    "id": m.id,
                    "title": m.title,
                    "status": m.status,
                    "start": m.scheduled_start or m.actual_start,
                    "error": m.error,
                }
                for m in meetings
            ]
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"meetings": rows, "settings": settings}
        )

    @app.get("/meetings/{meeting_id}", response_class=HTMLResponse)
    def meeting_detail(request: Request, meeting_id: str):
        _check_auth(request)
        with session_factory() as session:
            meeting = _get_meeting(session, meeting_id)
            segments = (
                session.query(Segment)
                .filter(Segment.meeting_id == meeting_id)
                .order_by(Segment.start_s)
                .all()
            )
            notes = {
                n.lang: {
                    "summary": n.summary,
                    "key_points": n.key_points,
                    "decisions": n.decisions,
                    "action_items": n.action_items,
                    "open_questions": n.open_questions,
                }
                for n in session.query(Note).filter(Note.meeting_id == meeting_id).all()
            }
            speakers = sorted({s.speaker for s in segments if s.speaker})
            folder = Path(meeting.folder) if meeting.folder else None
            files = sorted(p.name for p in folder.glob("*") if p.is_file()) if folder else []
            data = {
                "id": meeting.id,
                "title": meeting.title,
                "status": meeting.status,
                "error": meeting.error,
                "duration": (
                    (meeting.actual_end - meeting.actual_start).total_seconds()
                    if meeting.actual_end and meeting.actual_start
                    else None
                ),
            }
            segment_rows = [
                {
                    "id": s.id,
                    "start_s": s.start_s,
                    "speaker": s.speaker,
                    "text_original": s.text_original,
                    "text_en": s.text_en,
                    "text_ar": s.text_ar,
                }
                for s in segments
            ]
        return TEMPLATES.TemplateResponse(
            request,
            "meeting.html",
            {
                "meeting": data,
                "segments": segment_rows,
                "notes": notes,
                "speakers": speakers,
                "files": files,
                "has_audio": any(name.startswith("recording.") for name in files),
            },
        )

    @app.get("/meetings/{meeting_id}/audio")
    def meeting_audio(request: Request, meeting_id: str):
        _check_auth(request)
        with session_factory() as session:
            meeting = _get_meeting(session, meeting_id)
            folder = Path(meeting.folder) if meeting.folder else meeting_dir(settings, meeting_id)
        recording = find_recording(folder)
        if recording is None:
            raise HTTPException(status_code=404, detail="No recording for this meeting")
        return FileResponse(recording)

    @app.get("/meetings/{meeting_id}/files/{filename}")
    def meeting_file(request: Request, meeting_id: str, filename: str):
        _check_auth(request)
        # Prevent path traversal.
        if "/" in filename or "\\" in filename or filename.startswith("."):
            raise HTTPException(status_code=400, detail="Invalid filename")
        with session_factory() as session:
            meeting = _get_meeting(session, meeting_id)
            folder = Path(meeting.folder) if meeting.folder else meeting_dir(settings, meeting_id)
        target = (folder / filename).resolve()
        if not str(target).startswith(str(folder.resolve())) or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(target)

    @app.post("/meetings/{meeting_id}/speaker")
    def rename(
        request: Request,
        meeting_id: str,
        old: str = Query(...),
        new: str = Query(...),
    ):
        _check_auth(request)
        if not new.strip():
            raise HTTPException(status_code=400, detail="New speaker name is required")
        try:
            changed = rename_speaker(settings, session_factory, meeting_id, old, new.strip())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Meeting not found") from exc
        return {"meeting_id": meeting_id, "renamed": changed, "new_name": new.strip()}

    @app.post("/meetings/{meeting_id}/reprocess")
    def reprocess(
        request: Request,
        background: BackgroundTasks,
        meeting_id: str,
        from_stage: str = Query("normalize"),
    ):
        _check_auth(request)

        def _run() -> None:
            from meetingbot.pipeline.runner import PipelineRunner

            try:
                PipelineRunner(settings, session_factory).run(meeting_id, from_stage=from_stage)
            except Exception:  # noqa: BLE001 - background task
                logger.exception("Background reprocess failed for %s", meeting_id)

        background.add_task(_run)
        return {"meeting_id": meeting_id, "from_stage": from_stage, "status": "queued"}

    @app.post("/meetings/{meeting_id}/deliver")
    def deliver(request: Request, meeting_id: str):
        _check_auth(request)
        sent = deliver_meeting(settings, secrets, meeting_id)
        return {"meeting_id": meeting_id, "sent": sent}

    return app


def run_server(settings: Settings | None = None) -> None:  # pragma: no cover - runtime
    import uvicorn

    settings = settings or load_settings()
    target = settings.delivery.web_ui
    app = create_app(settings)
    uvicorn.run(app, host=target.host, port=target.port)
