#!/usr/bin/env python
"""GATE-PX-MYWORK-READS-STATE — My Work reads facts, never "have you seen this".

This gate **replaces an exit condition that could not be written.** The upstream plan
asked for "marking notifications read does not change My Work's counts", and this system
has no notifications: no table, no endpoint, no read state. A test for that condition
would pass forever while asserting nothing, which is worse than no test — it makes the
next reader believe the boundary is guarded.

What the gate defends instead is the property the condition was really about: every
predicate behind My Work reads Task, Run and gate state, and none of them reads what a
person has *seen*. So when notifications do arrive, nobody wires them into a count.

**Comments and docstrings are stripped before matching.** The first version of this was a
`grep` and it matched its own explanatory paragraph — the failure `plan/18/09` §3 item 15
records, where the cheapest way to green a gate is to delete the sentence explaining it.

Run: uv run --project backend python scripts/px/gate_mywork_reads_state.py
"""

from __future__ import annotations

import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGETS = [
    ROOT / "backend/app/api/http/me.py",
    *sorted((ROOT / "backend/app/services/work").rglob("*.py")),
]

# Names that would mean "this person has seen it". `notification` is included because the
# first notification table is the moment this rule needs to be visible.
FORBIDDEN = re.compile(
    r"\b(read_at|seen_at|is_read|unread|dismissed_at|notification)\b"
)


def code_only(source: str) -> str:
    """The module with comments and string literals removed.

    Docstrings are string literals, so dropping `STRING` tokens removes them too — and
    that is wanted: a docstring naming the thing the rule forbids is documentation, not a
    read of it.
    """
    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


def main() -> int:
    offenders: list[str] = []
    for path in TARGETS:
        if not path.exists():  # pragma: no cover - the package always has these
            continue
        for match in FORBIDDEN.finditer(code_only(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.relative_to(ROOT)}: reads `{match.group(1)}`")
    if offenders:
        for line in offenders:
            print(line, file=sys.stderr)
        return 1
    print(f"        checked {len(TARGETS)} modules, comments and docstrings excluded")
    print("GATE-PX-MYWORK-READS-STATE: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
