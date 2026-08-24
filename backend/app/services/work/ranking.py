"""The string that orders a board (PX-61, ADR 0042 §5).

Ported from `../kintra`'s `modules/board/ranking.py` (plan/26 D99): **the function
bodies and both test suites are the same code**, with the docstrings translated —
kintra's comments are in Chinese and this repository's are in English, and a file that
reads as a foreign object is one the next person is reluctant to change. The three
invariant names are kept so that the two can still be compared.

The requirement, stated exactly:

    given adjacent ranks a < b, produce r with a < r < b strictly, in O(1), writing
    **one row**.

A contiguous integer column cannot do this — there is no integer between adjacent
integers, so an insert renumbers the tail. Lexicographic string order can, which is the
whole reason the column is a `VARCHAR` and not an `INTEGER`.

**Pure, no I/O.** Everything here is a function of its arguments, which is what makes the
property tests below meaningful and what lets migration `0043`'s backfill call
:func:`rebalanced_ranks` without an application.
"""

from typing import Final

#: base 36, lowercase alphanumerics, already in sorted order.
#:
#: **Not base 62.** PostgreSQL string comparison is collation-dependent, and mixing case
#: can give ``a < B`` under `en_US.UTF-8`. Lowercase alphanumerics order the same way
#: under every collation, so `ORDER BY rank` does not change with a database setting.
ALPHABET: Final = "0123456789abcdefghijklmnopqrstuvwxyz"
BASE: Final = len(ALPHABET)
FIRST: Final = ALPHABET[0]
LAST: Final = ALPHABET[-1]
#: The middle digit, used when there is no upper bound to aim below.
MID: Final = ALPHABET[BASE // 2]

#: The first card in a project. Deliberately not ``'0'`` (violates I2) and not ``'z'``
#: (leaves no room above).
INITIAL_RANK: Final = "a"

#: Background rebalance threshold: a rank this long means the project should be
#: rebalanced when convenient.
REBALANCE_THRESHOLD: Final = 24
#: The inline safety valve — past this, rebalance the project during the request rather
#: than hoping the background pass arrives first.
INLINE_REBALANCE_THRESHOLD: Final = 48

_INDEX: Final[dict[str, int]] = {char: position for position, char in enumerate(ALPHABET)}


def validate_rank(value: str) -> None:
    """The three invariants.

    A violation is a programming error rather than bad user input, so this raises
    ``ValueError`` rather than a domain error.

    * **I1** non-empty, and every character is in the alphabet.
    * **I2** does **not** end in ``'0'`` — otherwise "insert before this" can be
      unsolvable: a predecessor of ``'a0'` would have to lie between ``'a'`` and
      ``'a0'``, and there is no legal string there.
    * **I3** (enforced by :func:`rank_between`, not here) the result of an insertion is
      strictly between its neighbours.
    """
    if not value:
        raise ValueError("rank must not be empty")
    if any(char not in _INDEX for char in value):
        raise ValueError(f"rank contains a character outside the alphabet: {value!r}")
    if value.endswith(FIRST):
        raise ValueError(f"rank must not end in {FIRST!r}: {value!r}")


def rank_after(a: str) -> str:
    """The smallest sensible value greater than ``a`` — "move to the bottom"."""
    for index in range(len(a) - 1, -1, -1):
        if a[index] != LAST:
            return a[:index] + ALPHABET[_INDEX[a[index]] + 1]
    # All ``'z'`` — append. Not ``'0'``, which would violate I2.
    return a + "1"


def rank_before(b: str) -> str:
    """A value smaller than ``b`` — "move to the top"."""
    index = len(b) - 1
    while index >= 0 and b[index] == FIRST:  # defensive: I2 says this cannot happen
        index -= 1
    if index < 0:
        raise ValueError(f"not a valid rank: {b!r}")
    prefix, digit = b[:index], _INDEX[b[index]]
    if digit > 1:
        return prefix + ALPHABET[digit - 1]
    # digit == 1: stepping down to ``'0'`` would violate I2, so append the middle digit.
    return prefix + FIRST + MID


def _midpoint(a: str, b: str) -> str:
    prefix = ""
    index = 0
    while True:
        left = _INDEX[a[index]] if index < len(a) else 0  # a shorter → treat as '0'
        right = _INDEX[b[index]] if index < len(b) else BASE  # a < b: b cannot run out
        if left == right:
            prefix += ALPHABET[left]
            index += 1
            continue
        if right - left > 1:
            # Room at this digit. The midpoint is >= left + 1 >= 1, so it never ends
            # in '0'.
            return prefix + ALPHABET[(left + right) // 2]
        # Adjacent digits: keep a's digit and go deeper. Past here b no longer binds.
        prefix += ALPHABET[left]
        index += 1
        if index < len(a):
            return prefix + rank_after(a[index:])
        return prefix + MID


def rank_between(a: str | None, b: str | None) -> str:
    """A rank strictly between ``a`` and ``b``.

    ``a`` is None for "move to the top", ``b`` is None for "move to the bottom", and
    both None means this is the project's first card.
    """
    if a is None and b is None:
        return INITIAL_RANK
    if a is None:
        assert b is not None
        validate_rank(b)
        return rank_before(b)
    if b is None:
        validate_rank(a)
        return rank_after(a)
    validate_rank(a)
    validate_rank(b)
    if a >= b:
        raise ValueError(f"rank_between requires a < b, got {a!r} and {b!r}")
    return _midpoint(a, b)


def _to_base36(value: int, width: int) -> str:
    digits: list[str] = []
    for _ in range(width):
        digits.append(ALPHABET[value % BASE])
        value //= BASE
    return "".join(reversed(digits))


def rebalanced_ranks(count: int, width: int = 3) -> list[str]:
    """Evenly spaced ranks for ``count`` cards: ordered, unique, and satisfying I2.

    ``width=3`` covers up to 23,327 cards (the point at which ``step >= 2`` fails);
    beyond that it widens itself, so the caller never has to decide.

    **The order of the input is the order of the output.** Rebalancing must not change
    any card's relative position — it is easy to write one that is correct on average,
    and the invariant test is what makes that specific.
    """
    if count <= 0:
        return []
    step = BASE**width // (count + 1)
    if step < 2:
        return rebalanced_ranks(count, width + 1)
    ranks: list[str] = []
    for position in range(1, count + 1):
        value = _to_base36(step * position, width)
        if value.endswith(FIRST):
            # Repair I2. `step >= 2` guarantees +1 cannot collide with the next value.
            value = value[:-1] + "1"
        ranks.append(value)
    return ranks
