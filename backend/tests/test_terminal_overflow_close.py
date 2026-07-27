"""The overflow path closes the connection, it does not just stop (P4-11 finding).

`pump()` used to send `terminal.gap` and `return`, leaving the socket open with a dead
pump. The browser had its gap notice and would never receive another byte, while staying
counted in `active_terminal_connections`, staying subscribed in the relay, and — if it
was the writer — holding the writer marker it could no longer use.

Every existing test asserted the gap was *sent*. None asserted what happened next, which
is why the defect survived to P4 and was found by the P4-11 slow-client harness against a
live Central instead.

These are structural assertions, deliberately labelled as such. The behavioural coverage
is `slow_client_is_disconnected` in `scripts/p4/load/terminal_clients.py`, which drives a
real non-reading socket through a real Central; it runs in the `capacity` CI job. A
structural check is a poor substitute for it, but it is cheap, it pins the intent next to
the code, and it fails if someone deletes the close while refactoring — which is the
regression that actually happened.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.api.ws.terminal import OVERFLOW_CLOSE_CODE

SOURCE = Path(__file__).parents[1] / "app/api/ws/terminal.py"


def test_the_close_code_is_1013_try_again_later() -> None:
    """1013 rather than 1011 or 1000: the browser should reconnect, and the session it
    was watching is untouched. A 1000 would read as an orderly, intended end."""
    assert OVERFLOW_CLOSE_CODE == 1013


def _overflow_branch() -> ast.If:
    """The `elif kind == "overflow"` branch of `pump`, located in the AST rather than by
    string matching so a reformat cannot make this test silently vacuous."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "kind"
            and any(isinstance(c, ast.Constant) and c.value == "overflow" for c in test.comparators)
        ):
            return node
    pytest.fail("the overflow branch of pump() was not found; this test needs updating")


def test_the_overflow_branch_closes_the_socket() -> None:
    branch = _overflow_branch()
    calls = [
        node
        for node in ast.walk(branch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close"
    ]
    assert calls, (
        "the overflow branch sends the gap but never closes: the browser is left "
        "subscribed with a dead pump, holding the writer marker if it had it"
    )


def test_the_gap_is_sent_before_the_close() -> None:
    """Order matters. Closing first would drop the frame that explains why, turning a
    handled overflow back into an unexplained disconnect."""
    branch = _overflow_branch()
    order: list[str] = []
    for node in ast.walk(branch):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("send_text", "close"):
                order.append(node.func.attr)
    assert order.index("send_text") < order.index("close")
