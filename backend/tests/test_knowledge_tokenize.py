"""The tokenizer, on its own (`KN-07`, ADR 0038 §4, D79).

These are the cheapest tests in the phase and the most important. The function they
cover has one job — produce the same lexemes for the index and for the query — and its
failure mode is **silence**: index and query disagree, every search returns nothing, and
nothing anywhere raises. There is no integration test that would catch that as clearly
as seven assertions about a pure function.
"""

from __future__ import annotations

import pytest

from app.services.knowledge.tokenize import document, has_cjk, lexemes


def test_cjk_becomes_overlapping_bigrams():
    """Bigrams, not unigrams (`期` would match everything) and not trigrams (`租約`,
    the ordinary two-character word, would match nothing)."""
    assert lexemes("租約過期") == ["租約", "約過", "過期"]


def test_an_identifier_keeps_itself_and_gains_its_parts():
    """The whole token ranks an exact search above one that only matched the pieces."""
    got = lexemes("lease_expires_at")
    assert got[0] == "lease_expires_at"
    assert set(got) == {"lease_expires_at", "lease", "expires", "at"}


def test_camel_case_is_split_too():
    assert set(lexemes("LeaseExpiresAt")) == {"leaseexpiresat", "lease", "expires", "at"}


def test_a_card_reference_survives_whole_and_in_parts():
    got = lexemes("CV-05")
    assert "cv-05" in got and "cv" in got and "05" in got


def test_mixed_writing_systems_do_not_contaminate_each_other():
    got = lexemes("處理 lease_expires_at 逾時")
    # Each CJK run is bigrammed independently, so a word does not bleed across the
    # ASCII token that separates it from the next one.
    assert "處理" in got and "逾時" in got
    assert "理逾" not in got, "two runs must not be joined across the ASCII between them"
    assert "lease_expires_at" in got
    assert all(
        not any("\u4e00" <= ch <= "\u9fff" for ch in token) or len(token) == 2 for token in got
    ), "a CJK lexeme is always exactly one bigram"


def test_a_single_cjk_character_produces_no_lexeme_and_says_it_is_cjk():
    """The degraded-search case. The caller has to report it: an empty page reads as
    "nothing was written about this", which is a different and wrong answer."""
    assert lexemes("期") == []
    assert has_cjk("期") is True


def test_output_is_deduplicated_but_ordered():
    got = lexemes("lease lease expires")
    assert got == ["lease", "expires"]


@pytest.mark.parametrize(
    "text",
    ["", "   ", "。。。", "​​", "🙂🙂", "———"],
)
def test_degenerate_input_produces_no_empty_lexemes(text):
    assert all(token.strip() for token in lexemes(text))


def test_a_very_long_token_is_dropped_rather_than_rejected_by_postgres():
    """A tsvector lexeme is bounded at 2047 bytes; a minified line that escaped the
    exclude rules must not make the insert fail."""
    assert lexemes("a" * 500) == []


def test_a_long_document_is_linear_and_does_not_recurse():
    got = lexemes("租約過期。" * 20_000)
    assert got  # completed at all, and produced something


def test_document_is_the_space_joined_form():
    assert document("租約過期") == "租約 約過 過期"
