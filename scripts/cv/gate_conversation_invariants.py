#!/usr/bin/env python
"""The V2-C1 invariants whose violation is silent (`plan/23/08-…md` §3).

Four gates in one file, because all four are AST scans over `backend/app` and running
one process is cheaper than four:

* `GATE-CV-PROJECTION-ONE-WRITER` — `tasks.waiting_for_actor` and
  `tasks.open_question_count` are assigned in exactly one function. A second writer's
  first missed branch shows a card that says "waiting for your reply" after the reply
  arrived, and **nothing errors**.
* `GATE-CV-CONTINUATION-REFUSALS` — the card-level dispatch refusals are raised in
  exactly one function, so a continuation cannot bypass them. The card is editable
  while it waits; a clarification card that gained a secret between turns would
  otherwise carry it into the next run.
* `GATE-CV-APPEND-ONLY` — `task_messages` has no update path. A message that can be
  rewritten in place is not a record of what was said.
* `GATE-CV-NO-CLIENT-WAITING-DERIVATION` — the browser does not infer waiting state
  from the last message's kind. That guess is what V2.5's panel did, and it was wrong
  in both directions.

**AST rather than text search**, for the reason `plan/18/09` §3 item 15 records: V2.2
shipped three gates that matched their own explanatory comments, and the cheapest way
to make such a gate green is to delete the paragraph saying why the rule exists.

Run: uv run --project backend python scripts/cv/gate_conversation_invariants.py
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
FRONTEND = ROOT / "frontend" / "src"

failures: list[str] = []


def _enclosing(tree: ast.AST, node: ast.AST) -> str:
    best = "<module>"
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = getattr(candidate, "end_lineno", candidate.lineno)
        if candidate.lineno <= node.lineno <= end:
            best = candidate.name
    return best


def _modules() -> list[tuple[pathlib.Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(APP.rglob("*.py"))
    ]


# --- GATE-CV-PROJECTION-ONE-WRITER ------------------------------------------
#
# Written out rather than derived: the point is that adding a writer is a decision
# somebody makes on purpose, and a rule that discovers writers automatically would
# approve the next one silently.
PROJECTION_COLUMNS = {"waiting_for_actor", "open_question_count"}
PROJECTION_WRITERS = {("services/conversation.py", "_reproject")}


def check_projection_one_writer(modules: list[tuple[pathlib.Path, ast.Module]]) -> None:
    offenders: set[str] = set()
    for path, tree in modules:
        relative = path.relative_to(APP).as_posix()
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if not isinstance(target, ast.Attribute):
                    continue
                if target.attr not in PROJECTION_COLUMNS:
                    continue
                where = (relative, _enclosing(tree, node))
                if where not in PROJECTION_WRITERS:
                    offenders.add(f"{where[0]}::{where[1]} assigns {target.attr}")
            # `update(Task).values(waiting_for_actor=…)` is the other way to write one.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr != "values":
                    continue
                for keyword in node.keywords:
                    if keyword.arg in PROJECTION_COLUMNS:
                        where = (relative, _enclosing(tree, node))
                        if where not in PROJECTION_WRITERS:
                            offenders.add(
                                f"{where[0]}::{where[1]} updates {keyword.arg}"
                            )
    if offenders:
        failures.append(
            "GATE-CV-PROJECTION-ONE-WRITER: the board projection has more than one "
            "writer:\n  " + "\n  ".join(sorted(offenders))
        )


# --- GATE-CV-CONTINUATION-REFUSALS ------------------------------------------
#
# The six codes that refuse a *card* (as opposed to refusing to start new work). They
# must be raised from the extracted helper only, so that `dispatch` and
# `enqueue_continuation` cannot drift apart — and the direction they drift is always
# "the continuation's copy is the older one".
CARD_REFUSALS = {
    "TASK_KIND_FORBIDS_SECRETS",
    "TASK_KIND_NEEDS_REQUIREMENT",
    "TASK_KIND_DELIVERY_NOT_ALLOWED",
    "TASK_MOCKUP_INTEGRATION_DISABLED",
    "TASK_SECRETS_NOT_ALLOWED",
    "TASK_SECRETS_MISSING",
}
REFUSAL_HOME = ("services/runs.py", "_assert_card_dispatchable")
REFUSAL_CALLERS = {"dispatch", "enqueue_continuation"}

# Two exemptions, and each is a *different* use of the same string rather than a second
# copy of the same refusal.
#
# `error_catalog.py` documents every code; flagging it would train the next person to
# widen the allowlist until the gate means nothing (the reasoning `gate_human_actor.py`
# applies to DTOs).
#
# The two agent read routes answer "this card has no requirement to read", which is a
# lookup failing rather than a dispatch being refused. They are listed rather than
# pattern-matched so that a *third* one has to be added here on purpose.
REFUSAL_EXEMPT = {
    ("api/error_catalog.py", "<module>"),
    ("api/http/agents.py", "_run_requirement"),
    ("api/http/agents.py", "agent_read_requirement"),
}


def check_continuation_refusals(modules: list[tuple[pathlib.Path, ast.Module]]) -> None:
    offenders: set[str] = set()
    for path, tree in modules:
        relative = path.relative_to(APP).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if node.value not in CARD_REFUSALS:
                continue
            where = (relative, _enclosing(tree, node))
            if where != REFUSAL_HOME and where not in REFUSAL_EXEMPT:
                offenders.add(f"{where[0]}::{where[1]} raises {node.value}")
    if offenders:
        failures.append(
            "GATE-CV-CONTINUATION-REFUSALS: a card refusal lives outside "
            f"{REFUSAL_HOME[0]}::{REFUSAL_HOME[1]}:\n  " + "\n  ".join(sorted(offenders))
        )
        return

    # The static half above proves the refusals are in one place. It does **not** prove
    # the continuation path calls it — a continuation that simply never did would pass.
    runs = ast.parse((APP / "services" / "runs.py").read_text(encoding="utf-8"))
    callers: set[str] = set()
    for node in ast.walk(runs):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == REFUSAL_HOME[1]:
            callers.add(_enclosing(runs, node))
    missing = REFUSAL_CALLERS - callers
    if missing:
        failures.append(
            "GATE-CV-CONTINUATION-REFUSALS: these do not run the card refusals: "
            + ", ".join(sorted(missing))
        )


# --- GATE-CV-APPEND-ONLY ----------------------------------------------------
#
# `task_questions` is the whitelist: its `state` and two `answered_*` columns are the
# compare-and-set, and that is the only in-place write this phase adds.
APPEND_ONLY_MODELS = {"TaskMessage"}


def check_append_only(modules: list[tuple[pathlib.Path, ast.Module]]) -> None:
    offenders: set[str] = set()
    for path, tree in modules:
        relative = path.relative_to(APP).as_posix()
        if relative.startswith("db/migrations/"):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "update" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id in APPEND_ONLY_MODELS:
                offenders.add(f"{relative}::{_enclosing(tree, node)} updates {first.id}")
    if offenders:
        failures.append(
            "GATE-CV-APPEND-ONLY: a message is rewritten in place:\n  "
            + "\n  ".join(sorted(offenders))
        )


# --- GATE-CV-NO-CLIENT-WAITING-DERIVATION -----------------------------------
#
# Text rather than AST: the frontend is TypeScript, and the shape being forbidden is a
# recognisable idiom rather than a call. Narrow on purpose — it matches "the last
# message's kind decides", not any mention of `question`.
CLIENT_GUESS = re.compile(
    r"(reverse\(\)[\s\S]{0,200}?kind\s*===\s*[\"']question[\"'])"
    r"|(last\??\.kind\s*===\s*[\"']question[\"'])",
)


def check_no_client_waiting_derivation() -> None:
    offenders = [
        path.relative_to(FRONTEND).as_posix()
        for path in sorted(FRONTEND.rglob("*.vue"))
        if CLIENT_GUESS.search(path.read_text(encoding="utf-8"))
    ]
    offenders += [
        path.relative_to(FRONTEND).as_posix()
        for path in sorted(FRONTEND.rglob("*.ts"))
        if not path.name.endswith(".test.ts")
        and CLIENT_GUESS.search(path.read_text(encoding="utf-8"))
    ]
    if offenders:
        failures.append(
            "GATE-CV-NO-CLIENT-WAITING-DERIVATION: the browser is guessing waiting "
            "state from the thread:\n  " + "\n  ".join(offenders)
        )


def main() -> int:
    modules = _modules()
    check_projection_one_writer(modules)
    check_continuation_refusals(modules)
    check_append_only(modules)
    check_no_client_waiting_derivation()
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(
        "conversation invariants: OK "
        "(one projection writer, one refusal site, no message update, no client guess)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
