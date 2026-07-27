#!/usr/bin/env python
"""Render docs/permission-matrix.md from ROLE_ACTIONS (P4-03, ADR 0016).

The document is generated, never hand-edited. `test_permission_matrix_doc_is_current`
asserts the file on disk equals this output, so the published matrix cannot drift
from the code that enforces it — the failure mode this replaces is a table in a
doc that was true when written and quietly false a phase later.

    uv run --project backend python ../scripts/p4/render_permission_matrix.py --check
    uv run --project backend python ../scripts/p4/render_permission_matrix.py --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import rbac  # noqa: E402

DOC = ROOT / "docs/permission-matrix.md"

# PRD §8.1 names each capability in product terms; this maps those rows to the
# action keys that implement them, so the generated table can be read against the
# PRD without translation.
PRD_ROWS: list[tuple[str, str]] = [
    ("查看 Node / View nodes", rbac.NODE_VIEW),
    ("建立安裝 Token / Create enrollment token", rbac.ENROLLMENT_MANAGE),
    ("移除 Node / Manage & remove nodes", rbac.NODE_MANAGE),
    ("建立 Session / Create session", rbac.SESSION_CREATE),
    ("查看 Session / View session (read-only attach)", rbac.SESSION_VIEW),
    ("操作 Terminal / Operate terminal (writer)", rbac.TERMINAL_OPERATE),
    ("接管 Terminal / Take over the writer role", rbac.TERMINAL_TAKEOVER),
    ("終止 Session / Terminate session", rbac.SESSION_TERMINATE),
    ("瀏覽檔案 / Browse & preview files", rbac.FILE_BROWSE),
    ("查看 Audit Log / View audit log", rbac.AUDIT_VIEW),
]

ROLES = (rbac.ADMIN, rbac.DEVELOPER, rbac.VIEWER)

# Resource-scope rules from ADR 0016. Held here so the generated document states
# both layers: an action column alone would imply a Developer can terminate any
# session, which is exactly the misreading that produced the P4-03 defect.
SCOPE_RULES: list[tuple[str, str]] = [
    (
        "session.view / read-only attach",
        "any holder of `session.view` (Viewer included)",
    ),
    (
        "terminal writer (input, resize)",
        "`terminal.operate` **and** (owner **or** holder of `terminal.takeover`)",
    ),
    (
        "terminal takeover",
        "same as writer eligibility; displaces the current writer, so it is announced and audited",
    ),
    (
        "session.terminate / delete",
        "`session.terminate` **and** (owner **or** holder of `node.manage`, i.e. Admin)",
    ),
    (
        "session.create",
        "`user_id` is assigned by the server; never accepted from the client",
    ),
    (
        "file browse / search / preview",
        "`file.browse` **and** view access to the owning session",
    ),
    ("node management", "`node.manage`; nodes have no owner"),
]


def render() -> str:
    lines = [
        "<!-- GENERATED FILE — do not edit.",
        "     Source: app/services/rbac.py (ROLE_ACTIONS) + ADR 0016.",
        "     Regenerate: uv run --project backend python ../scripts/p4/render_permission_matrix.py --write",
        "-->",
        "",
        "# Permission matrix",
        "",
        "Two layers authorize every session-scoped mutation, and **both** are required",
        '(ADR 0016). The action layer below answers "may this role ever do this kind of',
        'thing?"; the resource-scope rules that follow answer "may this user do it to',
        '*this* resource?". A role check alone was the P1-P3 behaviour, and it let any',
        "Developer terminate any colleague's session.",
        "",
        "## Action layer (PRD §8.1)",
        "",
        "| 功能 / Capability | Action key | " + " | ".join(ROLES) + " |",
        "|---|---|" + "|".join([":--:"] * len(ROLES)) + "|",
    ]
    for label, action in PRD_ROWS:
        marks = ["✓" if action in rbac.ROLE_ACTIONS[role] else "—" for role in ROLES]
        lines.append(f"| {label} | `{action}` | " + " | ".join(marks) + " |")

    lines += [
        "",
        "Roles are strictly nested: Viewer ⊂ Developer ⊂ Admin. Viewer holds no mutation",
        "action, so a forged Viewer mutation fails before any resource is loaded.",
        "",
        "## Resource-scope layer (`app/services/authz.py`)",
        "",
        "| Operation | Rule |",
        "|---|---|",
    ]
    lines += [f"| {operation} | {rule} |" for operation, rule in SCOPE_RULES]

    lines += [
        "",
        "Every refusal from either layer raises the same `FORBIDDEN` / 403 with the same",
        "message, so a caller cannot use the response to learn whether a resource exists",
        "or who owns it. Where absence is legitimate, view access is settled first and",
        "only then may a 404 be returned.",
        "",
        "## Where these are enforced",
        "",
        "| Surface | Mechanism |",
        "|---|---|",
        "| HTTP | `require_action()` (action) then `app/services/authz.py` (resource) |",
        "| Browser terminal WebSocket | ws-ticket bound to (user, session), then the same "
        "predicates **on every inbound control message** — not once at attach |",
        "| Daemon WebSocket | Ed25519 node credential; a daemon cannot invoke a user action |",
        "| UI | capability flags computed by the server (`/api/auth/me`, "
        "`SessionSummary.capabilities`); hiding a control is never the authorization |",
        "",
        "Coverage is asserted by `backend/tests/test_authz.py` and",
        "`backend/tests/db/test_permission_matrix.py`: adding a route without deciding its",
        "authorization fails the route-coverage test.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write", action="store_true", help="write docs/permission-matrix.md"
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the file is stale"
    )
    args = parser.parse_args()
    expected = render()
    if args.write:
        DOC.write_text(expected, encoding="utf-8")
        print(f"wrote {DOC.relative_to(ROOT)}")
        return 0
    if args.check:
        actual = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if actual != expected:
            print(
                f"{DOC.relative_to(ROOT)} is stale; run with --write", file=sys.stderr
            )
            return 1
        print("permission matrix doc is current")
        return 0
    print(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
