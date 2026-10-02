from __future__ import annotations

import json
import re
import wave
from pathlib import Path

import pytest

from meetingbot.config import Settings
from meetingbot.db import create_db_engine, init_db, make_session_factory
from meetingbot.providers.base import TranscriptionResult, TranscriptSegment


@pytest.fixture
def wav_16k(tmp_path: Path) -> Path:
    """A short 16 kHz mono WAV, generated with the stdlib (no ffmpeg needed)."""
    path = tmp_path / "sample.wav"
    rate = 16000
    seconds = 1.0
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(data_dir=data_dir)


@pytest.fixture
def session_factory():
    engine = create_db_engine(memory=True)
    init_db(engine)
    return make_session_factory(engine)


class CountingTranscriber:
    """A fake transcriber that records how many times it was called."""

    def __init__(self, segments_per_call: int = 2) -> None:
        self.calls = 0
        self.segments_per_call = segments_per_call

    def transcribe(self, audio_path, *, language=None, initial_prompt=None):
        self.calls += 1
        segments = [
            TranscriptSegment(
                id=i,
                start_s=i * 1.0,
                end_s=i * 1.0 + 1.0,
                text=f"hello {i}",
                language="en",
                avg_logprob=-0.2,
            )
            for i in range(self.segments_per_call)
        ]
        return TranscriptionResult(segments=segments, language="en", duration_s=2.0)


@pytest.fixture
def fake_transcriber() -> CountingTranscriber:
    return CountingTranscriber()


_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class MockLLM:
    """Deterministic LLM stand-in for tests (no network)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.notes_markdown = (
            "# Test Meeting\n\n"
            "## TL;DR\nThis is a summary.\n\n"
            "## Key discussion points\n- First point\n- Second point\n\n"
            "## Decisions\n- We decided X [00:10]\n\n"
            "## Action items\n"
            "| Task | Owner | Due | [mm:ss] |\n"
            "| --- | --- | --- | --- |\n"
            "| Send report | Alice | Friday | [00:20] |\n\n"
            "## Open questions\n- What about Y?\n\n"
            "## Notable numbers and dates\n- 25% growth\n"
        )

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> str:
        self.calls.append((system, user, json_mode))
        if json_mode:
            match = _ARRAY_RE.search(user)
            items = json.loads(match.group(0)) if match else []
            target = "en" if "into English" in system or "to English" in system else "ar"
            return json.dumps(
                [{"id": item["id"], "text": f"{target}:{item['text']}"} for item in items],
                ensure_ascii=False,
            )
        return self.notes_markdown


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


class FakeElement:
    def __init__(self) -> None:
        self.click_count = 0
        self.fills: list[str] = []
        self.presses: list[str] = []

    def click(self) -> None:
        self.click_count += 1

    def fill(self, text: str) -> None:
        self.fills.append(text)

    def press(self, key: str) -> None:
        self.presses.append(key)


class FakePage:
    """Minimal Playwright-like page for selector and session tests."""

    def __init__(self, present: set[str] | None = None) -> None:
        self.present: set[str] = set(present or set())
        self.counts: dict[str, int] = {}
        self.goto_url: str | None = None
        self.screenshots: list[str] = []
        self._elements: dict[str, FakeElement] = {}
        self.html = "<html></html>"

    def element(self, selector: str) -> FakeElement:
        return self._elements.setdefault(selector, FakeElement())

    def goto(self, url: str) -> None:
        self.goto_url = url

    def query_selector(self, selector: str):
        if selector not in self.present:
            return None
        return self.element(selector)

    def query_selector_all(self, selector: str) -> list[FakeElement]:
        count = self.counts.get(selector, 0)
        return [FakeElement() for _ in range(count)]

    def screenshot(self, path: str) -> None:
        self.screenshots.append(path)

    def content(self) -> str:
        return self.html


class FakeClock:
    """Time source that advances on sleep and can trigger a callback."""

    def __init__(self, on_sleep=None) -> None:
        self.t = 0.0
        self.on_sleep = on_sleep
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds
        if self.on_sleep:
            self.on_sleep()
