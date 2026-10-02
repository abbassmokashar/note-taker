"""Playwright browser launcher.

Chromium runs **headed on Xvfb** (headless is much more likely to be flagged by
Google), with a persistent profile so the one-time login survives, microphone/camera
permissions auto-granted, and the UI locale forced to the configured language so
selectors stay stable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from meetingbot.config import Settings

logger = logging.getLogger(__name__)


class BrowserNotInstalledError(RuntimeError):
    """Raised when Playwright (or its Chromium build) is missing."""


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise BrowserNotInstalledError(
            "Playwright is not installed. Install it with: pip install 'meetingbot[bot]' "
            "and run `playwright install chromium`."
        ) from exc
    return sync_playwright


@contextmanager
def open_meet_browser(
    settings: Settings,
    *,
    profile_dir: Path | None = None,
) -> Iterator[tuple[object, object]]:
    """Yield ``(context, page)`` for a persistent Chromium profile."""
    sync_playwright = _require_playwright()
    profile = Path(profile_dir or settings.browser_profile_dir)
    profile.mkdir(parents=True, exist_ok=True)

    args = [
        "--use-fake-ui-for-media-stream",  # auto-allow mic/camera prompts
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-features=Translate,MediaRouter",
        "--no-sandbox",
    ]
    viewport = _parse_resolution(settings.bot.video_resolution)

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,  # headed on Xvfb
                locale=settings.bot.language,
                args=args,
                viewport=viewport,
                accept_downloads=False,
            )
        except Exception as exc:  # noqa: BLE001 - surface a clear message
            raise BrowserNotInstalledError(
                f"Could not launch Chromium: {exc}. Run `playwright install chromium` "
                "and make sure an X display (Xvfb) is available."
            ) from exc

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30_000)
            yield context, page
        finally:
            try:
                context.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing browser context: %s", exc)


def _parse_resolution(value: str) -> dict[str, int]:
    try:
        width, height = value.lower().split("x")
        return {"width": int(width), "height": int(height)}
    except (ValueError, AttributeError):
        return {"width": 1280, "height": 720}
