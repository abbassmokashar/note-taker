from __future__ import annotations

import json
from pathlib import Path

import pytest

from meetingbot.config import Settings
from meetingbot.db import Meeting, MeetingStatus, Note, Segment, StageName
from meetingbot.pipeline.runner import (
    PipelineRunner,
    find_recording,
    new_meeting_id,
    process_file,
    slugify,
)


def test_slugify() -> None:
    assert slugify("Weekly Sync!") == "weekly-sync"
    assert slugify("   ") == "meeting"
    assert slugify("اجتماع")  # non-empty for Arabic


def test_new_meeting_id_shape() -> None:
    mid = new_meeting_id("Weekly Sync")
    parts = mid.split("_")
    assert len(parts) == 3
    assert parts[1] == "weekly-sync"


def test_process_file_end_to_end(
    settings: Settings, wav_16k: Path, session_factory, fake_transcriber, mock_llm
) -> None:
    meeting = process_file(
        settings,
        wav_16k,
        "Weekly Sync",
        session_factory=session_factory,
        transcriber=fake_transcriber,
        llm=mock_llm,
    )
    assert meeting.status == MeetingStatus.DONE
    folder = Path(meeting.folder)
    for name in (
        "transcript.original.md",
        "transcript.original.srt",
        "transcript.original.vtt",
        "transcript.original.json",
        "transcript.en.md",
        "transcript.ar.md",
        "transcript.raw.json",
        "transcript.translated.json",
        "bilingual.md",
        "notes.en.md",
        "notes.ar.md",
        "meta.json",
    ):
        assert (folder / name).exists(), name
    assert find_recording(folder) is not None

    with session_factory() as session:
        segments = session.query(Segment).filter_by(meeting_id=meeting.id).all()
        assert len(segments) == 2
        assert segments[0].text_original == "hello 0"
        # Source language is 'en', so English is copied as-is and Arabic is translated.
        assert segments[0].text_en == "hello 0"
        assert segments[0].text_ar == "ar:hello 0"
        notes = session.query(Note).filter_by(meeting_id=meeting.id).all()
        assert {n.lang for n in notes} == {"en", "ar"}
        assert notes[0].summary


def test_pipeline_is_idempotent(
    settings: Settings, wav_16k: Path, session_factory, fake_transcriber, mock_llm
) -> None:
    meeting = process_file(
        settings,
        wav_16k,
        "Sync",
        session_factory=session_factory,
        transcriber=fake_transcriber,
        llm=mock_llm,
    )
    assert fake_transcriber.calls == 1
    runner = PipelineRunner(settings, session_factory, transcriber=fake_transcriber, llm=mock_llm)
    runner.run(meeting.id)  # all stages already done -> no re-transcribe
    assert fake_transcriber.calls == 1

    with session_factory() as session:
        count = session.query(Segment).filter_by(meeting_id=meeting.id).count()
        assert count == 2  # no duplicates
        assert session.query(Note).filter_by(meeting_id=meeting.id).count() == 2


def test_resume_from_stage_uses_cache(
    settings: Settings, wav_16k: Path, session_factory, fake_transcriber, mock_llm
) -> None:
    meeting = process_file(
        settings,
        wav_16k,
        "Sync",
        session_factory=session_factory,
        transcriber=fake_transcriber,
        llm=mock_llm,
    )
    folder = Path(meeting.folder)
    (folder / "transcript.original.md").unlink()

    class ExplodingTranscriber:
        def transcribe(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("transcriber must not be called when raw cache exists")

    runner = PipelineRunner(
        settings, session_factory, transcriber=ExplodingTranscriber(), llm=mock_llm
    )
    runner.run(meeting.id, from_stage=StageName.EXPORT)
    assert (folder / "transcript.original.md").exists()


def test_failure_marks_meeting_failed(
    settings: Settings, wav_16k: Path, session_factory, mock_llm
) -> None:
    class BrokenTranscriber:
        def transcribe(self, *a, **k):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        process_file(
            settings,
            wav_16k,
            "Broken",
            session_factory=session_factory,
            transcriber=BrokenTranscriber(),
            llm=mock_llm,
        )

    with session_factory() as session:
        failed = session.query(Meeting).filter_by(status=MeetingStatus.FAILED).all()
        assert len(failed) == 1
        assert "boom" in (failed[0].error or "")


def test_reprocess_unknown_stage(
    settings: Settings, wav_16k: Path, session_factory, fake_transcriber, mock_llm
) -> None:
    meeting = process_file(
        settings,
        wav_16k,
        "Sync",
        session_factory=session_factory,
        transcriber=fake_transcriber,
        llm=mock_llm,
    )
    runner = PipelineRunner(settings, session_factory, transcriber=fake_transcriber, llm=mock_llm)
    with pytest.raises(ValueError):
        runner.run(meeting.id, from_stage="not-a-stage")


def test_raw_json_shape(
    settings: Settings, wav_16k: Path, session_factory, fake_transcriber, mock_llm
) -> None:
    meeting = process_file(
        settings,
        wav_16k,
        "Sync",
        session_factory=session_factory,
        transcriber=fake_transcriber,
        llm=mock_llm,
    )
    payload = json.loads(
        (Path(meeting.folder) / "transcript.raw.json").read_text(encoding="utf-8")
    )
    assert payload["language"] == "en"
    assert len(payload["segments"]) == 2


def test_translate_stage_never_loses_segments(
    settings: Settings, wav_16k: Path, session_factory, fake_transcriber, mock_llm
) -> None:
    """Even if a target language equals the source, counts must match."""
    meeting = process_file(
        settings,
        wav_16k,
        "Sync",
        session_factory=session_factory,
        transcriber=fake_transcriber,
        llm=mock_llm,
    )
    translated = json.loads(
        (Path(meeting.folder) / "transcript.translated.json").read_text(encoding="utf-8")
    )
    assert len(translated["segments"]) == 2
    for seg in translated["segments"]:
        assert seg["text_en"]
        assert seg["text_ar"]
