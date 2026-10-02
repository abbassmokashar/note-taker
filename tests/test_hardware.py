from __future__ import annotations

import pytest

from meetingbot.hardware import detect_tier, resolve_transcription


def test_tier_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETINGBOT_TIER", "A")
    assert detect_tier() == "A"


def test_tier_a_uses_large_v3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETINGBOT_TIER", "A")
    resolved = resolve_transcription()
    assert resolved.model == "large-v3"
    assert resolved.device == "cuda"
    assert resolved.compute_type == "float16"


def test_tier_c_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETINGBOT_TIER", "C")
    resolved = resolve_transcription()
    assert resolved.device == "cpu"
    assert resolved.compute_type == "int8"
    assert resolved.model == "large-v3-turbo"


def test_tier_d_small(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETINGBOT_TIER", "D")
    assert resolve_transcription().model == "small"


def test_explicit_values_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEETINGBOT_TIER", "A")
    resolved = resolve_transcription(model="medium", device="cpu", compute_type="int8")
    assert resolved.model == "medium"
    assert resolved.device == "cpu"
    assert resolved.compute_type == "int8"
