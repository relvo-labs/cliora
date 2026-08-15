#!/usr/bin/env python
"""GATE-RQ-CONTEXT-DISPATCH: the context pack is chosen in exactly one place.

Two renderers exist rather than one with a flag, and the choice between them is made in
`RunService._context_for` and nowhere else (ADR 0034 §3).

The failure this guards is silent and specific: a second branch's first missed kind
hands a clarification card the *implementation* pack — whose "environment variables
available to this run" section is a **false sentence**, because that kind of card is
refused secrets at dispatch. Nothing would fail; the agent would simply be told
something untrue.

Asserted by call site rather than by grepping for `card_kind`, because `dispatch()`
legitimately branches on the kind four times for its refusals. What must be unique is
who calls the renderers.

Run: uv run --project backend python scripts/rq/gate_context_dispatch.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"

RENDERERS = {
    "render_run_context",
    "render_clarification_context",
    "render_decomposition_context",
}
# The one function allowed to call them. Tests call them directly and are not scanned.
CHOOSER = "_context_for"


def main() -> int:
    callers: dict[str, set[str]] = {name: set() for name in RENDERERS}
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in RENDERERS:
                continue
            enclosing = "<module>"
            for candidate in functions:
                end = getattr(candidate, "end_lineno", candidate.lineno)
                if candidate.lineno <= node.lineno <= end:
                    enclosing = candidate.name
            callers[node.func.id].add(f"{path.relative_to(APP).as_posix()}::{enclosing}")

    problems = [
        f"{renderer} is called from {sorted(sites)}"
        for renderer, sites in callers.items()
        if sites and sites != {f"services/runs.py::{CHOOSER}"}
    ]
    if problems:
        print("the context pack is chosen in more than one place:")
        for problem in problems:
            print(f"  {problem}")
        print(f"\nAll three renderers must be reached only through {CHOOSER}.")
        return 1
    print("context pack dispatch: OK (one chooser)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
