from __future__ import annotations

from pathlib import Path

from meetingbot.pipeline.transcribe import transcribe_audio


def test_transcribe_caches_parts(wav_16k: Path, tmp_path: Path, fake_transcriber) -> None:
    work = tmp_path / "work"
    first = transcribe_audio(fake_transcriber, wav_16k, work)
    assert fake_transcriber.calls == 1
    assert len(first.segments) == 2

    # Second call reuses the cached part file.
    second = transcribe_audio(fake_transcriber, wav_16k, work)
    assert fake_transcriber.calls == 1
    assert len(second.segments) == 2
    assert [s.start_s for s in second.segments] == [s.start_s for s in first.segments]


def test_force_ignores_cache(wav_16k: Path, tmp_path: Path, fake_transcriber) -> None:
    work = tmp_path / "work"
    transcribe_audio(fake_transcriber, wav_16k, work)
    transcribe_audio(fake_transcriber, wav_16k, work, force=True)
    assert fake_transcriber.calls == 2


def test_segments_are_renumbered(wav_16k: Path, tmp_path: Path, fake_transcriber) -> None:
    result = transcribe_audio(fake_transcriber, wav_16k, tmp_path / "work")
    assert [s.id for s in result.segments] == [0, 1]
    assert result.language == "en"
