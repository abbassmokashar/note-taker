from __future__ import annotations

import json

from meetingbot.pipeline.glossary import apply_glossary_correction, build_initial_prompt
from meetingbot.providers.base import TranscriptSegment


def test_build_initial_prompt_no_glossary() -> None:
    assert build_initial_prompt("base", []) == "base"
    assert build_initial_prompt(None, []) is None


def test_build_initial_prompt_with_glossary() -> None:
    prompt = build_initial_prompt("base", ["Nabil", "AUB"])
    assert prompt.startswith("base")
    assert "Nabil" in prompt and "AUB" in prompt


def test_build_initial_prompt_glossary_only() -> None:
    prompt = build_initial_prompt(None, ["Nabil"])
    assert prompt is not None
    assert prompt.startswith("Glossary")


class FixingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system, user, json_mode=False):
        self.calls += 1
        payload = json.loads(user.split("Segments:\n", 1)[1])
        return json.dumps(
            [{"id": s["id"], "text": s["text"].replace("Nabeel", "Nabil")} for s in payload]
        )


def test_apply_glossary_correction_fixes_terms() -> None:
    llm = FixingLLM()
    segments = [TranscriptSegment(id=0, start_s=0, end_s=1, text="call Nabeel today")]
    apply_glossary_correction(llm, segments, ["Nabil"])
    assert segments[0].text == "call Nabil today"
    assert llm.calls == 1


def test_apply_glossary_noop_without_glossary() -> None:
    llm = FixingLLM()
    segments = [TranscriptSegment(id=0, start_s=0, end_s=1, text="hello")]
    apply_glossary_correction(llm, segments, [])
    assert llm.calls == 0
    assert segments[0].text == "hello"


def test_apply_glossary_handles_llm_error() -> None:
    from meetingbot.providers.llm_common import LLMError

    class BadLLM:
        def complete(self, *, system, user, json_mode=False):
            raise LLMError("nope")

    segments = [TranscriptSegment(id=0, start_s=0, end_s=1, text="hi")]
    # Should not raise; text is left unchanged.
    apply_glossary_correction(BadLLM(), segments, ["Term"])
    assert segments[0].text == "hi"
