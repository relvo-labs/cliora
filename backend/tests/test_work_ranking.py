"""The rank string, in three layers (PX-61, ported from kintra's `test_ranking.py`).

Ordering is the part of a board that most easily looks right and is wrong at the edges,
so the suite is deliberately three separate things: **fixed vectors** (the seventeen from
the prototype's actual output), **the invariants**, and **property tests** over random
and worst-case insertion patterns.

**No database.** `services/work/ranking.py` is pure, which is what makes the 5,000-insert
property test cheap enough to run on every commit.
"""

from __future__ import annotations

import random

import pytest

from app.services.work.ranking import (
    ALPHABET,
    FIRST,
    INLINE_REBALANCE_THRESHOLD,
    rank_between,
    rebalanced_ranks,
    validate_rank,
)

#: Seventeen vectors. The expected values are the prototype's real output, not values
#: derived by reading the implementation — which is what makes them a check on it.
VECTORS: list[tuple[str | None, str | None, str]] = [
    (None, None, "a"),
    (None, "a", "9"),
    (None, "1", "0i"),
    (None, "00i", "00h"),
    ("a", None, "b"),
    ("z", None, "z1"),
    ("zz", None, "zz1"),
    ("a", "b", "ai"),
    ("a", "c", "b"),
    ("a", "ab", "a5"),
    ("az", "b", "az1"),
    ("a1", "a2", "a1i"),
    ("a1i", "a2", "a1j"),
    ("0i", "1", "0j"),
    ("z", "z1", "z0i"),
    ("9", "a", "9i"),
    ("zz", "zzz", "zzh"),
]


class TestVectors:
    """Each vector asserts three things: `a < r`, `r < b`, and the invariants hold."""

    @pytest.mark.parametrize(("left", "right", "expected"), VECTORS)
    def test_vector(self, left: str | None, right: str | None, expected: str) -> None:
        result = rank_between(left, right)
        assert result == expected
        validate_rank(result)
        if left is not None:
            assert left < result
        if right is not None:
            assert result < right


class TestInvariants:
    def test_rejects_unordered_input(self) -> None:
        with pytest.raises(ValueError, match="a < b"):
            rank_between("b", "a")

    def test_rejects_equal_input(self) -> None:
        with pytest.raises(ValueError, match="a < b"):
            rank_between("a", "a")

    def test_rejects_trailing_zero(self) -> None:
        """I2. Otherwise "insert before this" can have no answer at all."""
        with pytest.raises(ValueError, match="must not end in"):
            validate_rank("a0")

    def test_rejects_foreign_characters(self) -> None:
        with pytest.raises(ValueError, match="outside the alphabet"):
            validate_rank("a-b")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_rank("")


class TestProperties:
    """Property tests with a fixed seed — a test has to be deterministic."""

    def test_random_inserts_preserve_order(self) -> None:
        rng = random.Random(20260803)  # noqa: S311 - test data, not cryptography
        sequence = [rank_between(None, None)]
        longest = 0
        for _ in range(5000):
            position = rng.randint(0, len(sequence))
            left = sequence[position - 1] if position > 0 else None
            right = sequence[position] if position < len(sequence) else None
            value = rank_between(left, right)
            validate_rank(value)
            if left is not None:
                assert left < value
            if right is not None:
                assert value < right
            sequence.insert(position, value)
            longest = max(longest, len(value))

        assert sequence == sorted(sequence)
        assert len(sequence) == 5001
        # Measured at 10; the bound is 64 so the test does not go red for an
        # implementation tweak that is still well inside the budget.
        assert longest <= 64

    def test_worst_case_growth_triggers_inline_valve(self) -> None:
        """Repeated insertion at one position: about one character per five inserts.

        Two hundred of them reach roughly 41 characters, which is what makes the inline
        valve (48) a thing that only fires under deliberately pathological use.
        """
        sequence = [rank_between(None, None), rank_between("a", None)]
        for _ in range(200):
            value = rank_between(sequence[0], sequence[1])
            sequence.insert(1, value)
        assert sequence == sorted(sequence)
        assert 30 <= len(sequence[1]) <= INLINE_REBALANCE_THRESHOLD

    def test_never_returns_zero_suffix(self) -> None:
        for left in ("1", "a", "z", "a1", "zz", "0i"):
            for right in (None, "zzz"):
                if right is not None and left >= right:
                    continue
                assert not rank_between(left, right).endswith(FIRST)


class TestRebalance:
    def test_produces_ordered_unique_ranks(self) -> None:
        for count in (1, 5, 40, 500):
            ranks = rebalanced_ranks(count)
            assert len(ranks) == count
            assert ranks == sorted(ranks)
            assert len(set(ranks)) == count
            for value in ranks:
                validate_rank(value)

    def test_is_idempotent(self) -> None:
        """An already balanced project rebalances to the same values — 0 rows updated."""
        assert rebalanced_ranks(40) == rebalanced_ranks(40)

    def test_width_three_for_reasonable_counts(self) -> None:
        assert all(len(value) == 3 for value in rebalanced_ranks(40))

    def test_widens_automatically_when_dense(self) -> None:
        """Past 36³ / 2 cards it widens itself, so the caller never has to decide."""
        ranks = rebalanced_ranks(len(ALPHABET) ** 3 // 2 + 10)
        assert all(len(value) == 4 for value in ranks)
        assert ranks == sorted(ranks)

    def test_empty(self) -> None:
        assert rebalanced_ranks(0) == []

    def test_rebalancing_preserves_relative_order(self) -> None:
        """**The property the whole thing exists for**, and the one a plausible-looking
        rebalance can fail: the nth card before is the nth card after.

        Not in kintra's suite — added here because `0043`'s backfill is a rebalance over
        every existing card, and a reshuffle on upgrade is the single most visible way
        this phase could go wrong.
        """
        before = [rank_between(None, None)]
        for _ in range(50):
            before.append(rank_between(before[-1], None))
        after = rebalanced_ranks(len(before))
        assert [index for index, _ in sorted(enumerate(before), key=lambda p: p[1])] == [
            index for index, _ in sorted(enumerate(after), key=lambda p: p[1])
        ]
