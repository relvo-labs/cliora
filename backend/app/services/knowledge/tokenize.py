"""The single source of lexemes, for the index and for the query (ADR 0038 §4, D79).

**Why this file exists at all.** PostgreSQL ships no CJK parser, and
`postgres:16-alpine` has only the stock configurations. So::

    to_tsvector('simple', '租約過期時要怎麼處理')  →  one lexeme, the whole string

Almost every piece of product content in this system is Traditional Chinese. A
full-text channel built on the stock parser would therefore have **zero recall** over
the majority of the corpus — and zero recall raises no error, returns no warning, and
looks exactly like a project that has nothing written about the subject.

**The rule that makes it work is that there is only one of it.** The index and the
query must agree lexeme for lexeme; if they ever diverge the system keeps running and
always returns nothing. `GATE-KN-ONE-TOKENIZER` asserts that this is the only place
producing them, for the same reason `GATE-CV-PROJECTION-ONE-WRITER` exists: the failure
is silent, so a test that happens to pass today is not enough.

**Why bigrams for CJK.** Unigrams make `期` match everything; trigrams make the very
common two-character word (`租約`, `逾時`, `決策`) match nothing. Bigrams are the
standard compromise for CJK lexical search and they compose: a four-character phrase
becomes three overlapping bigrams that a phrase query can require in order.

**Why it is computed in Python.** `to_tsvector` is `STABLE` rather than `IMMUTABLE`, so
PostgreSQL refuses it in a generated column; and a trigger would split "how is this
index computed" across two languages, which is precisely the state that lets the write
side and the read side drift apart.

The function is pure and has no I/O. That is not incidental — it is what allows the
query path to call it on user input without a database round trip.
"""

from __future__ import annotations

import re

# The CJK ranges that matter here: unified ideographs (plus extension A), the
# compatibility block, and kana. Deliberately not "everything non-ASCII": Cyrillic and
# Greek are alphabetic and are served correctly by the word rule below, and treating
# them as bigrams would make them *less* findable.
_CJK_RANGES = "㐀-䶿一-鿿豈-﫿぀-ヿ"
_CJK_RUN = re.compile(f"[{_CJK_RANGES}]+")
# A "word" for the ASCII side: letters, digits, and the three characters that hold
# identifiers together. `CV-05`, `lease_expires_at` and `v1.13.0` must each survive as
# one token, because they are exactly the queries the trigram channel is worst at
# guessing and the full-text channel is best at matching outright.
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
_SPLIT_ID = re.compile(r"[_.\-]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: Longest lexeme PostgreSQL will accept in a tsvector is 2047 bytes; anything near
#: that is not a word anyone will search for. Bounded here so a minified file that
#: escaped the exclude rules cannot produce a lexeme that fails the insert.
_MAX_LEXEME = 64


def lexemes(text: str) -> list[str]:
    """Lexemes for one piece of text, in encounter order, deduplicated.

    Three kinds come out:

    * **CJK bigrams** — ``租約過期`` → ``租約``, ``約過``, ``過期``. A run of one
      character yields none, which is deliberate and is reported to the caller by the
      query path (a single-character query degrades to the trigram channel and
      `KnowledgeSearch` says so rather than returning silence).
    * **ASCII words**, lowercased.
    * **Split identifiers** — ``lease_expires_at`` and ``LeaseExpiresAt`` both keep the
      original *and* gain ``lease``, ``expires``, ``at``. The original is kept because
      an exact search for it should rank higher than one that only matched the parts.

    Order is preserved so that a phrase query can be built from the same output, and
    duplicates are dropped so that a long document does not inflate one lexeme's weight
    purely by repetition — `ts_rank_cd` already accounts for frequency through position
    data we are not supplying.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        if not token or len(token) > _MAX_LEXEME or token in seen:
            return
        seen.add(token)
        out.append(token)

    for run in _CJK_RUN.finditer(text):
        span = run.group()
        for index in range(len(span) - 1):
            add(span[index : index + 2])

    for match in _WORD.finditer(text):
        word = match.group().lower()
        add(word)
        parts = [part for part in _SPLIT_ID.split(_CAMEL.sub(" ", match.group())) if part]
        if len(parts) > 1 or (parts and parts[0].lower() != word):
            for part in parts:
                for piece in part.split():
                    add(piece.lower())
    return out


def has_cjk(text: str) -> bool:
    """Whether the text contains anything the bigram rule applies to.

    Used by the query path to explain a degraded search: a one-character CJK query
    produces no bigram and therefore no full-text term, and the caller has to say so
    rather than return an empty page.
    """
    return _CJK_RUN.search(text) is not None


def document(text: str) -> str:
    """The space-joined lexeme string handed to ``to_tsvector('simple', …)``.

    ``simple`` and not ``english``: the tokens above were chosen deliberately, and
    stemming them again would turn ``expires`` into ``expir`` on one side of the system
    only if the other side ever stopped matching — the classic silent-mismatch bug this
    whole module is arranged to prevent.
    """
    return " ".join(lexemes(text))
