"""Three invariants of the run path, asserted by **parsing** rather than by grepping.

`GATE-AR-SINGLE-CLAIM`, `GATE-AR-NO-WORKSPACE-IN-RUNS` and
`GATE-AR-NO-REQUEST-IN-LOOP` (plan/18/08-…md §3/§4).

The first version of all three was a text scan, and all three failed **on their own
documentation**: `services/runs.py` opens by explaining why it must not call
`registry.request()` and why `authorize_workspace` is not imported, and
`uploaded_by_runner_id=` contains `runner_id=` as a substring.

That failure mode matters more than the inconvenience. A guard that finds its own
explanation is worse than no guard at all, because the cheapest way to make it green is
to delete the paragraph that says why the rule exists — and the next person then has a
rule with no reason attached. `ast` sees code and nothing else.

    python scripts/ar/gate_run_invariants.py

Exit code 1 with one line per violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "backend" / "app"


def _single_claim() -> list[str]:
    """Exactly one statement may assign `runner_id` a value.

    "A card cannot be claimed twice" rests entirely on one
    `UPDATE … WHERE runner_id IS NULL`. A second writer would fail no test — it would
    simply make the guarantee untrue — so the assertion is on the *count*.

    Only assignments of a bare name are counted. `run.decline` releases a run with
    `runner_id=None`, which is a different shape and deliberately not a claim.
    """
    writers: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "runner_id":
                if isinstance(node.value, ast.Name):
                    writers.append(
                        f"{path.relative_to(APP.parent)}:{node.value.lineno}"
                    )
    if len(writers) == 1:
        return []
    return [f"GATE-AR-SINGLE-CLAIM: {len(writers)} writers of runner_id: {writers}"]


def _no_workspace_in_runs() -> list[str]:
    """The queue service has no edge to workspace authorization.

    After the 2026-08-10 ruling a run does not use a workspace binding at all: it
    clones into a directory the daemon owns. That is what makes red line 2 apply to
    exactly one caller group again, and this keeps it that way.
    """
    tree = ast.parse((APP / "services" / "runs.py").read_text())
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    calls = {
        node.func.id
        if isinstance(node.func, ast.Name)
        else getattr(node.func, "attr", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    if "authorize_workspace" in names | calls:
        return ["GATE-AR-NO-WORKSPACE-IN-RUNS: runs.py reaches workspace authorization"]
    return []


def _no_request_in_loop() -> list[str]:
    """Nothing on the queue path awaits a node response.

    The node WebSocket loop resolves its own responses (`registry.py` ←
    `api/ws/nodes.py`), so awaiting one from inside a handler that loop invoked is a
    guaranteed timeout rather than a slow path. This is also why dispatch queues
    instead of reaching for a machine.
    """
    offenders: list[str] = []
    for name in ("runs.py", "runners.py"):
        tree = ast.parse((APP / "services" / name).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"request", "send_text_frame", "send_binary"}
            ):
                offenders.append(
                    f"GATE-AR-NO-REQUEST-IN-LOOP: services/{name}:{node.lineno}"
                )
    return offenders


def main() -> int:
    failures = _single_claim() + _no_workspace_in_runs() + _no_request_in_loop()
    for line in failures:
        print(line)
    if not failures:
        print(
            "run invariants hold: one claim writer, no workspace edge, no node request"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
