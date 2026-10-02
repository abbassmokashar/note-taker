from __future__ import annotations

from meetingbot.bot import meet_selectors as S
from tests.conftest import FakePage


def test_resolve_returns_first_present_candidate() -> None:
    # JOIN_NOW's first candidate is 'text="Join now"'; provide a later candidate.
    page = FakePage(present={'text="Join"'})
    element = S.resolve(page, S.JOIN_NOW_BUTTON)
    assert element is not None


def test_resolve_returns_none_when_absent() -> None:
    page = FakePage(present=set())
    assert S.resolve(page, S.JOIN_NOW_BUTTON) is None


def test_resolve_skips_broken_selector() -> None:
    class BrokenPage:
        def query_selector(self, selector):
            raise RuntimeError("invalid selector")

    assert S.resolve(BrokenPage(), S.LEAVE_BUTTON) is None


def test_resolve_all_uses_first_matching_candidate() -> None:
    page = FakePage()
    page.counts['[data-participant-id]'] = 3
    items = S.resolve_all(page, S.PARTICIPANT_ITEMS)
    assert len(items) == 3


def test_all_selectors_have_candidates() -> None:
    for spec in S.all_selectors():
        assert spec.candidates, spec.name
        assert spec.description
