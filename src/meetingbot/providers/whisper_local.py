"""Local faster-whisper transcriber.

faster_whisper is imported lazily so the rest of the app works without the heavy
``stt`` extra installed (useful for development and for the web UI).
"""

from __future__ import annotations

from pathlib import Path

from meetingbot.providers.base import TranscriptionResult, TranscriptSegment


class WhisperNotInstalledError(RuntimeError):
    """Raised when faster-whisper is not available."""


class FasterWhisperTranscriber:
    """Transcriber backed by a local faster-whisper model."""

    def __init__(
        self,
        model: str,
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        vad_filter: bool = True,
        multilingual: bool = False,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.multilingual = multilingual
        self.language = language
        self.initial_prompt = initial_prompt
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - depends on env
            raise WhisperNotInstalledError(
                "faster-whisper is not installed. Install it with: pip install 'meetingbot[stt]'"
            ) from exc
        self._model = WhisperModel(
            self.model_name, device=self.device, compute_type=self.compute_type
        )
        return self._model

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        model = self._ensure_model()
        lang = language if language is not None else self.language
        prompt = initial_prompt if initial_prompt is not None else self.initial_prompt

        kwargs: dict = {
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
            "word_timestamps": False,
        }
        if lang:
            kwargs["language"] = lang
        if prompt:
            kwargs["initial_prompt"] = prompt
        if self.multilingual:
            kwargs["multilingual"] = True

        try:
            segment_iter, info = model.transcribe(str(audio_path), **kwargs)
        except TypeError:
            # Older faster-whisper builds don't support `multilingual`.
            kwargs.pop("multilingual", None)
            segment_iter, info = model.transcribe(str(audio_path), **kwargs)

        segments: list[TranscriptSegment] = []
        for index, seg in enumerate(segment_iter):
            segments.append(
                TranscriptSegment(
                    id=index,
                    start_s=float(seg.start),
                    end_s=float(seg.end),
                    text=(seg.text or "").strip(),
                    language=getattr(seg, "language", None) or getattr(info, "language", None),
                    avg_logprob=getattr(seg, "avg_logprob", None),
                )
            )

        return TranscriptionResult(
            segments=segments,
            language=getattr(info, "language", None) or lang,
            duration_s=getattr(info, "duration", None),
        )
