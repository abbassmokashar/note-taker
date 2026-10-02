"""All Google Meet DOM selectors live here.

Meet's UI changes without notice, so every interaction is defined as an ordered list
of fallback selectors. When joining breaks, update this file only — nothing else in
the codebase references CSS.

The bot browser locale is forced to English (`bot.language`, default ``en-US``) so the
primary selectors are stable; Arabic fallbacks are included anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class PageLike(Protocol):  # pragma: no cover - structural typing helper
    def query_selector(self, selector: str) -> Any: ...
    def query_selector_all(self, selector: str) -> list[Any]: ...


@dataclass(frozen=True)
class Selector:
    """A named UI element with ordered fallback selectors."""

    name: str
    description: str
    candidates: list[str] = field(default_factory=list)


def resolve(page: PageLike, spec: Selector) -> Any | None:
    """Return the first element matching any candidate selector, else None."""
    for selector in spec.candidates:
        try:
            element = page.query_selector(selector)
        except Exception:  # noqa: BLE001 - a bad selector must not crash the bot
            continue
        if element is not None:
            return element
    return None


def resolve_all(page: PageLike, spec: Selector) -> list[Any]:
    for selector in spec.candidates:
        try:
            elements = page.query_selector_all(selector)
        except Exception:  # noqa: BLE001
            continue
        if elements:
            return list(elements)
    return []


def _text(*values: str) -> list[str]:
    return [f'text="{value}"' for value in values]


def _aria(*labels: str) -> list[str]:
    return [f'[aria-label="{label}"]' for label in labels]


# --- pre-join ---------------------------------------------------------
DISMISS_BUTTONS = Selector(
    "dismiss_buttons",
    "Cookie/consent/'Got it' dialogs shown before joining.",
    _text(
        "Got it", "Dismiss", "Accept all", "I agree", "OK", "No thanks",
        "حسناً", "موافق", "قبول الكل",
    ),
)

NAME_INPUT = Selector(
    "name_input",
    "Display-name field shown when joining as a guest.",
    [
        'input[aria-label="Your name"]',
        'input[placeholder="Your name"]',
        'input[type="text"]',
        _aria("Your name", "اسمك")[0],
    ],
)

MIC_BUTTON_OFF = Selector(
    "mic_button_off",
    "Microphone toggle (when currently muted).",
    _aria("Turn on microphone", "تشغيل الميكروفون"),
)

MIC_BUTTON_ON = Selector(
    "mic_button_on",
    "Microphone toggle (when currently unmuted) — click to mute.",
    _aria("Turn off microphone", "إيقاف الميكروفون"),
)

CAM_BUTTON_ON = Selector(
    "cam_button_on",
    "Camera toggle (when currently on) — click to turn off.",
    _aria("Turn off camera", "إيقاف الكاميرا"),
)

JOIN_NOW_BUTTON = Selector(
    "join_now",
    "Join button when the meeting is open.",
    _text("Join now", "Join", "انضم الآن", "انضمام"),
)

ASK_TO_JOIN_BUTTON = Selector(
    "ask_to_join",
    "Ask-to-join button when the host must admit the bot.",
    _text("Ask to join", "طلب الانضمام"),
)


# --- waiting room -----------------------------------------------------
WAITING_INDICATORS = Selector(
    "waiting_indicators",
    "Text shown while waiting to be admitted or when denied.",
    _text("Asking to join", "Waiting for the host", "You'll join when someone admits you"),
)

DENIED_INDICATORS = Selector(
    "denied_indicators",
    "Messages meaning the bot will not be admitted.",
    _text(
        "You can't join this call",
        "No one responded",
        "Your request to join was denied",
        "You were denied",
    ),
)


# --- in-meeting -------------------------------------------------------
LEAVE_BUTTON = Selector(
    "leave_button",
    "Leave-call button; proves we are in the meeting.",
    _aria("Leave call", "مغادرة المكالمة"),
)

CHAT_BUTTON = Selector(
    "chat_button",
    "Opens the in-call chat panel.",
    _aria("Chat with everyone", "Chat", "الدردشة مع الجميع", "الدردشة"),
)

CHAT_INPUT = Selector(
    "chat_input",
    "Text box to type a chat message.",
    [
        'textarea[aria-label*="message"]',
        'textarea[aria-label*="Send a message"]',
        'textarea[placeholder*="message"]',
        "textarea",
    ],
)

CHAT_SEND_BUTTON = Selector(
    "chat_send_button",
    "Send button for the chat message.",
    _aria("Send a message", "Send", "إرسال رسالة", "إرسال"),
)

CAPTIONS_BUTTON = Selector(
    "captions_button",
    "Turns on live captions (used for speaker attribution).",
    _aria("Turn on captions", "Captions", "تشغيل التعليقات التوضيحية"),
)

PARTICIPANTS_BUTTON = Selector(
    "participants_button",
    "Opens the participant list (used to count attendees).",
    _aria("Show everyone", "People", "المشاركون"),
)

PARTICIPANT_ITEMS = Selector(
    "participant_items",
    "Rows in the participant list.",
    [
        '[data-participant-id]',
        'div[role="listitem"]',
        'div[jsname][role="listitem"]',
    ],
)

CAPTION_REGION = Selector(
    "caption_region",
    "Live-caption container we attach a MutationObserver to.",
    [
        'div[jsname="dsyhDe"]',
        '.a4cQT',
        'div[aria-live="polite"]',
    ],
)

MEETING_ENDED = Selector(
    "meeting_ended",
    "Screens shown after the meeting ends or we are removed.",
    _text(
        "You left the meeting",
        "The meeting has ended",
        "You've been removed",
        "You were removed",
        "Return to home screen",
    ),
)


def all_selectors() -> list[Selector]:
    """Every selector spec, for diagnostics and tests."""
    return [
        DISMISS_BUTTONS,
        NAME_INPUT,
        MIC_BUTTON_OFF,
        MIC_BUTTON_ON,
        CAM_BUTTON_ON,
        JOIN_NOW_BUTTON,
        ASK_TO_JOIN_BUTTON,
        WAITING_INDICATORS,
        DENIED_INDICATORS,
        LEAVE_BUTTON,
        CHAT_BUTTON,
        CHAT_INPUT,
        CHAT_SEND_BUTTON,
        CAPTIONS_BUTTON,
        PARTICIPANTS_BUTTON,
        PARTICIPANT_ITEMS,
        CAPTION_REGION,
        MEETING_ENDED,
    ]
