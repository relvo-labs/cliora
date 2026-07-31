"""Role-based authorization over stable action keys (PRD §8.1, ADR 0007/0016).

This module owns the **action layer** only: the vocabulary of action keys and
which role holds which. Resource-scope questions ("may this user terminate *this*
session?") live in `app/services/authz.py` — see ADR 0016. Keeping them apart is
what stops a role check from being mistaken for an ownership check.

A user has one role; the role's `permissions.actions` list is the seeded
authorization vocabulary. Checks operate on the loaded User so a disabled
account or a role change takes effect on the next request.

`ROLE_ACTIONS` is the single source of truth (ADR 0016). Three automated
assertions keep the copies from drifting — see
`backend/tests/db/test_permission_matrix.py`:

1. it matches what the seed migrations actually produce in PostgreSQL,
2. it matches the `ACTION_*` constants exported by `frontend/src/api/dto.ts`,
3. every action is enforced somewhere (or is listed in `UNENFORCED_ACTIONS`).
"""

from __future__ import annotations

from app.db.models import User

# Stable action keys (must match the role seed migrations 0002 + 0006 + 0007 + 0008 + 0012).
NODE_VIEW = "node.view"
SESSION_CREATE = "session.create"
SESSION_VIEW = "session.view"
TERMINAL_OPERATE = "terminal.operate"
TERMINAL_TAKEOVER = "terminal.takeover"
TERMINAL_SHELL = "terminal.shell"
SESSION_TERMINATE = "session.terminate"
FILE_BROWSE = "file.browse"
ENROLLMENT_MANAGE = "enrollment.manage"
NODE_MANAGE = "node.manage"
AUDIT_VIEW = "audit.view"

ADMIN = "Admin"
DEVELOPER = "Developer"
VIEWER = "Viewer"

# --- The permission matrix (PRD §8.1). Single source of truth, ADR 0016. ---
#
# Viewer holds the read-only actions: node.view, session.view (read-only attach,
# P2/ADR 0013) and file.browse (read-only browse + preview, ADR 0015). It holds
# no mutation action, so a Viewer's forged create/terminate/takeover/enrollment
# request fails at the action layer before any resource is loaded.
_VIEWER_ACTIONS = frozenset({NODE_VIEW, SESSION_VIEW, FILE_BROWSE})
# `terminal.shell` sits with the other session-mutation actions rather than in the
# Admin set (ADR 0021): a Developer already drives a CLI in their own session. The
# boundary is ownership, not role — `authz.may_open_shell` requires the caller to own
# the session, and nobody may attach to a shell they did not open.
_DEVELOPER_ACTIONS = _VIEWER_ACTIONS | {
    SESSION_CREATE,
    SESSION_TERMINATE,
    TERMINAL_OPERATE,
    TERMINAL_TAKEOVER,
    TERMINAL_SHELL,
}
_ADMIN_ACTIONS = _DEVELOPER_ACTIONS | {ENROLLMENT_MANAGE, NODE_MANAGE, AUDIT_VIEW}

ROLE_ACTIONS: dict[str, frozenset[str]] = {
    ADMIN: _ADMIN_ACTIONS,
    DEVELOPER: _DEVELOPER_ACTIONS,
    VIEWER: _VIEWER_ACTIONS,
}

ALL_ACTIONS: frozenset[str] = frozenset().union(*ROLE_ACTIONS.values())

# Actions that exist in the vocabulary but are not yet enforced by any endpoint
# or WebSocket handler. Every entry is a permission that does not really exist
# yet, so the list must be emptied by the ticket that wires the action up —
# `test_every_action_is_enforced_somewhere` fails in *both* directions, so a
# stale entry is as loud as a missing one.
#
# Now empty. `audit.view` was seeded to Admin in migration 0002 (P1) and checked
# by nothing until P4-05 landed `GET /api/audit`; P4-03 is what made that
# visible. Every action in the vocabulary is now enforced somewhere.
UNENFORCED_ACTIONS: frozenset[str] = frozenset()


def role_actions(user: User) -> set[str]:
    permissions = user.role.permissions or {}
    actions = permissions.get("actions", [])
    return set(actions) if isinstance(actions, list) else set()


def has_action(user: User, action: str) -> bool:
    return action in role_actions(user)
