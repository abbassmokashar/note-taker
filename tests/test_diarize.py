from __future__ import annotations

from pathlib import Path

import pytest

from meetingbot.pipeline.diarize import (
    DiarizationUnavailableError,
    PyannoteDiarizer,
    SpeakerTurn,
    assign_speakers_from_turns,
)
from meetingbot.providers.base import TranscriptSegment


def _seg(start: float, end: float, text: str = "x") -> TranscriptSegment:
    return TranscriptSegment(start_s=start, end_s=end, text=text)


def test_assigns_speaker_by_overlap() -> None:
    turns = [
        SpeakerTurn(start_s=0.0, end_s=4.0, speaker="SPEAKER_00"),
        SpeakerTurn(start_s=10.0, end_s=14.0, speaker="SPEAKER_01"),
    ]
    segments = [_seg(1.0, 3.0), _seg(11.0, 13.0), _seg(20.0, 21.0)]
    assign_speakers_from_turns(segments, turns)
    assert segments[0].speaker == "SPEAKER_00"
    assert segments[1].speaker == "SPEAKER_01"
    assert segments[2].speaker is None  # no overlapping turn


def test_empty_turns_is_noop() -> None:
    segments = [_seg(0, 1)]
    assign_speakers_from_turns(segments, [])
    assert segments[0].speaker is None


def test_pyannote_requires_token(tmp_path: Path) -> None:
    diarizer = PyannoteDiarizer(hf_token=None)
    with pytest.raises(DiarizationUnavailableError):
        diarizer.diarize(tmp_path / "audio.wav")
