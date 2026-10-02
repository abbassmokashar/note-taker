"""Resumable pipeline orchestration.

Stages run in order and record their status in the ``stages`` table, so a crash in
any stage can be retried with ``meetingbot reprocess <id> --from-stage <stage>``
without redoing earlier work.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from meetingbot.config import Secrets, Settings
from meetingbot.db import (
    Meeting,
    MeetingStatus,
    Note,
    Segment,
    StageName,
    StageStatus,
    create_db_engine,
    get_or_create_stage,
    init_db,
    make_session_factory,
    utcnow,
)
from meetingbot.hardware import resolve_transcription
from meetingbot.pipeline.audio_prep import ensure_16k_mono
from meetingbot.pipeline.export import (
    TranscriptMeta,
    export_bilingual,
    export_transcript,
    segments_for_lang,
    write_meta,
)
from meetingbot.pipeline.notes import generate_notes, parse_notes_markdown
from meetingbot.pipeline.speakers import (
    align_speakers,
    load_caption_events,
    load_recording_start_wall,
    merge_consecutive,
)
from meetingbot.pipeline.transcribe import transcribe_audio
from meetingbot.pipeline.translate import translate_transcript
from meetingbot.providers.base import LLM, Transcriber, TranscriptionResult, TranscriptSegment

logger = logging.getLogger(__name__)

# Stages executed by the pipeline, in order.
RUN_STAGES = [
    StageName.NORMALIZE,
    StageName.TRANSCRIBE,
    StageName.ALIGN_SPEAKERS,
    StageName.TRANSLATE,
    StageName.SUMMARIZE,
    StageName.EXPORT,
]
_FILE_FORMATS = ["md", "srt", "vtt", "json"]


def slugify(text: str, max_len: int = 40) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\-]", "", text, flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text[:max_len].strip("-")) or "meeting"


def new_meeting_id(title: str, when: dt.datetime | None = None) -> str:
    when = when or dt.datetime.now()
    return f"{when.strftime('%Y-%m-%d')}_{slugify(title)}_{uuid.uuid4().hex[:4]}"


def meeting_dir(settings: Settings, meeting_id: str) -> Path:
    return settings.meetings_dir / meeting_id


def find_recording(folder: Path) -> Path | None:
    """Locate the stored recording in a meeting folder."""
    for pattern in ("recording.*", "*.opus", "*.wav", "*.mp3", "*.m4a", "*.mp4"):
        for match in sorted(folder.glob(pattern)):
            if match.is_file() and match.name != "audio16k.wav":
                return match
    return None


def make_transcriber(settings: Settings) -> Transcriber:
    """Build the configured transcriber provider."""
    from meetingbot.providers.whisper_local import FasterWhisperTranscriber

    cfg = settings.transcription
    if cfg.provider != "faster_whisper":  # pragma: no cover - future providers
        raise NotImplementedError(
            f"Transcription provider '{cfg.provider}' is not implemented yet."
        )

    resolved = resolve_transcription(
        model=cfg.model, device=cfg.device, compute_type=cfg.compute_type
    )
    logger.info(
        "Transcriber: model=%s device=%s compute=%s tier=%s",
        resolved.model, resolved.device, resolved.compute_type, resolved.tier,
    )
    from meetingbot.pipeline.glossary import build_initial_prompt

    base_prompt = cfg.initial_prompt_ar if cfg.language in ("ar", None) else None
    prompt = build_initial_prompt(base_prompt, cfg.glossary)
    return FasterWhisperTranscriber(
        resolved.model,
        device=resolved.device,
        compute_type=resolved.compute_type,
        beam_size=cfg.beam_size,
        vad_filter=cfg.vad_filter,
        language=cfg.language,
        initial_prompt=prompt,
    )


class PipelineRunner:
    """Runs pipeline stages for a meeting, resumably."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | None = None,
        transcriber: Transcriber | None = None,
        llm: LLM | None = None,
    ) -> None:
        self.settings = settings
        if session_factory is None:
            engine = create_db_engine(settings.db_path)
            init_db(engine)
            session_factory = make_session_factory(engine)
        self.session_factory = session_factory
        self.transcriber = transcriber
        self._llm = llm

    @property
    def llm(self) -> LLM:
        if self._llm is None:
            from meetingbot.providers.factory import build_llm

            self._llm = build_llm(self.settings, Secrets.from_env())
        return self._llm

    # --- transcript caches --------------------------------------------
    def _raw_path(self, folder: Path) -> Path:
        return folder / "transcript.raw.json"

    def _translated_path(self, folder: Path) -> Path:
        return folder / "transcript.translated.json"

    def _write_segments(self, path: Path, result: TranscriptionResult) -> None:
        payload = {
            "language": result.language,
            "duration_s": result.duration_s,
            "segments": [seg.to_dict() for seg in result.segments],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_segments(self, path: Path) -> TranscriptionResult | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return TranscriptionResult(
            segments=[TranscriptSegment.from_dict(s) for s in data.get("segments", [])],
            language=data.get("language"),
            duration_s=data.get("duration_s"),
        )

    # --- orchestration -------------------------------------------------
    def run(
        self,
        meeting_id: str,
        *,
        from_stage: str | None = None,
        force: bool = False,
    ) -> Meeting:
        with self.session_factory() as session:
            meeting = session.get(Meeting, meeting_id)
            if meeting is None:
                raise KeyError(f"Meeting '{meeting_id}' not found.")
            folder = Path(meeting.folder) if meeting.folder else meeting_dir(
                self.settings, meeting_id
            )
            folder.mkdir(parents=True, exist_ok=True)
            meeting.folder = str(folder)

            if from_stage:
                self._reset_from(session, meeting_id, from_stage)

            try:
                self._run_normalize(session, meeting, folder, force=force)
                raw = self._run_transcribe(session, meeting, folder, force=force)
                raw = self._run_align_speakers(session, meeting, folder, raw, force=force)
                translated = self._run_translate(session, meeting, folder, raw, force=force)
                self._run_summarize(session, meeting, folder, translated, force=force)
                self._run_export(session, meeting, folder, raw, translated, force=force)
            except Exception as exc:  # noqa: BLE001 - record any failure on the meeting
                logger.exception("Pipeline failed for %s", meeting_id)
                meeting.status = MeetingStatus.FAILED
                meeting.error = str(exc)
                session.commit()
                raise

            meeting.status = MeetingStatus.DONE
            meeting.error = None
            session.commit()
            session.refresh(meeting)

        self._maybe_deliver(meeting_id)
        return meeting

    def _maybe_deliver(self, meeting_id: str) -> None:
        """Email/upload results when delivery is enabled. Never fails the pipeline."""
        if not (
            self.settings.delivery.email.enabled or self.settings.delivery.drive.enabled
        ):
            return
        try:
            from meetingbot.config import Secrets
            from meetingbot.pipeline.admin import deliver_meeting

            deliver_meeting(self.settings, Secrets.from_env(), meeting_id)
        except Exception:  # noqa: BLE001 - delivery problems must not fail a good run
            logger.exception("Delivery failed for %s", meeting_id)

    def _reset_from(self, session: Session, meeting_id: str, from_stage: str) -> None:
        if from_stage not in StageName.ORDERED:
            raise ValueError(
                f"Unknown stage '{from_stage}'. Valid: {', '.join(StageName.ORDERED)}"
            )
        start = StageName.ORDERED.index(from_stage)
        for stage in StageName.ORDERED[start:]:
            row = get_or_create_stage(session, meeting_id, stage)
            row.status = StageStatus.PENDING
            row.error = None
        session.commit()

    def _stage_done(self, session: Session, meeting_id: str, stage: str) -> bool:
        return get_or_create_stage(session, meeting_id, stage).status == StageStatus.DONE

    def _mark(
        self, session: Session, meeting_id: str, stage: str, status: str, error: str | None = None
    ) -> None:
        row = get_or_create_stage(session, meeting_id, stage)
        row.status = status
        if status == StageStatus.RUNNING:
            row.started_at = utcnow()
            row.attempts = (row.attempts or 0) + 1
        if status in (StageStatus.DONE, StageStatus.FAILED):
            row.finished_at = utcnow()
        row.error = error
        session.commit()

    # --- stages --------------------------------------------------------
    def _run_normalize(
        self, session: Session, meeting: Meeting, folder: Path, *, force: bool
    ) -> Path:
        existing = folder / "work" / "audio16k.wav"
        if not force and self._stage_done(session, meeting.id, StageName.NORMALIZE):
            if existing.exists():
                return existing

        self._mark(session, meeting.id, StageName.NORMALIZE, StageStatus.RUNNING)
        source = find_recording(folder)
        if source is None:
            raise FileNotFoundError(f"No recording found in {folder}")
        normalized = ensure_16k_mono(source, folder / "work")
        self._mark(session, meeting.id, StageName.NORMALIZE, StageStatus.DONE)
        return normalized

    def _run_transcribe(
        self, session: Session, meeting: Meeting, folder: Path, *, force: bool
    ) -> TranscriptionResult:
        if not force and self._stage_done(session, meeting.id, StageName.TRANSCRIBE):
            cached = self._read_segments(self._raw_path(folder))
            if cached is not None:
                return cached

        self._mark(session, meeting.id, StageName.TRANSCRIBE, StageStatus.RUNNING)
        meeting.status = MeetingStatus.TRANSCRIBING
        session.commit()

        normalized = self._run_normalize(session, meeting, folder, force=force)
        transcriber = self.transcriber or make_transcriber(self.settings)
        from meetingbot.pipeline.glossary import build_initial_prompt

        cfg = self.settings.transcription
        base_prompt = cfg.initial_prompt_ar if cfg.language in ("ar", None) else None
        prompt = build_initial_prompt(base_prompt, cfg.glossary)
        result = transcribe_audio(
            transcriber,
            normalized,
            folder / "work",
            language=self.settings.transcription.language,
            initial_prompt=prompt,
            force=force,
        )
        if cfg.glossary_correction and cfg.glossary:
            from meetingbot.pipeline.glossary import apply_glossary_correction

            apply_glossary_correction(
                self.llm, result.segments, cfg.glossary, language=cfg.language
            )
        self._write_segments(self._raw_path(folder), result)
        self._persist_segments(session, meeting.id, result.segments)
        self._mark(session, meeting.id, StageName.TRANSCRIBE, StageStatus.DONE)
        return result

    def _run_align_speakers(
        self,
        session: Session,
        meeting: Meeting,
        folder: Path,
        raw: TranscriptionResult,
        *,
        force: bool,
    ) -> TranscriptionResult:
        if not force and self._stage_done(session, meeting.id, StageName.ALIGN_SPEAKERS):
            cached = self._read_segments(self._raw_path(folder))
            if cached is not None:
                return cached

        self._mark(session, meeting.id, StageName.ALIGN_SPEAKERS, StageStatus.RUNNING)
        events = load_caption_events(folder / "events.jsonl")
        start_wall = load_recording_start_wall(folder)
        align_speakers(raw.segments, events, start_wall)
        raw.segments = merge_consecutive(raw.segments)
        self._write_segments(self._raw_path(folder), raw)
        self._persist_segments(session, meeting.id, raw.segments)
        self._mark(session, meeting.id, StageName.ALIGN_SPEAKERS, StageStatus.DONE)
        return raw

    def _run_translate(
        self,
        session: Session,
        meeting: Meeting,
        folder: Path,
        raw: TranscriptionResult,
        *,
        force: bool,
    ) -> TranscriptionResult:
        if not force and self._stage_done(session, meeting.id, StageName.TRANSLATE):
            cached = self._read_segments(self._translated_path(folder))
            if cached is not None:
                return cached

        self._mark(session, meeting.id, StageName.TRANSLATE, StageStatus.RUNNING)
        meeting.status = MeetingStatus.TRANSLATING
        session.commit()

        targets = tuple(
            lang for lang in self.settings.outputs.languages if lang in ("en", "ar")
        ) or ("en", "ar")
        translate_transcript(self.llm, raw.segments, targets=targets)
        self._write_segments(self._translated_path(folder), raw)
        self._persist_segments(session, meeting.id, raw.segments)
        self._mark(session, meeting.id, StageName.TRANSLATE, StageStatus.DONE)
        return raw

    def _run_summarize(
        self,
        session: Session,
        meeting: Meeting,
        folder: Path,
        translated: TranscriptionResult,
        *,
        force: bool,
    ) -> dict[str, str]:
        languages = [lang for lang in self.settings.outputs.languages if lang in ("en", "ar")]
        if not languages:
            languages = ["en"]

        notes: dict[str, str] = {}
        done = not force and self._stage_done(session, meeting.id, StageName.SUMMARIZE)
        if done and all((folder / f"notes.{lang}.md").exists() for lang in languages):
            for lang in languages:
                notes[lang] = (folder / f"notes.{lang}.md").read_text(encoding="utf-8")
            return notes

        self._mark(session, meeting.id, StageName.SUMMARIZE, StageStatus.RUNNING)
        meeting.status = MeetingStatus.SUMMARIZING
        session.commit()

        for lang in languages:
            markdown = generate_notes(
                self.llm,
                translated.segments,
                meeting.title,
                lang=lang,
                arabic_style=self.settings.outputs.arabic_style,
                chunk_chars=self.settings.llm.chunk_chars,
            )
            (folder / f"notes.{lang}.md").write_text(markdown, encoding="utf-8")
            notes[lang] = markdown
            self._persist_note(session, meeting.id, lang, markdown)
            if "pdf" in self.settings.outputs.formats:
                self._write_notes_pdf(folder, lang, markdown, meeting.title)

        self._mark(session, meeting.id, StageName.SUMMARIZE, StageStatus.DONE)
        return notes

    def _run_export(
        self,
        session: Session,
        meeting: Meeting,
        folder: Path,
        raw: TranscriptionResult,
        translated: TranscriptionResult,
        *,
        force: bool,
    ) -> None:
        if not force and self._stage_done(session, meeting.id, StageName.EXPORT):
            if (folder / "transcript.original.md").exists():
                return

        self._mark(session, meeting.id, StageName.EXPORT, StageStatus.RUNNING)
        formats = [f for f in self.settings.outputs.formats if f in _FILE_FORMATS]
        formats = formats or _FILE_FORMATS
        title = meeting.title

        original_meta = TranscriptMeta(
            meeting_id=meeting.id,
            title=title,
            language=raw.language,
            duration_s=raw.duration_s,
            source="original",
        )
        export_transcript(
            raw.segments, original_meta, folder, stem="transcript.original", formats=formats
        )

        for lang in self.settings.outputs.languages:
            if lang not in ("en", "ar"):
                continue
            meta = TranscriptMeta(
                meeting_id=meeting.id,
                title=title,
                language=lang,
                duration_s=raw.duration_s,
                source=lang,
            )
            export_transcript(
                segments_for_lang(translated.segments, lang),
                meta,
                folder,
                stem=f"transcript.{lang}",
                formats=formats,
            )

        export_bilingual(translated.segments, original_meta, folder)
        write_meta(
            folder,
            {
                "meeting_id": meeting.id,
                "title": title,
                "language": raw.language,
                "duration_s": raw.duration_s,
                "segment_count": len(raw.segments),
                "created_at": dt.datetime.now(dt.UTC).isoformat(),
            },
        )
        self._mark(session, meeting.id, StageName.EXPORT, StageStatus.DONE)

    # --- persistence ---------------------------------------------------
    def _persist_segments(
        self, session: Session, meeting_id: str, segments: list[TranscriptSegment]
    ) -> None:
        """Replace this meeting's segments (idempotent)."""
        session.query(Segment).filter(Segment.meeting_id == meeting_id).delete()
        for seg in segments:
            session.add(
                Segment(
                    meeting_id=meeting_id,
                    start_s=seg.start_s,
                    end_s=seg.end_s,
                    speaker=seg.speaker,
                    lang=seg.language,
                    text_original=seg.text,
                    text_en=seg.text_en,
                    text_ar=seg.text_ar,
                )
            )
        session.commit()

    def _write_notes_pdf(self, folder: Path, lang: str, markdown: str, title: str) -> None:
        if (folder / f"notes.{lang}.pdf").exists():
            return
        try:
            from meetingbot.pipeline.export import export_pdf

            export_pdf(markdown, folder, stem=f"notes.{lang}", title=title, lang=lang)
        except ImportError:
            logger.warning(
                "PDF export skipped: WeasyPrint is not installed (pip install 'meetingbot[pdf]')."
            )
        except Exception:  # noqa: BLE001 - PDF is best-effort
            logger.exception("PDF export failed for %s", lang)

    def _persist_note(
        self, session: Session, meeting_id: str, lang: str, markdown: str
    ) -> None:
        parsed = parse_notes_markdown(markdown)
        note = (
            session.query(Note)
            .filter_by(meeting_id=meeting_id, lang=lang)
            .one_or_none()
        )
        if note is None:
            note = Note(meeting_id=meeting_id, lang=lang)
            session.add(note)
        note.summary = parsed["summary"]
        note.key_points_json = json.dumps(parsed["key_points"], ensure_ascii=False)
        note.decisions_json = json.dumps(parsed["decisions"], ensure_ascii=False)
        note.action_items_json = json.dumps(parsed["action_items"], ensure_ascii=False)
        note.open_questions_json = json.dumps(parsed["open_questions"], ensure_ascii=False)
        session.commit()


def process_file(
    settings: Settings,
    audio_path: Path,
    title: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    transcriber: Transcriber | None = None,
    llm: LLM | None = None,
    force: bool = False,
) -> Meeting:
    """Create a meeting from a local audio file and run the pipeline."""
    if session_factory is None:
        engine = create_db_engine(settings.db_path)
        init_db(engine)
        session_factory = make_session_factory(engine)
    settings.ensure_dirs()

    meeting_id = new_meeting_id(title)
    folder = meeting_dir(settings, meeting_id)
    folder.mkdir(parents=True, exist_ok=True)

    stored_audio = folder / f"recording{audio_path.suffix.lower()}"
    if audio_path.resolve() != stored_audio.resolve():
        stored_audio.write_bytes(audio_path.read_bytes())

    with session_factory() as session:
        meeting = Meeting(
            id=meeting_id,
            title=title,
            status=MeetingStatus.RECORDED,
            folder=str(folder),
            actual_start=utcnow(),
        )
        session.add(meeting)
        session.commit()

    runner = PipelineRunner(settings, session_factory, transcriber=transcriber, llm=llm)
    return runner.run(meeting_id, force=force)
