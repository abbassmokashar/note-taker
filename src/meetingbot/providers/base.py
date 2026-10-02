"""Provider interfaces.

Every external dependency (speech-to-text, LLM, notifications) is defined here as a
protocol returning plain dataclasses, so implementations can be swapped without
touching the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class TranscriptSegment:
    """One timed, spoken segment."""

    start_s: float
    end_s: float
    text: str
    language: str | None = None
    speaker: str | None = None
    avg_logprob: float | None = None
    id: int | None = None
    text_en: str | None = None
    text_ar: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "text": self.text,
            "language": self.language,
            "speaker": self.speaker,
            "avg_logprob": self.avg_logprob,
            "text_en": self.text_en,
            "text_ar": self.text_ar,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TranscriptSegment:
        return cls(
            start_s=float(data["start_s"]),
            end_s=float(data["end_s"]),
            text=data.get("text", ""),
            language=data.get("language"),
            speaker=data.get("speaker"),
            avg_logprob=data.get("avg_logprob"),
            id=data.get("id"),
            text_en=data.get("text_en"),
            text_ar=data.get("text_ar"),
        )


@dataclass
class TranscriptionResult:
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str | None = None
    duration_s: float | None = None

    @property
    def text(self) -> str:
        return " ".join(seg.text.strip() for seg in self.segments if seg.text.strip())


@runtime_checkable
class Transcriber(Protocol):
    """Speech-to-text provider."""

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:  # pragma: no cover - protocol
        ...


@runtime_checkable
class LLM(Protocol):
    """Text generation provider (translation, notes)."""

    def complete(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = False,
    ) -> str:  # pragma: no cover - protocol
        ...


@runtime_checkable
class Notifier(Protocol):
    """Delivery provider."""

    def notify(self, meeting_id: str, subject: str, body: str, attachments: list[Path] | None = None) -> None:  # pragma: no cover - protocol
        ...
