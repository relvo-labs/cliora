#!/usr/bin/env python
"""GATE-RQ-HUMAN-ACTOR: the three "who decided" columns have one writer each.

**The most important gate in V2.5**, because the failure it guards is invisible in every
other signal. A second write site does not turn a test red: the row looks entirely
normal, the timestamps are plausible, the audit entry exists. What is wrong is that the
"person" recorded in it was not one.

The phase adds no outward surface and no execution capability (ADR 0034, Context), so
this — an agent's output being read as a person's decision — is the whole of its risk.

Static half. The dynamic half is
`backend/tests/db/test_clarification_and_decomposition.py::
test_no_agent_reachable_route_ever_writes_a_decider`, which walks **every** route in
`app.routes` with a run credential; the two are complementary, and the dynamic one is
what covers a route added by a later phase without anybody remembering this file.

Run: uv run --project backend python scripts/rq/gate_human_actor.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"

# Only constructors of **ORM models** count. A DTO that carries `decided_by` out to the
# browser is a read, and flagging it would train the next person to widen ALLOWED until
# the gate means nothing. Discovered from `db/models.py` rather than listed, because a
# new table with a decision column should be caught, not exempted by omission.
MODEL_CLASSES = {
    node.name
    for node in ast.parse((APP / "db" / "models.py").read_text(encoding="utf-8")).body
    if isinstance(node, ast.ClassDef)
}

# The columns whose value is a claim that a human decided something.
GUARDED = {"approved_by", "decided_by"}

# Where each may be written, as `module::function`. One entry per gate in ADR 0034 §6,
# plus the patch proposal's single decision path.
#
# **Written out rather than derived.** The point of the gate is that adding a writer is a
# decision somebody makes on purpose, and a rule that discovers writers automatically
# would approve the next one silently.
ALLOWED = {
    ("services/requirements.py", "approve"),  # specification approval
    ("services/requirements.py", "accept"),  # proposal acceptance
    ("services/requirements.py", "reject"),  # proposal rejection
    ("services/patches.py", "decide"),  # patch proposal accept/reject
}


def _enclosing_function(tree: ast.AST, node: ast.AST) -> str:
    """The name of the function a node sits in, or `<module>`."""
    best = "<module>"
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = getattr(candidate, "end_lineno", candidate.lineno)
        if candidate.lineno <= node.lineno <= end:
            best = candidate.name
    return best


def main() -> int:
    found: set[tuple[str, str]] = set()
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in GUARDED:
                    found.add((relative, _enclosing_function(tree, node)))
            # `Model(decided_by=...)` — the constructor form, which an assignment scan
            # alone would miss and which is how a row could be created pre-decided.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in MODEL_CLASSES and any(
                    keyword.arg in GUARDED for keyword in node.keywords
                ):
                    found.add((relative, _enclosing_function(tree, node)))

    unexpected = sorted(found - ALLOWED)
    missing = sorted(ALLOWED - found)
    if unexpected:
        print("a human-decision column is written somewhere it should not be:")
        for module, function in unexpected:
            print(f"  {module}::{function}")
        print("\nEvery one of these columns asserts that a person decided. Adding a")
        print("writer is a decision — add it to ALLOWED here and say why in the ADR.")
        return 1
    if missing:
        # Both directions: an entry that stops being a writer means the gate it named is
        # gone, and a gate that quietly disappeared is exactly what this file is for.
        print("an allowed writer no longer writes; did a human gate disappear?")
        for module, function in missing:
            print(f"  {module}::{function}")
        return 1
    print(f"human-decision columns: OK ({len(found)} writers, all expected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
