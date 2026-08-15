#!/usr/bin/env python
"""GATE-RQ-NO-PATCH-APPLY: the platform never applies a document patch.

"We already have the diff, let's add an apply button" is a natural next thought, and it
would pass every test in the suite — the proposal is there, the diff is there, and
applying it looks like a convenience. What it actually does is reintroduce general file
editing, which `plan/14` designed and had withdrawn (ADR 0034 §6).

AST rather than grep, because a grep for `open(` matches this sentence.

Run: uv run --project backend python scripts/rq/gate_no_patch_apply.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET = ROOT / "backend" / "app" / "services" / "patches.py"

FORBIDDEN_IMPORTS = {"os", "pathlib", "shutil", "subprocess", "tempfile", "io"}
FORBIDDEN_CALLS = {"open", "system", "run", "Popen", "write_text", "write_bytes"}


def main() -> int:
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    problems.append(f"line {node.lineno}: imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in FORBIDDEN_IMPORTS:
                problems.append(f"line {node.lineno}: imports from {node.module}")
        elif isinstance(node, ast.Call):
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if name in FORBIDDEN_CALLS:
                problems.append(f"line {node.lineno}: calls {name}()")

    if problems:
        print("the patch service reaches the filesystem:")
        for problem in problems:
            print(f"  {problem}")
        print("\nThe platform renders a patch and records a decision. Applying one goes")
        print("through an ordinary pull-request card, where it gets a reviewer.")
        return 1
    print("patch service: OK (no filesystem reach)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
