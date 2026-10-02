from __future__ import annotations

from pathlib import Path

from meetingbot.eval.runner import (
    EvalCase,
    evaluate,
    load_cases,
    render_report,
    write_report,
)
from meetingbot.providers.base import TranscriptionResult, TranscriptSegment


class ScriptedTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def transcribe(self, audio_path, *, language=None, initial_prompt=None):
        self.calls += 1
        return TranscriptionResult(
            segments=[TranscriptSegment(start_s=0, end_s=1, text=self.text)], language="en"
        )


def test_load_cases_requires_reference(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    (tmp_path / "b.wav").write_bytes(b"x")  # no reference -> skipped
    cases = load_cases(tmp_path)
    assert [c.name for c in cases] == ["a"]


def test_evaluate_computes_wer(tmp_path: Path) -> None:
    case = EvalCase(name="a", audio=tmp_path / "a.wav", reference="the quick brown fox")
    transcriber = ScriptedTranscriber("the quick brown cat")
    results = evaluate(transcriber, [case])
    assert transcriber.calls == 1
    assert results[0].wer == 0.25
    assert results[0].words == 4


def test_render_report_has_table_and_mean() -> None:
    from meetingbot.eval.runner import EvalResult

    report = render_report(
        [
            EvalResult(name="a", wer=0.25, cer=0.1, words=4, hypothesis="x"),
            EvalResult(name="b", wer=0.5, cer=0.2, words=2, hypothesis="y"),
        ],
        settings_note="Model: `small`",
    )
    assert "| Clip | Words | WER | CER |" in report
    assert "**37.5%**" in report  # mean WER
    assert "Model: `small`" in report


def test_write_report(tmp_path: Path) -> None:
    path = write_report(tmp_path / "docs" / "STT_EVAL.md", "# Report\n")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# Report\n"
