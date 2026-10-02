"""Optional pyannote diarization fallback for speaker attribution.

Used only when caption events are unavailable (captions are the primary method).
pyannote.audio is imported lazily because it is a heavy, optional dependency that
needs a free Hugging Face token and accepting the model terms (HUMAN STEP).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from meetingbot.providers.base import TranscriptSegment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "pyannote/speaker-diarization-3.1"


class DiarizationUnavailableError(RuntimeError):
    """pyannote (or its token/model access) is not available."""


@dataclass
class SpeakerTurn:
    start_s: float
    end_s: float
    speaker: str


class Diarizer(Protocol):
    def diarize(self, audio_path: Path) -> list[SpeakerTurn]:  # pragma: no cover - protocol
        ...


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _best_turn(
    seg: TranscriptSegment, turns: list[SpeakerTurn]
) -> SpeakerTurn | None:
    best: SpeakerTurn | None = None
    best_overlap = 0.0
    for turn in turns:
        overlap = _overlap(seg.start_s, seg.end_s, turn.start_s, turn.end_s)
        if overlap > best_overlap:
            best_overlap = overlap
            best = turn
    return best


def assign_speakers_from_turns(
    segments: list[TranscriptSegment], turns: list[SpeakerTurn]
) -> list[TranscriptSegment]:
    """Assign each segment the diarization speaker with the largest time overlap."""
    if not turns:
        return segments
    assigned = 0
    for seg in segments:
        turn = _best_turn(seg, turns)
        if turn is not None:
            seg.speaker = turn.speaker
            assigned += 1
    logger.info("Diarization attributed %d/%d segments.", assigned, len(segments))
    return segments


class PyannoteDiarizer:
    """Diarizer backed by pyannote.audio (lazy import)."""

    def __init__(self, hf_token: str | None = None, model: str = DEFAULT_MODEL) -> None:
        self.hf_token = hf_token
        self.model_name = model
        self._pipeline = None

    def _ensure_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        if not self.hf_token:
            raise DiarizationUnavailableError(
                "HF_TOKEN is not set. Create a free Hugging Face token and accept the "
                "model terms for pyannote/speaker-diarization-3.1 (see docs/SETUP.md)."
            )
        try:
            from pyannote.audio import Pipeline  # lazy heavy import
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise DiarizationUnavailableError(
                "pyannote.audio is not installed. Install it with: pip install pyannote.audio"
            ) from exc
        self._pipeline = Pipeline.from_pretrained(self.model_name, use_auth_token=self.hf_token)
        return self._pipeline

    def diarize(self, audio_path: Path) -> list[SpeakerTurn]:
        pipeline = self._ensure_pipeline()
        annotation = pipeline(str(audio_path))
        turns: list[SpeakerTurn] = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            turns.append(
                SpeakerTurn(start_s=float(turn.start), end_s=float(turn.end), speaker=str(speaker))
            )
        turns.sort(key=lambda t: t.start_s)
        return turns


def build_diarizer(hf_token: str | None) -> Diarizer:
    return PyannoteDiarizer(hf_token=hf_token)
