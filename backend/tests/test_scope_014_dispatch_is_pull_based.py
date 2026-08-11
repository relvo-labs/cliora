"""SCOPE-014.AC-04: dispatch is pull-based; the platform assigns nothing (ADR 0027).

Red line 4 ("no git automation, no task routing") was withdrawn and replaced by four
constraints. Three of them are about git and have no code until V2.3, so they stay
`proposed`. **This one is true today and can be guarded today**, which is why it is
the one criterion of SCOPE-014 that goes `active` in V2.0.

The distinction the constraint draws is easy to lose later: what was withdrawn is
"a task may be *claimed* by an agent", not "the platform decides who does what". An
endpoint that pushes work to a named runner would erase it — so the guard is that no
such endpoint exists at all, asserted against the mounted route table rather than
against anyone's memory of the rule.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.test_authz import ROUTE_ACTIONS, mounted_routes

BACKEND = Path(__file__).resolve().parents[1] / "app"

# Words that would name a push at a *named machine*. `dispatch` left this list in V2.2:
# `POST /api/tasks/{id}/dispatch` queues a card and returns, and a runner only ever
# acquires it by polling. `claim` and `poll` were always absent, for the same reason —
# they are the permitted pull-side verbs.
_PUSH = re.compile(r"(assign|schedule|route-to|push-to)", re.I)
# A path that names a runner *and* a work verb would be the forbidden shape spelled a
# different way: `POST /api/agents/{id}/tasks`, `POST /api/agents/{id}/run`.
_RUNNER_WORK = re.compile(r"/agents?/\{[^}]+\}/(tasks?|runs?|work|jobs?)", re.I)


def test_no_route_pushes_work_to_a_runner() -> None:
    offenders = sorted(
        f"{method} {path}"
        for method, path in mounted_routes()
        if _PUSH.search(path) or _RUNNER_WORK.search(path)
    )
    assert offenders == [], (
        "SCOPE-014.AC-04: the platform must not expose a path that assigns work. "
        f"Found: {offenders}. Claiming is pull-side and belongs on the daemon's poll, "
        "not on an HTTP endpoint that names a runner."
    )


def test_dispatch_queues_and_never_reaches_a_node() -> None:
    """The half of AC-04 that a route table cannot show.

    `POST /api/tasks/{id}/dispatch` is allowed to exist because of what it does *not*
    do: it inserts a `queued` row and answers 202. If it ever sent a frame to a node —
    `registry.send_text_frame`, `send_binary` or `request` — the platform would have
    started choosing machines, and the pull model would be a fiction maintained only
    in the documentation.

    Parsed rather than grepped: the module's own docstring explains why it must not
    call these, and a text scan would find its own explanation. `ast` sees calls only.
    """
    tree = ast.parse((BACKEND / "services" / "runs.py").read_text())
    forbidden = {"request", "send_text_frame", "send_binary"}
    offenders = sorted(
        {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden
        }
    )
    assert offenders == [], (
        f"services/runs.py reaches a node: {offenders}. Dispatch queues; the runner "
        "polls. This is also the deadlock guard — the node WebSocket loop resolves its "
        "own responses, so awaiting one from inside it can only time out."
    )


def test_the_route_matrix_names_no_assignment_action() -> None:
    """The same claim from the authorization side.

    A push endpoint would need an action to guard it, so an action whose name means
    "assign" is the other way this constraint could quietly acquire an exception.
    """
    actions = {action for action in ROUTE_ACTIONS.values() if action}
    offenders = sorted(action for action in actions if _PUSH.search(action))
    assert offenders == [], f"SCOPE-014.AC-04: assignment-shaped action(s): {offenders}"


def test_the_runner_registry_records_capacity_and_never_an_assignment() -> None:
    """The tripwire fired in V2.2, and this is what replaced it.

    Until V2.2 the strongest form of this constraint was that no runner concept existed
    at all. It exists now, so the guard moves from "no such table" to the property that
    table has to keep: **a runner row says what a machine can do, never what it has
    been told to do.** A column naming a queue, a task or an assignment on
    `agent_runners` would be an assignment stored on the runner — the push model with
    the endpoint left out.

    The card's own `assigned_runner_id` is deliberately *not* covered by this: it is a
    filter in that runner's poll query, and it lives on the card and on the run, which
    is where a person's preference belongs.
    """
    from app.db.models import AgentRunner

    columns = set(AgentRunner.__table__.columns.keys())
    offenders = sorted(
        column for column in columns if re.search(r"(assigned|queue|current_task|pending)", column)
    )
    assert offenders == [], (
        f"SCOPE-014.AC-04: `agent_runners` grew {offenders}. A runner row states "
        "capability and capacity; work is claimed, not stored against a machine."
    )
    # The capability half, positively: this is what the row is for.
    assert {"runtimes", "max_concurrent", "max_waiting", "enabled"} <= columns
