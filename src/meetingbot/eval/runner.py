"""Evaluation harness: transcribe a folder of clips and report WER/CER.

Folder convention: each case is an audio file plus a sibling ``.txt`` with the
human-corrected reference transcript, e.g. ``clip1.wav`` + ``clip1.txt``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from meetingbot.eval.metrics import character_error_rate, word_error_rate
from meetingbot.providers.base import Transcriber, TranscriptSegment

logger = logging.getLogger(__name__)

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".opus", ".flac", ".ogg", ".mp4"}


@dataclass
class EvalCase:
    name: str
    audio: Path
    reference: str


@dataclass
class EvalResult:
    name: str
    wer: float
    cer: float
    words: int
    hypothesis: str


def load_cases(folder: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for audio in sorted(folder.iterdir()):
        if audio.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        reference_path = audio.with_suffix(".txt")
        if not reference_path.exists():
            logger.warning("Skipping %s: no reference %s", audio.name, reference_path.name)
            continue
        cases.append(
            EvalCase(
                name=audio.stem,
                audio=audio,
                reference=reference_path.read_text(encoding="utf-8"),
            )
        )
    return cases


def _transcript_text(segments: list[TranscriptSegment]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def evaluate(
    transcriber: Transcriber,
    cases: list[EvalCase],
    *,
    language: str | None = None,
    initial_prompt: str | None = None,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    for case in cases:
        logger.info("Evaluating %s", case.name)
        result = transcriber.transcribe(
            case.audio, language=language, initial_prompt=initial_prompt
        )
        hypothesis = _transcript_text(result.segments)
        results.append(
            EvalResult(
                name=case.name,
                wer=word_error_rate(case.reference, hypothesis),
                cer=character_error_rate(case.reference, hypothesis),
                words=len(case.reference.split()),
                hypothesis=hypothesis,
            )
        )
    return results


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def render_report(
    results: list[EvalResult], *, title: str = "STT Evaluation", settings_note: str = ""
) -> str:
    lines = [
        f"# {title}",
        "",
        "Word/character error rate on the provided reference clips "
        "(lower is better). Lebanese dialect and code-switching are harder than MSA "
        "or English — expect higher WER on those clips.",
        "",
    ]
    if settings_note:
        lines += [settings_note, ""]

    lines += [
        "| Clip | Words | WER | CER |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result.name} | {result.words} | {result.wer:.1%} | {result.cer:.1%} |"
        )
    lines.append(
        f"| **Mean** | | **{_mean([r.wer for r in results]):.1%}** "
        f"| **{_mean([r.cer for r in results]):.1%}** |"
    )
    lines.append("")
    lines.append(
        "> Accuracy on Lebanese Arabic depends heavily on the model and the "
        "`glossary` / `initial_prompt_ar` settings. Use these numbers to choose defaults."
    )
    return "\n".join(lines) + "\n"


def write_report(path: Path, markdown: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path
