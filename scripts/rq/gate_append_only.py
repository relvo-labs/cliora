#!/usr/bin/env python
"""GATE-RQ-APPEND-ONLY: the three proposal tables are insert-only.

`feature_specs`, `task_proposals` and `document_patch_proposals` are version rows and
decision rows. An in-place rewrite changes what a person looked at when they decided —
which is the one thing a record of a decision must not do (ADR 0027's rule for
`execution_plans`, extended here).

**Decision columns are the exception, and they are enumerated**: a proposal's status,
who decided it, when, and their note. Everything else is written once.

The check is a bulk-`UPDATE` scan rather than an ORM-mutation scan: the ORM assignments
this phase makes are exactly the decision columns, and they are covered by
`gate_human_actor.py`. What this catches is the other shape — a `sa.update(FeatureSpec)`
somewhere that rewrites a version in place.

Run: uv run --project backend python scripts/rq/gate_append_only.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"

APPEND_ONLY = {"FeatureSpec", "TaskProposal", "DocumentPatchProposal"}


def main() -> int:
    problems: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name not in {"update", "delete"}:
                continue
            for argument in node.args:
                if isinstance(argument, ast.Name) and argument.id in APPEND_ONLY:
                    problems.append(
                        f"{relative}:{node.lineno} {name}({argument.id}) — these tables only INSERT"
                    )

    if problems:
        print("an append-only table is rewritten in bulk:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"append-only tables: OK ({len(APPEND_ONLY)} tables, no bulk update or delete)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
