"""Structured logging setup: rotating file + rich console."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    *,
    console: bool = True,
) -> logging.Logger:
    """Configure the root logger. Safe to call multiple times."""

    resolved = level.upper() if level else "INFO"
    if resolved not in _LEVELS:
        resolved = "INFO"

    root = logging.getLogger()
    root.setLevel(resolved)

    # Remove handlers we previously installed so repeated calls don't duplicate.
    for handler in list(root.handlers):
        if getattr(handler, "_meetingbot", False):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream._meetingbot = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler._meetingbot = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
