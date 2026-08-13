"""GATE-AR-DISPATCH-COVERAGE: every run message has a branch that handles it.

`node_gateway`'s control loop is an `if/elif` chain whose **last** branch is
`resolve_response()`, and anything that reaches it is dropped with a warning. So a
message type the chain does not name does not fail — it disappears, and the symptom is
"the message vanished and nothing reported an error" (ADR 0029 D2).

That is not hypothetical. On 2026-08-11, the first time the stack was started for real,
`runner.register` was serialising `runtimes` as `null` instead of `[]`; the frame failed
schema validation, `decode_control` raised, the loop's `except` swallowed it, and the
result was a daemon that logged "registered with central", a `nodes.agent_runner` of
`true`, and **no runner row anywhere** — with no error on either side. This gate is the
one that was missing when that happened, so it now checks both halves:

1. every node→central `run.*` / `runner.*` type in the contract has a branch;
2. every payload the daemon can build for those types **validates against the
   contract**, which is the half that would have caught the real bug.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.protocol import ProtocolError, decode_control

ROOT = Path(__file__).resolve().parents[2]
NODES_WS = ROOT / "backend/app/api/ws/nodes.py"
ENVELOPE = ROOT / "contracts/v1/schemas/control-envelope.schema.json"

# Types Central *sends*; they need no inbound branch. Everything else in the `run.*` /
# `runner.*` family arrives from a node and must be handled.
CENTRAL_TO_NODE = {"runner.registered", "run.offer", "run.cancel"}


def _contract_types() -> set[str]:
    document = json.loads(ENVELOPE.read_text())
    return {
        value
        for value in document["properties"]["type"]["enum"]
        if value.startswith(("run.", "runner."))
    }


def _handled_types() -> set[str]:
    """Every string the control loop compares `message.type` against.

    Parsed rather than grepped: this file's own comments name several of these types
    while explaining the rule, and a guard that matches its own explanation is one
    somebody makes green by deleting the explanation.
    """
    tree = ast.parse(NODES_WS.read_text())
    handled: set[str] = set()

    def literals(node: ast.AST) -> set[str]:
        found: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                found.add(child.value)
        return found

    for node in ast.walk(tree):
        # `message.type == "x"` and `message.type in {...}` / `in _SET`
        if isinstance(node, ast.Compare):
            left = node.left
            if (
                isinstance(left, ast.Attribute)
                and left.attr == "type"
                and isinstance(left.value, ast.Name)
                and left.value.id == "message"
            ):
                for comparator in node.comparators:
                    handled |= literals(comparator)
                    if isinstance(comparator, ast.Name):
                        handled.add(f"<set:{comparator.id}>")
    # Resolve the module-level frozensets the chain compares against.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if f"<set:{name}>" in handled:
                handled.discard(f"<set:{name}>")
                handled |= literals(node.value)
    return handled


def test_every_inbound_run_message_has_a_branch() -> None:
    expected = _contract_types() - CENTRAL_TO_NODE
    missing = sorted(expected - _handled_types())
    assert missing == [], (
        f"these run messages reach the loop's final branch and are dropped with a "
        f"warning: {missing}. The symptom of that is 'the message vanished and nothing "
        f"reported an error', which is the hardest bug in this phase to find."
    )


def test_the_central_to_node_types_are_not_handled_inbound() -> None:
    """The other direction of the same claim.

    A branch for a type Central only ever *sends* would be dead code that looks like a
    handled case, which is worse than an absent one.
    """
    unexpected = sorted(CENTRAL_TO_NODE & _handled_types())
    assert unexpected == [], f"inbound branches for outbound-only types: {unexpected}"


# --- the half that would have caught the real bug -------------------------- #

_ENVELOPE_BASE = {
    "version": 1,
    "request_id": "01K0ABCDEFGHJKMNPQRSTVWX30",
    "node_id": "00000000-0000-4000-8000-0000000000aa",
    "timestamp": "2026-08-11T10:00:00Z",
}
RUN_ID = "00000000-0000-4000-8000-0000000000b1"

# Payloads the daemon really builds, including the shapes that are easy to get wrong.
# The first entry is the exact frame that was silently dropped in production.
DAEMON_PAYLOADS = [
    # A node whose CLIs are all too old. **This is the common case**, not an edge one:
    # an empty runtime set is how the design reports "installed but not usable", so
    # this frame is on the main path.
    (
        "runner.register",
        {
            "name": "dev-runner-01",
            "runtimes": [],
            "labels": [],
            "max_concurrent": 1,
            "max_waiting": 5,
            "dedicated": False,
        },
    ),
    (
        "runner.register",
        {
            "name": "dev-runner-01",
            "runtimes": ["claude"],
            "labels": ["gpu"],
            "max_concurrent": 2,
            "max_waiting": 5,
            "dedicated": True,
        },
    ),
    ("runner.poll", {"runner_id": RUN_ID, "capacity": 1}),
    ("run.accept", {"run_id": RUN_ID}),
    ("run.lease_renew", {"run_id": RUN_ID}),
    ("run.decline", {"run_id": RUN_ID, "reason": "at_capacity"}),
    ("run.progress", {"run_id": RUN_ID, "phase": "preparing"}),
    (
        "run.progress",
        {
            "run_id": RUN_ID,
            "phase": "checked_out",
            "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        },
    ),
    ("run.log_chunk", {"run_id": RUN_ID, "seq": 0, "data": "{}", "truncated": False}),
    # A completion with nothing to report: no remotes, nothing unpushed, and **no
    # summary at all**. This is the common path — a clean run has nothing awkward to
    # say — and it is the shape that caught the second bug: the daemon was sending
    # `"summary": ""` where the contract says `minLength: 1`, so every clean run's
    # completion frame was silently dropped and the lease expired instead.
    (
        "run.complete",
        {
            "run_id": RUN_ID,
            "result": "no_changes",
            "disk_bytes": 0,
            "git_remotes": [],
            "unpushed_commits": 0,
            "untracked_files": 0,
        },
    ),
    (
        "run.complete",
        {
            "run_id": RUN_ID,
            "result": "succeeded",
            "summary": "本卡宣告不交付，但工作目錄有變更；diff 已附為產物。",
            "disk_bytes": 18000000,
            "git_remotes": ["origin\thttps://example.invalid/a (fetch)"],
            "unpushed_commits": 2,
            "untracked_files": 1,
        },
    ),
    (
        "run.failed",
        {
            "run_id": RUN_ID,
            "error_code": "RUN_SOURCE_UNAVAILABLE",
            "message": "no usable credential on this node",
        },
    ),
]


@pytest.mark.parametrize(
    ("message_type", "payload"),
    DAEMON_PAYLOADS,
    ids=[f"{index}:{item[0]}" for index, item in enumerate(DAEMON_PAYLOADS)],
)
def test_a_payload_the_daemon_builds_survives_the_receiver(
    message_type: str, payload: dict
) -> None:
    """Validated by **the receiver itself**, not by a re-implementation of it.

    `decode_control` is the function that dropped the real frame, so calling anything
    else here would be testing a second opinion. The bug it exists for was invisible to
    every other check: the Go side compiled, the daemon logged success, and the type
    had a branch — what was wrong was the JSON, where a nil slice became `null` and the
    contract says `array`.
    """
    frame = json.dumps({**_ENVELOPE_BASE, "type": message_type, "payload": payload}).encode()
    try:
        message = decode_control(frame)
    except ProtocolError as error:  # pragma: no cover - the assertion is the report
        pytest.fail(
            f"{message_type} would be rejected and **silently dropped** by the node "
            f"gateway: {error.code}. Nothing on either side reports this."
        )
    assert message.type == message_type
