"""Word/character error rate metrics for STT evaluation."""

from __future__ import annotations

import re
import unicodedata

_PUNCT_RE = re.compile(r"[^\w\s\u0600-\u06FF]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/diacritics, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    # Remove Arabic diacritics (they are not meaningful for WER).
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _edit_distance(a: list, b: list) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize(reference).split()
    hyp = normalize(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def character_error_rate(reference: str, hypothesis: str) -> float:
    ref = list(normalize(reference).replace(" ", ""))
    hyp = list(normalize(hypothesis).replace(" ", ""))
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def word_matches(reference: str, hypothesis: str) -> tuple[int, int]:
    """Return (correct_words, total_reference_words) — a rough accuracy helper."""
    ref = normalize(reference).split()
    hyp = normalize(hypothesis).split()
    distance = _edit_distance(ref, hyp)
    correct = max(0, len(ref) - distance)
    return correct, len(ref)
