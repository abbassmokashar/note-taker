"""Evaluate STT accuracy on a folder of clips with reference transcripts.

Folder layout:
    samples/
      clip1.wav
      clip1.txt      <- human-corrected reference transcript
      clip2.m4a
      clip2.txt

Usage:
    python scripts/eval_stt.py samples/ [--out docs/STT_EVAL.md] [--config config.yaml]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import typer  # noqa: E402

from meetingbot.cli import app  # noqa: E402


def main(
    folder: Path = typer.Argument(..., exists=True),
    out: Path = typer.Option(Path("docs/STT_EVAL.md"), "--out"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Delegate to `meetingbot eval` so both paths share one implementation."""
    sys.argv = ["meetingbot", "eval", str(folder), "--out", str(out)]
    if config:
        sys.argv += ["--config", str(config)]
    app()


if __name__ == "__main__":
    typer.run(main)
