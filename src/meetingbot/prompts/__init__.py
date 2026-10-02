"""Versioned prompt templates, stored as Markdown next to this module."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent


@cache
def load(name: str) -> str:
    """Load a prompt template by name (without the ``.md`` extension)."""
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt '{name}' not found at {path}")
    return path.read_text(encoding="utf-8")


def render(name: str, **replacements: str) -> str:
    """Load a prompt and substitute ``__TOKEN__`` placeholders."""
    text = load(name)
    for key, value in replacements.items():
        text = text.replace(f"__{key.upper()}__", value)
    return text


def available() -> list[str]:
    return sorted(p.stem for p in _PROMPT_DIR.glob("*.md"))
