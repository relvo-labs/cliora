#!/usr/bin/env python3
"""Four V2.3 invariants that no test would otherwise notice being broken.

Each of these guards a property whose violation is **silent**: the code still runs, the
tests still pass, and the thing that changed is a promise nobody re-reads.

* `GATE-SC-SINGLE-DECRYPT` — exactly one module turns a stored secret back into
  plaintext. Every additional caller is another path a security review has to trace, and
  they arrive as one-line conveniences.
* `GATE-SC-TAG-BOTH-QUERIES` — both eligibility paths call the shared predicate. Change
  one and not the other and the queue behaves one way while the console explains the
  other, with nothing red.
* `GATE-SC-NO-PLAINTEXT-COLUMN` — the secrets table has no column that could hold a
  value. Guards the "store it in plain text for now" change, which has no way back.
* `GATE-SC-NO-BINDING-PROMISE` — no code still promises `project_agents`. That table was
  cancelled, and the promises were sitting in `rbac.py` and the API docstrings where a
  security review reads them.

**All four use `ast` rather than text search**, and that is not fastidiousness: V2.2 shipped
three gates that matched their own explanatory comments, and the cheapest way to make such
a gate green is to delete the paragraph saying why the rule exists (plan/18/09 §3 item 15).
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"

failures: list[str] = []


def fail(gate: str, detail: str) -> None:
    failures.append(f"{gate}: {detail}")


def calls(tree: ast.AST) -> set[str]:
    """Every callee name in a module, dotted form included."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            found.add(target.id)
        elif isinstance(target, ast.Attribute):
            parts = []
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                parts.append(target.id)
            found.add(".".join(reversed(parts)))
    return found


# --- GATE-SC-SINGLE-DECRYPT -------------------------------------------------
decrypters: list[str] = []
for path in sorted(APP.rglob("*.py")):
    if path.name == "secret_envelope.py":
        continue
    tree = ast.parse(path.read_text(), filename=str(path))
    names = calls(tree)
    if {"unseal", "secret_envelope.unseal", "rewrap", "secret_envelope.rewrap"} & names:
        decrypters.append(str(path.relative_to(ROOT)))

if decrypters != ["backend/app/services/secrets.py"]:
    fail(
        "GATE-SC-SINGLE-DECRYPT",
        "exactly one module may decrypt a project secret; found "
        + (", ".join(decrypters) if decrypters else "none"),
    )

# --- GATE-SC-TAG-BOTH-QUERIES -----------------------------------------------
runs = ast.parse((APP / "services" / "runs.py").read_text())
functions = {
    node.name: node
    for node in ast.walk(runs)
    if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
}
for name, predicate in (
    ("_eligible", "tag_match_clause"),
    ("_online_candidates", "tag_match"),
):
    node = functions.get(name)
    if node is None:
        fail("GATE-SC-TAG-BOTH-QUERIES", f"{name} no longer exists; the pairing is unchecked")
        continue
    if predicate not in calls(node):
        fail(
            "GATE-SC-TAG-BOTH-QUERIES",
            f"{name} does not call {predicate}; the two eligibility paths can now drift, "
            "and the symptom is a console that explains something the queue does not do",
        )

# --- GATE-SC-NO-PLAINTEXT-COLUMN --------------------------------------------
migration = (APP / "db" / "migrations" / "versions" / "0033_project_secrets.py").read_text()
table = migration.split('op.create_table(\n        "project_secrets"', 1)
if len(table) != 2:
    fail("GATE-SC-NO-PLAINTEXT-COLUMN", "the project_secrets table was not found in 0033")
else:
    body = table[1].split("op.create_index", 1)[0]
    columns = set(re.findall(r'sa\.Column\(\s*"([a-z_]+)"', body))
    forbidden = {
        column
        for column in columns
        if ("value" in column and not column.endswith(("_encrypted", "_nonce")))
        or column in {"plain", "raw", "plaintext", "secret"}
    }
    if forbidden:
        fail(
            "GATE-SC-NO-PLAINTEXT-COLUMN",
            f"project_secrets has {sorted(forbidden)}; a column that can hold a value is "
            "the change with no way back — the plaintext already written stays written",
        )

# --- GATE-SC-NO-BINDING-PROMISE ---------------------------------------------
# `project_agents` was cancelled on 2026-08-12, not deferred. A comment still saying it
# is coming misleads exactly where it matters — `rbac.py` and the API docstrings are
# what a security review reads.
#
# Migrations are excluded: they are a historical record, and 0029 carries a dated note
# rather than a rewrite.
PROMISE = re.compile(
    r"project_agents[^\n]*?(V2\.3|arrives|will arrive|起提供|即將)", re.IGNORECASE
)
for root, patterns in ((APP, "*.py"), (ROOT / "frontend" / "src", "*.*"), (ROOT / "daemon", "*.go")):
    for path in sorted(root.rglob(patterns)):
        if "migrations" in path.parts or path.suffix not in {".py", ".ts", ".vue", ".go"}:
            continue
        for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if PROMISE.search(line):
                fail(
                    "GATE-SC-NO-BINDING-PROMISE",
                    f"{path.relative_to(ROOT)}:{number} still promises project_agents",
                )

if failures:
    for line in failures:
        print(f"FAIL  {line}", file=sys.stderr)
    sys.exit(1)
print("secret invariants: OK (4 gates)")
