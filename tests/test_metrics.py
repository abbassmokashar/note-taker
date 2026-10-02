from __future__ import annotations

from meetingbot.eval.metrics import (
    character_error_rate,
    normalize,
    word_error_rate,
    word_matches,
)


def test_normalize_strips_punctuation_diacritics_and_case() -> None:
    assert normalize("Hello,   World!") == "hello world"
    # Arabic diacritics are removed.
    assert normalize("مَرْحَبًا") == "مرحبا"


def test_wer_identical_is_zero() -> None:
    assert word_error_rate("hello world", "hello world") == 0.0


def test_wer_one_substitution() -> None:
    # 4 reference words, 1 wrong -> 0.25
    assert word_error_rate("the quick brown fox", "the quick brown cat") == 0.25


def test_wer_insertion() -> None:
    assert word_error_rate("a b", "a b c") == 0.5


def test_wer_empty_reference() -> None:
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "something") == 1.0


def test_cer() -> None:
    assert character_error_rate("abcd", "abcd") == 0.0
    assert character_error_rate("abcd", "abce") == 0.25


def test_word_matches() -> None:
    correct, total = word_matches("the quick brown fox", "the quick brown fox")
    assert (correct, total) == (4, 4)
    correct, total = word_matches("the quick brown fox", "the quick brown cat")
    assert total == 4
    assert correct == 3
