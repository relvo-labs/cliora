"""Splitting a source into retrievable pieces (plan/25/03-…md §9, D84).

Two numbers and one rule:

* **800 tokens with 100 of overlap.** Both are guesses, and they are recorded as
  guesses in `plan/25/10-open-measurements.md` — the value that makes retrieval best
  cannot be known before there is a relevance baseline to compare against. Changing
  them later costs a re-ingest and no migration, because chunk keys are stable.
* **The key is an ordinal, never a content hash.** A hash would make "a sentence was
  added at the top" mean every chunk downstream is new, and the whole GIN index gets
  rebuilt for a typo.

Token counts are approximated from characters rather than measured with a tokenizer
library, because `backend/pyproject.toml` gaining a dependency is the thing SR-2's
"Central added no outbound connection" is evidenced by, and a package that does not
connect anywhere still makes that evidence need a paragraph of explanation. The
approximation only decides *where to cut*; every real budget in this phase is counted
in bytes, because the wire and HTTP limits are in bytes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.services.knowledge.tokenize import _CJK_RANGES  # noqa: PLC2701 - one owner of the ranges

DEFAULT_CHUNK_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 100

_CJK_CHAR = re.compile(f"[{_CJK_RANGES}]")
# Preferred cut points, best first. A paragraph break beats a sentence end beats a line
# break; a hard cut is the last resort and is what the overlap exists to soften.
_PARAGRAPH = re.compile(r"\n\s*\n")
# Two rules, because the two writing systems punctuate differently. CJK sentences are
# not followed by a space, so an ASCII-shaped rule that requires one means a
# two-thousand-character Chinese paragraph never splits at all. ASCII *does* require the
# space, so that `v1.13.0` and `docs/adr/0035-x.md` survive as single tokens.
_SENTENCE = re.compile(r"(?<=[。！？])|(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    key: str
    content: str
    token_count: int

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def approx_tokens(text: str) -> int:
    """A character-based estimate: one CJK character ≈ one token, four ASCII ≈ one.

    Deliberately crude. It is used to decide where to cut and nothing else — see the
    module docstring for why no tokenizer package is installed for this.
    """
    if not text:
        return 0
    cjk = len(_CJK_CHAR.findall(text))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def _segments(text: str) -> list[str]:
    """Paragraphs, then sentences inside an over-long paragraph, then raw lines."""
    out: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if approx_tokens(paragraph) <= DEFAULT_CHUNK_TOKENS:
            out.append(paragraph)
            continue
        for sentence in _SENTENCE.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if approx_tokens(sentence) <= DEFAULT_CHUNK_TOKENS:
                out.append(sentence)
            else:
                out.extend(line for line in sentence.splitlines() if line.strip())
    return out


def chunk(
    text: str,
    *,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split text into chunks, keyed by ordinal.

    A source shorter than one chunk — which is most of them: a conversation message, an
    evidence item, a card's fields — comes back as exactly one chunk with key ``0000``.
    That is not a special case in the code, and it should not become one: the
    single-chunk path and the many-chunk path have to produce identical keys for
    identical input, or a source that grows past the threshold would orphan its first
    chunk instead of updating it.
    """
    text = (text or "").strip()
    if not text:
        return []
    segments = _segments(text)
    if not segments:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for segment in segments:
        segment_tokens = approx_tokens(segment)
        if current and current_tokens + segment_tokens > max_tokens:
            chunks.append("\n\n".join(current))
            # Carry the tail of the previous chunk forward so a sentence that spans a
            # boundary is still findable as a whole in at least one chunk.
            carried: list[str] = []
            carried_tokens = 0
            for previous in reversed(current):
                previous_tokens = approx_tokens(previous)
                if carried_tokens + previous_tokens > overlap_tokens:
                    break
                carried.insert(0, previous)
                carried_tokens += previous_tokens
            current = carried
            current_tokens = carried_tokens
        current.append(segment)
        current_tokens += segment_tokens
    if current:
        chunks.append("\n\n".join(current))

    # Last resort. A segment with no paragraph break, no sentence end and no newline — a
    # minified file that escaped the exclude rules, a base64 blob pasted into a
    # description — would otherwise become one chunk of unbounded size, and a single
    # oversized chunk consumes the whole retrieved budget the moment it matches
    # anything. Cut on characters rather than tokens: the point here is a bound, not a
    # boundary, and a bound that needs an estimate to be right is not a bound.
    limit = max_tokens * 4
    bounded: list[str] = []
    for body in chunks:
        if approx_tokens(body) <= max_tokens * 2:
            bounded.append(body)
            continue
        bounded.extend(body[start : start + limit] for start in range(0, len(body), limit))

    return [
        Chunk(key=f"{index:04d}", content=body, token_count=approx_tokens(body))
        for index, body in enumerate(bounded)
    ]
