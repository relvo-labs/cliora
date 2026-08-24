#!/usr/bin/env python
"""The V2-P1 invariants whose violation is silent (`plan/26/10` §3).

Four gates in one file, because all four are AST scans over `backend/app` and one process
is cheaper than four. Each guards a property whose breach leaves the system running, the
tests green, and the answer quietly wrong:

* `GATE-PX-ONE-PROJECT-SCOPE` — every `select()` over `Task` inside `services/work/` takes
  its project predicate from a `ProjectScope`. Today the predicate is one line, so a
  second path would be *correct*; the gate is not defending today's behaviour, it is
  defending the count of places that have to change when per-project membership arrives
  (D93). On this deployment an isolation test proves nothing, and this is what SR-3 has
  instead.
* `GATE-PX-NO-DYNAMIC-SQL` — no `text()`, no f-string and no `+` concatenation reaching a
  query inside `services/work/`. The filter language is an allowlist with one compilation
  path per `(field, op)`; the value of the gate is that a reader auditing the two-phase
  attention split can trust it is the *only* place where SQL is not the whole answer.
* `GATE-PX-SINGLE-ATTENTION` — the eight levels and their order exist once. A second
  ordering in the browser or in a second service would be equal on the day it was written
  and would drift silently after.
* `GATE-PX-BULK-USES-UPDATE` — the bulk endpoint calls `TaskService.update_task` and
  contains no `update(Task)` of its own. **No existing gate covers this**:
  `GATE-DV-SINGLE-DONE-PATH` only scans `runs.py`, so a bulk statement written straight
  against the table would bypass the Done Gate, the dependency refusal, the optimistic
  lock, both audit trails and — the one the upstream plan missed — the knowledge outbox.

**AST rather than text search**, for the reason `plan/18/09` §3 item 15 records: V2.2
shipped three gates that matched their own explanatory comments, and the cheapest way to
green such a gate is to delete the paragraph saying why the rule exists.

Run: uv run --project backend python scripts/px/gate_work_invariants.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
WORK = APP / "services" / "work"
FRONTEND = ROOT / "frontend" / "src"

failures: list[str] = []
honoured: list[str] = []


def _modules(root: pathlib.Path) -> list[tuple[pathlib.Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(root.rglob("*.py"))
    ]


def _callee(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def _names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


# --- GATE-PX-ONE-PROJECT-SCOPE -----------------------------------------------
#
# The exemptions are **printed**, because an exemption nobody can see is how a rule
# quietly stops being one (the shape `scripts/kn/gates.sh` established).
_SCOPE_EXEMPT = {
    # Builds one project's rows for the read model. It is reached only through the
    # endpoints above, which have already narrowed the scope, and it takes a `Project`
    # object rather than an id — so there is no id here to check against a scope.
    ("rows.py", "for_project"),
    # Phase B's runner query. `AgentRunner` is not project-scoped data: a runner belongs
    # to a node, and any enrolled node's runner may claim any project's card (ADR 0029).
    ("rows.py", "runtime_signals"),
    # The rebalance and the neighbour lookups are writes to one already-authorised card.
    ("ranking.py", "*"),
}


def _gate_one_project_scope() -> None:
    for path, tree in _modules(WORK):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _callee(node) != "select":
                continue
            selected = _names(node)
            if "Task" not in selected:
                continue
            function = "<module>"
            for candidate in ast.walk(tree):
                if isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
                    end = getattr(candidate, "end_lineno", candidate.lineno)
                    if candidate.lineno <= node.lineno <= end:
                        function = candidate.name
            key = (path.name, function)
            if key in _SCOPE_EXEMPT or (path.name, "*") in _SCOPE_EXEMPT:
                honoured.append(
                    f"        exempt {_relative(path)}::{function} (project scope)"
                )
                continue
            # The statement is built by chained `.where()` calls, so the predicate may be
            # anywhere in the enclosing statement rather than inside the `select()` call.
            statement = None
            for candidate in ast.walk(tree):
                if isinstance(candidate, ast.Expr | ast.Assign | ast.Return):
                    end = getattr(candidate, "end_lineno", candidate.lineno)
                    if candidate.lineno <= node.lineno <= end:
                        statement = candidate
                        break
            names = _names(statement) if statement is not None else set()
            if "predicate" not in names:
                failures.append(
                    f"GATE-PX-ONE-PROJECT-SCOPE: {_relative(path)}::{function} selects Task "
                    "without a ProjectScope.predicate() in the same statement"
                )


# --- GATE-PX-NO-DYNAMIC-SQL --------------------------------------------------


# One `text()` is allowed, and it is named rather than pattern-matched. `views.py`'s seed
# is a fixed `INSERT … SELECT` with bind parameters and no interpolation — it exists as a
# string because it has to be executable from both an Alembic connection and an
# `AsyncSession`, which the ORM cannot express in one object.
_SQL_EXEMPT = {("views.py", "text")}


def _gate_no_dynamic_sql() -> None:
    for path, tree in _modules(WORK):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee(node) == "text":
                if (path.name, "text") in _SQL_EXEMPT:
                    honoured.append(
                        f"        exempt {_relative(path)}:{node.lineno} text() "
                        "(fixed statement, bind parameters only)"
                    )
                    continue
                failures.append(
                    f"GATE-PX-NO-DYNAMIC-SQL: {_relative(path)}:{node.lineno} calls text()"
                )
            if isinstance(node, ast.JoinedStr):
                # An f-string is fine for a message; it is not fine near a query. The
                # signal is the surrounding statement mentioning a query builder.
                for candidate in ast.walk(tree):
                    if not isinstance(candidate, ast.Call):
                        continue
                    if _callee(candidate) not in {
                        "where",
                        "select",
                        "execute",
                        "order_by",
                    }:
                        continue
                    end = getattr(candidate, "end_lineno", candidate.lineno)
                    if candidate.lineno <= node.lineno <= end:
                        failures.append(
                            f"GATE-PX-NO-DYNAMIC-SQL: {_relative(path)}:{node.lineno} "
                            "builds an f-string inside a query call"
                        )


# --- GATE-PX-SINGLE-ATTENTION ------------------------------------------------


def _gate_single_attention() -> None:
    defining = [
        _relative(path)
        for path, tree in _modules(APP)
        for node in ast.walk(tree)
        # `AnnAssign` as well as `Assign`: the definition carries a type annotation, and
        # a scan that only saw bare assignments would report "defined nowhere" — which
        # reads as a pass in the wrong direction.
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ATTENTION_ORDER"
                for target in node.targets
            )
        )
        or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "ATTENTION_ORDER"
        )
    ]
    if defining != ["backend/app/services/work/attention.py"]:
        failures.append(
            "GATE-PX-SINGLE-ATTENTION: ATTENTION_ORDER is defined in "
            f"{defining or 'nowhere'}; it must exist only in services/work/attention.py"
        )
    # The browser has its own presentation table, which is legitimate — what it must not
    # have is a second *ordering*. `frontend/src/modules/work/attention.ts` holds the
    # levels for iteration and its own test restates the server's order to compare
    # against; a `sort` over them would be a second product decision.
    presentation = FRONTEND / "modules" / "work" / "attention.ts"
    if presentation.exists():
        text = presentation.read_text(encoding="utf-8")
        if ".sort(" in text or "localeCompare" in text:
            failures.append(
                "GATE-PX-SINGLE-ATTENTION: frontend/src/modules/work/attention.ts sorts "
                "the levels; the order is the server's"
            )
        else:
            honoured.append(
                "        checked frontend/src/modules/work/attention.ts (no sort)"
            )


# --- GATE-PX-BULK-USES-UPDATE ------------------------------------------------


def _gate_bulk_uses_update() -> None:
    path = APP / "api" / "http" / "work.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    target = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == "bulk_update"
        ):
            target = node
    if target is None:
        failures.append("GATE-PX-BULK-USES-UPDATE: no bulk_update in api/http/work.py")
        return
    calls = [_callee(node) for node in ast.walk(target) if isinstance(node, ast.Call)]
    if "update_task" not in calls:
        failures.append(
            "GATE-PX-BULK-USES-UPDATE: bulk_update does not call TaskService.update_task"
        )
    for node in ast.walk(target):
        if isinstance(node, ast.Call) and _callee(node) in {"update", "text", "delete"}:
            if _callee(node) == "update" and "Task" in _names(node):
                failures.append(
                    "GATE-PX-BULK-USES-UPDATE: bulk_update builds its own UPDATE against "
                    "Task; every card must go through TaskService.update_task"
                )
            if _callee(node) == "text":
                failures.append("GATE-PX-BULK-USES-UPDATE: bulk_update uses raw SQL")


def main() -> int:
    _gate_one_project_scope()
    _gate_no_dynamic_sql()
    _gate_single_attention()
    _gate_bulk_uses_update()
    for line in honoured:
        print(line)
    for line in failures:
        print(line, file=sys.stderr)
    if failures:
        return 1
    print(
        "GATE-PX-{ONE-PROJECT-SCOPE,NO-DYNAMIC-SQL,SINGLE-ATTENTION,BULK-USES-UPDATE}: OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
