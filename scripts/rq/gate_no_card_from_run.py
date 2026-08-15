#!/usr/bin/env python
"""GATE-RQ-NO-CARD-FROM-RUN: submitting a proposal never creates a card.

D28's central rule — an agent proposes, a person creates — needs an assertion against
the *code* rather than against behaviour, because an implementation that also created
cards would pass every test in the suite: the proposal exists, the cards exist, and the
two agree. What breaks is "a person looked at it", and that has no runtime shape.

Two claims:

1. `RequirementService.propose` does not reach `TaskService.create_task`;
2. the route that a run credential calls (`agent_submit_proposal`) reaches only
   `propose`.

Run: uv run --project backend python scripts/rq/gate_no_card_from_run.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"

FORBIDDEN_CALLS = {"create_task", "create_epic", "create_story"}
TARGETS = [
    ("services/requirements.py", "propose"),
    ("api/http/agents.py", "agent_submit_proposal"),
]


def _function(path: pathlib.Path, name: str) -> ast.AST | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def main() -> int:
    problems: list[str] = []
    for relative, name in TARGETS:
        path = APP / relative
        function = _function(path, name)
        if function is None:
            problems.append(f"{relative}::{name} no longer exists")
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            called = ""
            if isinstance(node.func, ast.Attribute):
                called = node.func.attr
            elif isinstance(node.func, ast.Name):
                called = node.func.id
            if called in FORBIDDEN_CALLS:
                problems.append(f"{relative}::{name} calls {called}() at line {node.lineno}")

    if problems:
        print("the proposal path creates cards:")
        for problem in problems:
            print(f"  {problem}")
        print("\nA proposal is not a card. Accepting one is what creates cards, and that")
        print("route requires `task.approve` — which a run credential never holds.")
        return 1
    print("proposal path: OK (creates no cards)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
