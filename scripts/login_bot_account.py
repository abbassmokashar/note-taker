"""One-time login helper for the bot's dedicated Google account.

Run this on a machine where you can see a browser window (or through VNC/noVNC on the
container display), sign in — including 2FA — and the persistent profile under
``data/browser_profile`` will keep the session for future automated joins.

Usage:
    python scripts/login_bot_account.py [--config config.yaml]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src` importable when run directly from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import typer  # noqa: E402

from meetingbot.bot.login import login_bot_account  # noqa: E402
from meetingbot.config import ConfigError, load_settings  # noqa: E402
from meetingbot.logging_setup import setup_logging  # noqa: E402


def main(config: Path | None = typer.Option(None, "--config", "-c")) -> None:
    try:
        settings = load_settings(config)
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    setup_logging(settings.log_level)
    login_bot_account(settings)


if __name__ == "__main__":
    typer.run(main)
