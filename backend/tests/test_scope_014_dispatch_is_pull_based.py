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

import re

from tests.test_authz import ROUTE_ACTIONS, mounted_routes

# Words that would name a push. `dispatch` and `assign` are the two the design
# documents use for the refused shape; `claim` and `poll` are deliberately absent
# from this list, because those are the *permitted* pull-side verbs V2.2 will add.
_PUSH = re.compile(r"(dispatch|assign|schedule|route-to|push-to)", re.I)


def test_no_route_pushes_work_to_a_runner() -> None:
    offenders = sorted(
        f"{method} {path}" for method, path in mounted_routes() if _PUSH.search(path)
    )
    assert offenders == [], (
        "SCOPE-014.AC-04: the platform must not expose a path that assigns work. "
        f"Found: {offenders}. Claiming is pull-side and belongs on the daemon's poll, "
        "not on an HTTP endpoint that names a runner."
    )


def test_the_route_matrix_names_no_assignment_action() -> None:
    """The same claim from the authorization side.

    A push endpoint would need an action to guard it, so an action whose name means
    "assign" is the other way this constraint could quietly acquire an exception.
    """
    actions = {action for action in ROUTE_ACTIONS.values() if action}
    offenders = sorted(action for action in actions if _PUSH.search(action))
    assert offenders == [], f"SCOPE-014.AC-04: assignment-shaped action(s): {offenders}"


def test_central_holds_no_runner_registry_yet() -> None:
    """V2.0 has no runner concept at all, which is the strongest form of this
    constraint — and a useful tripwire: when V2.2 adds one, this test fails and
    forces the other three SCOPE-014 criteria to be looked at rather than inherited.
    """
    from app.db import models

    runner_tables = [
        name
        for name in dir(models)
        if not name.startswith("_") and re.search(r"runner|dispatch", name, re.I)
    ]
    assert runner_tables == [], (
        f"a runner model appeared: {runner_tables}. V2.2 is where that belongs — and "
        "when it does, SCOPE-014.AC-01..03 need their own gates before they go active."
    )
