"""One-time manual login for the bot's Google account.

We never automate the login form or 2FA. A headed browser opens on the (virtual)
display; the human signs in and presses Enter, and the persistent profile keeps the
session for future runs.
"""

from __future__ import annotations

import logging

from meetingbot.bot.browser import open_meet_browser
from meetingbot.config import Settings

logger = logging.getLogger(__name__)


def login_bot_account(settings: Settings) -> None:
    """Open Google's sign-in page and wait until the human confirms."""
    with open_meet_browser(settings) as (context, page):
        page.goto("https://accounts.google.com/")
        try:
            input(
                "\nSign in as the bot account in the browser window "
                "(including 2FA), then press Enter here to save the session... "
            )
        except EOFError:  # non-interactive shell
            logger.warning("No stdin available; leaving the browser open is not possible.")
        logger.info("Bot session saved to %s", settings.browser_profile_dir)
