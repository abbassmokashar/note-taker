"""Caption scraping for speaker attribution.

We turn on Meet's live captions and observe their DOM, recording
``{t_wall, speaker_name, caption_text}`` events. Captions are used ONLY for speaker
names and timing — never as the transcript itself.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Injected once per page. Uses a MutationObserver and keeps events in a JS buffer
# that Python drains periodically.
CAPTION_OBSERVER_JS = r"""
(() => {
  if (window.__meetingbotCaptionInstalled) return true;
  window.__meetingbotCaptionInstalled = true;
  window.__meetingbotEvents = [];

  const containerSelectors = ['div[jsname="dsyhDe"]', '.a4cQT', 'div[aria-live="polite"]'];

  const detectSpeaker = (node) => {
    const img = node.querySelector && node.querySelector('img[alt]');
    if (img && img.alt) return img.alt;
    const labelled = node.querySelector && node.querySelector('[aria-label]');
    if (labelled && labelled.getAttribute('aria-label')) {
      return labelled.getAttribute('aria-label');
    }
    const nameEl = node.querySelector && node.querySelector('.xo6lbf, .KcIKyf, .jbbS8b');
    if (nameEl && nameEl.textContent) return nameEl.textContent.trim();
    return 'Unknown';
  };

  const record = (node) => {
    const text = (node.textContent || '').trim();
    if (!text) return;
    const events = window.__meetingbotEvents;
    const last = events[events.length - 1];
    if (last && last.caption_text === text) return;
    events.push({ t_wall: Date.now() / 1000, speaker_name: detectSpeaker(node), caption_text: text });
    if (events.length > 5000) events.splice(0, 1000);
  };

  const observe = (node) => {
    const observer = new MutationObserver(() => record(node));
    observer.observe(node, { childList: true, subtree: true, characterData: true });
    record(node);
  };

  const attach = () => {
    for (const sel of containerSelectors) {
      document.querySelectorAll(sel).forEach((node) => {
        if (!node.__meetingbotObserved) {
          node.__meetingbotObserved = true;
          observe(node);
        }
      });
    }
  };

  attach();
  new MutationObserver(attach).observe(document.body, { childList: true, subtree: true });
  return true;
})();
"""

DRAIN_JS = """
(() => {
  const events = window.__meetingbotEvents || [];
  window.__meetingbotEvents = [];
  return events;
})();
"""


def normalize_events(raw: Any) -> list[dict]:
    """Coerce whatever the browser returned into a clean list of caption events."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("caption_text", "")).strip()
        if not text:
            continue
        try:
            t_wall = float(item.get("t_wall"))
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "t_wall": t_wall,
                "speaker_name": str(item.get("speaker_name") or "Unknown"),
                "caption_text": text,
            }
        )
    return out


def append_jsonl(path: Path, events: list[dict]) -> int:
    """Append events to a JSONL file. Returns the number written."""
    if not events:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return len(events)


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


class CaptionLogger:
    """Installs the observer in a page and drains its buffer to disk."""

    def __init__(self, page, events_path: Path) -> None:
        self.page = page
        self.events_path = events_path
        self.total = 0

    def install(self) -> bool:
        try:
            return bool(self.page.evaluate(CAPTION_OBSERVER_JS))
        except Exception as exc:  # noqa: BLE001 - captions are best-effort
            logger.warning("Could not install caption observer: %s", exc)
            return False

    def drain(self) -> int:
        try:
            raw = self.page.evaluate(DRAIN_JS)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not drain caption events: %s", exc)
            return 0
        events = normalize_events(raw)
        written = append_jsonl(self.events_path, events)
        self.total += written
        return written
