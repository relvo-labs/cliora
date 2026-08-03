"""Authorization rules and matrix consistency, without a database (P4-03, ADR 0016).

Two things live here:

* the **resource-scope predicates** (`app/services/authz.py`) exercised over every
  role x ownership position — these are pure functions of a User and a
  TerminalSession, so they need no database and belong in the hermetic run;
* the **consistency checks** that keep the declared matrix from becoming fiction:
  the frontend's action constants, the "is every action actually enforced" scan,
  and full route coverage.

The database-backed half (seeded-role parity plus the real HTTP role x route
matrix) is in `tests/db/test_permission_matrix.py`.
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pytest

from app.db.models import Role, TerminalSession, User
from app.main import app
from app.services import authz, rbac

ROOT = Path(__file__).parents[2]


def _user(role_name: str, actions: set[str] | frozenset[str] | None = None) -> User:
    """A detached User with a role, built in memory: the predicates only read
    `user.role.permissions` and `user.id`, so nothing needs persisting."""
    granted = rbac.ROLE_ACTIONS[role_name] if actions is None else actions
    user = User(
        id=uuid.uuid4(),
        username=role_name.lower(),
        password_hash="x",
        display_name=role_name,
        role_id=uuid.uuid4(),
        is_active=True,
    )
    user.role = Role(id=user.role_id, name=role_name, permissions={"actions": sorted(granted)})
    return user


def _session(owner: User) -> TerminalSession:
    return TerminalSession(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        user_id=owner.id,
        name="s",
        runtime="claude",
        workspace="/home/neil/projects/app",
        status="running",
    )


# --------------------------------------------------------------------------- #
# Resource-scope predicates: role x ownership, exhaustively
# --------------------------------------------------------------------------- #

# (role, is_owner) -> (view, write, takeover, terminate, browse_files)
EXPECTED: dict[tuple[str, bool], tuple[bool, bool, bool, bool, bool]] = {
    ("Admin", True): (True, True, True, True, True),
    # An Admin holds node.manage, so ownership is not required to terminate.
    ("Admin", False): (True, True, True, True, True),
    ("Developer", True): (True, True, True, True, True),
    # A non-owner Developer holds terminal.takeover, so they may hold the writer
    # role — but they may NOT end a colleague's session. This asymmetry is the
    # whole point of the resource layer.
    ("Developer", False): (True, True, True, False, True),
    ("Viewer", True): (True, False, False, False, True),
    ("Viewer", False): (True, False, False, False, True),
}


@pytest.mark.parametrize(("role", "is_owner"), sorted(EXPECTED), ids=lambda v: str(v))
def test_predicates_over_role_and_ownership(role: str, is_owner: bool) -> None:
    view, write, takeover, terminate, browse = EXPECTED[(role, is_owner)]
    actor = _user(role)
    owner = actor if is_owner else _user("Developer")
    session = _session(owner)

    assert authz.is_owner(actor, session) is is_owner
    assert authz.may_view_session(actor, session) is view
    assert authz.may_write_session(actor, session) is write
    assert authz.may_takeover_session(actor, session) is takeover
    assert authz.may_terminate_session(actor, session) is terminate
    assert authz.may_browse_files(actor, session) is browse


@pytest.mark.parametrize(("role", "is_owner"), sorted(EXPECTED), ids=lambda v: str(v))
def test_capability_projection_matches_the_predicates(role: str, is_owner: bool) -> None:
    """The flags handed to the browser are the same decision the server enforces,
    not a parallel implementation."""
    actor = _user(role)
    owner = actor if is_owner else _user("Developer")
    session = _session(owner)
    caps = authz.session_capabilities(actor, session)
    assert caps == {
        "can_view": authz.may_view_session(actor, session),
        "can_write": authz.may_write_session(actor, session),
        "can_takeover": authz.may_takeover_session(actor, session),
        "can_terminate": authz.may_terminate_session(actor, session),
        "can_browse_files": authz.may_browse_files(actor, session),
        "can_upload_files": authz.may_upload_files(actor, session),
        "can_open_shell": authz.may_open_shell(actor, session),
    }


def test_owner_without_operate_cannot_write() -> None:
    """Permission contraction must contract. A user demoted to Viewer still owns
    the sessions they created, so an ownership-only rule would keep letting them
    type into a live CLI."""
    owner = _user("Viewer")
    session = _session(owner)
    assert authz.is_owner(owner, session) is True
    assert authz.may_view_session(owner, session) is True
    assert authz.may_write_session(owner, session) is False
    assert authz.may_takeover_session(owner, session) is False
    assert authz.may_terminate_session(owner, session) is False


def test_role_with_no_actions_is_refused_everything() -> None:
    stripped = _user("Stripped", actions=set())
    session = _session(stripped)
    assert authz.may_view_session(stripped, session) is False
    assert authz.may_write_session(stripped, session) is False
    assert authz.may_terminate_session(stripped, session) is False
    assert authz.may_browse_files(stripped, session) is False


@pytest.mark.parametrize(
    "authorize",
    [
        authz.authorize_session_view,
        authz.authorize_session_terminate,
        authz.authorize_file_browse,
    ],
    ids=["view", "terminate", "file_browse"],
)
def test_refusals_are_uniform_and_reveal_nothing(authorize) -> None:
    """Every refusal is the same 403 with the same message, so a caller cannot use
    the response to learn whether a resource exists or who owns it."""
    stripped = _user("Stripped", actions=set())
    session = _session(_user("Developer"))
    with pytest.raises(Exception) as raised:  # ApiError
        authorize(stripped, session)
    error = raised.value
    assert getattr(error, "code", None) == "FORBIDDEN"
    assert getattr(error, "status_code", None) == 403
    assert error.message == "You do not have permission for this action"
    # Nothing identifying may appear in the outward message.
    for leak in (str(session.id), str(session.user_id), session.workspace, "Stripped"):
        assert leak not in error.message


# --------------------------------------------------------------------------- #
# Consistency: one source of truth, and copies that must agree
# --------------------------------------------------------------------------- #


def test_all_actions_match_the_frontend_constants() -> None:
    """The browser hides controls by action key. A key on only one side is either
    a dead UI branch or a control shown without a permission behind it."""
    dto = (ROOT / "frontend/src/api/dto.ts").read_text(encoding="utf-8")
    exported = set(re.findall(r'export const ACTION_[A-Z_]+ = "([^"]+)";', dto))
    assert exported == set(rbac.ALL_ACTIONS)


def test_every_action_is_enforced_somewhere() -> None:
    """An action that nothing checks is a permission that does not exist.

    The scan deliberately excludes the seed migrations: their job is to *declare*
    the vocabulary, so counting them as enforcement makes this check vacuous —
    which is precisely how `audit.view` stayed dead from P1 through P3 while
    appearing to be present.
    """
    sources = [
        path.read_text(encoding="utf-8")
        for path in (ROOT / "backend/app").rglob("*.py")
        if path.name != "rbac.py" and "migrations" not in path.parts
    ]
    blob = "\n".join(sources)
    unenforced = {
        action
        for action in rbac.ALL_ACTIONS
        if f'"{action}"' not in blob and action.replace(".", "_").upper() not in blob
    }
    assert unenforced == set(rbac.UNENFORCED_ACTIONS), (
        "actions defined but enforced nowhere: "
        f"{sorted(unenforced - rbac.UNENFORCED_ACTIONS)}; "
        "listed as unenforced but now used (remove them from UNENFORCED_ACTIONS): "
        f"{sorted(rbac.UNENFORCED_ACTIONS - unenforced)}"
    )


# (method, path template) -> required action, or None for public /
# authentication-only routes. Owner rules are asserted by the predicates above
# and by the HTTP matrix in tests/db/test_permission_matrix.py.
ROUTE_ACTIONS: dict[tuple[str, str], str | None] = {
    ("POST", "/api/auth/login"): None,
    ("POST", "/api/auth/refresh"): None,
    ("POST", "/api/auth/logout"): None,
    ("GET", "/api/auth/me"): None,
    ("POST", "/api/ws-ticket"): None,
    ("GET", "/api/downloads/{filename}"): None,
    ("GET", "/api/install-script"): None,
    # Public for the same reason as the downloads it describes: a daemon needs to
    # know which releases exist before it holds any credential, and the content is
    # already public through /api/downloads (ADR 0017).
    ("GET", "/api/releases/manifest"): None,
    # Not a user action at all: guarded by a dedicated `metrics_scrape_token`, and off
    # entirely unless `metrics_enabled` (ADR 0018). Reusing `audit.view` would mean a
    # scrape account able to read the audit trail, and Prometheus holds no session.
    ("GET", "/api/metrics"): None,
    # Authorized by a single-use enrollment token, not by a user action.
    ("POST", "/api/nodes/register"): None,
    ("GET", "/api/nodes"): rbac.NODE_VIEW,
    ("GET", "/api/nodes/{node_id}"): rbac.NODE_VIEW,
    ("POST", "/api/nodes/{node_id}/enabled"): rbac.NODE_MANAGE,
    ("POST", "/api/nodes/{node_id}/credential/revoke"): rbac.NODE_MANAGE,
    ("POST", "/api/nodes/{node_id}/credential/rotate"): rbac.NODE_MANAGE,
    ("POST", "/api/nodes/{node_id}/update"): rbac.NODE_MANAGE,
    ("DELETE", "/api/nodes/{node_id}"): rbac.NODE_MANAGE,
    ("POST", "/api/enrollment-tokens"): rbac.ENROLLMENT_MANAGE,
    ("GET", "/api/enrollment-tokens"): rbac.ENROLLMENT_MANAGE,
    ("DELETE", "/api/enrollment-tokens/{token_id}"): rbac.ENROLLMENT_MANAGE,
    ("POST", "/api/sessions"): rbac.SESSION_CREATE,
    ("GET", "/api/sessions"): rbac.SESSION_VIEW,
    ("GET", "/api/sessions/{session_id}"): rbac.SESSION_VIEW,
    ("POST", "/api/sessions/{session_id}/attach"): rbac.SESSION_VIEW,
    ("POST", "/api/sessions/{session_id}/terminate"): rbac.SESSION_TERMINATE,
    ("POST", "/api/sessions/{session_id}/shell"): rbac.TERMINAL_SHELL,
    ("DELETE", "/api/sessions/{session_id}"): rbac.SESSION_TERMINATE,
    ("GET", "/api/sessions/{session_id}/files/tree"): rbac.FILE_BROWSE,
    ("GET", "/api/sessions/{session_id}/files/search"): rbac.FILE_BROWSE,
    ("GET", "/api/sessions/{session_id}/files/content"): rbac.FILE_BROWSE,
    # The one write route (ADR 0024). A separate action from file.browse on
    # purpose: all three roles browse, only two may write.
    ("POST", "/api/sessions/{session_id}/files/images"): rbac.FILE_UPLOAD,
    # General file upload reuses file.upload rather than adding an action
    # (ADR 0026 sec 6): the verb is the same, and with three fixed roles nobody can
    # express "may upload images but not files". The cost is that the action's
    # meaning widens, which is a release-note obligation rather than a matrix one.
    ("POST", "/api/sessions/{session_id}/files/upload"): rbac.FILE_UPLOAD,
    # Favourites/recents exist to make creating a session faster, so they are gated on
    # `session.create`: a Viewer cannot create one and has nothing to shortcut (ADR 0016).
    ("GET", "/api/workspaces/favorites"): rbac.SESSION_CREATE,
    ("POST", "/api/workspaces/favorites"): rbac.SESSION_CREATE,
    ("DELETE", "/api/workspaces/favorites/{favorite_id}"): rbac.SESSION_CREATE,
    ("GET", "/api/workspaces/recent"): rbac.SESSION_CREATE,
    ("GET", "/api/audit"): rbac.AUDIT_VIEW,
    # Port forwarding (ADR 0022). Viewer holds neither tunnel action: reading a URL is
    # reaching the application behind it, and "read-only platform role" does not compose with
    # "may open the preview".
    ("GET", "/api/tunnels"): rbac.TUNNEL_VIEW,
    ("POST", "/api/tunnels"): rbac.TUNNEL_MANAGE,
    ("DELETE", "/api/tunnels/{tunnel_id}"): rbac.TUNNEL_MANAGE,
    ("POST", "/api/tunnels/{tunnel_id}/extend"): rbac.TUNNEL_MANAGE,
    ("POST", "/api/tunnels/{tunnel_id}/rotate-password"): rbac.TUNNEL_MANAGE,
    ("GET", "/api/nodes/{node_id}/tunnel-policy"): rbac.TUNNEL_VIEW,
    # `tunnel.manage`, not `integration.manage`: which ports one machine may forward is
    # day-to-day work, while whose provider account the organisation uses is not.
    ("PUT", "/api/nodes/{node_id}/tunnel-settings"): rbac.TUNNEL_MANAGE,
    # Admin-only: supplying the organisation's third-party credential and deciding that
    # traffic may leave for a third party at all.
    ("GET", "/api/integrations/tunnel"): rbac.INTEGRATION_MANAGE,
    ("PUT", "/api/integrations/tunnel"): rbac.INTEGRATION_MANAGE,
    ("PUT", "/api/integrations/tunnel/credential"): rbac.INTEGRATION_MANAGE,
    ("DELETE", "/api/integrations/tunnel/credential"): rbac.INTEGRATION_MANAGE,
    # All three roles hold node.view: the Dashboard is the landing page and every
    # role has a legitimate view of fleet health. Actor identity inside recent
    # activity is what `audit.view` gates (services/dashboard.project_for).
    ("GET", "/api/dashboard/summary"): rbac.NODE_VIEW,
}

# Health, docs and WebSocket upgrades are outside the HTTP action surface. The WS
# endpoints authorize via ws-ticket plus the same predicates (see ADR 0016).
_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/ws/", "/openapi", "/docs", "/redoc")


def mounted_routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not methods or path.startswith(_EXEMPT_PREFIXES):
            continue
        found.update((method, path) for method in methods if method not in {"HEAD", "OPTIONS"})
    return found


def test_every_mounted_route_is_in_the_matrix() -> None:
    """Adding an endpoint without deciding its authorization fails here. This is
    the mechanism that keeps the matrix honest as the surface grows."""
    mounted = mounted_routes()
    declared = set(ROUTE_ACTIONS)
    assert mounted - declared == set(), (
        f"routes missing from the matrix: {sorted(mounted - declared)}"
    )
    assert declared - mounted == set(), (
        f"matrix lists routes that do not exist: {sorted(declared - mounted)}"
    )


@pytest.mark.parametrize(
    ("method", "path"),
    sorted(key for key, action in ROUTE_ACTIONS.items() if action is not None),
    ids=lambda value: str(value),
)
def test_guarded_action_is_held_by_some_role(method: str, path: str) -> None:
    """A guard nobody passes is a dead route. (Read actions such as `node.view` are
    legitimately held by all three roles, so breadth is not itself a defect —
    `test_viewer_holds_no_mutation_action` covers that side.)"""
    action = ROUTE_ACTIONS[(method, path)]
    assert action is not None
    holders = {role for role, actions in rbac.ROLE_ACTIONS.items() if action in actions}
    assert holders, f"{method} {path} requires {action}, which no role holds"


def test_authorization_logic_is_confined_to_two_modules() -> None:
    """`has_action` may only be called from the action guard and the resource layer.

    A check written inline in a route or a WebSocket handler is how the two layers
    drift apart: it will be correct the day it is written and forgotten the day the
    rule changes. Both surfaces already had one (`api/ws/terminal.py` decided writer
    and takeover locally through P2/P3), which is why this is a test and not a
    convention.
    """
    allowed = {"deps.py", "authz.py", "rbac.py"}
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "backend/app").rglob("*.py")
        if path.name not in allowed and "has_action(" in path.read_text(encoding="utf-8")
    )
    assert offenders == [], (
        f"authorization decided outside app/api/http/deps.py and app/services/authz.py: {offenders}"
    )


def test_permission_matrix_doc_is_current() -> None:
    """`docs/permission-matrix.md` is generated from `ROLE_ACTIONS`. Asserting it
    here is what stops the published matrix from being true when written and
    quietly false a phase later."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/p4/render_permission_matrix.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_viewer_holds_no_mutation_action() -> None:
    """Viewer is read-only by construction, so a forged mutation fails at the
    action layer before any resource is even loaded (PRD §8.1)."""
    mutations = {
        rbac.SESSION_CREATE,
        rbac.SESSION_TERMINATE,
        rbac.TERMINAL_OPERATE,
        rbac.TERMINAL_TAKEOVER,
        rbac.ENROLLMENT_MANAGE,
        rbac.NODE_MANAGE,
    }
    assert rbac.ROLE_ACTIONS[rbac.VIEWER] & mutations == set()


def test_admin_is_a_superset_of_developer_which_is_a_superset_of_viewer() -> None:
    assert rbac.ROLE_ACTIONS[rbac.VIEWER] < rbac.ROLE_ACTIONS[rbac.DEVELOPER]
    assert rbac.ROLE_ACTIONS[rbac.DEVELOPER] < rbac.ROLE_ACTIONS[rbac.ADMIN]


# --------------------------------------------------------------------------- #
# System terminal (ADR 0021). Every rule here is *narrower* than the CLI rule it
# shadows, so each one is asserted against the role that would otherwise pass.
# --------------------------------------------------------------------------- #


def _shell(owner: User, parent_status: str = "running") -> TerminalSession:
    session = _session(owner)
    session.runtime = "shell"
    session.status = parent_status
    return session


def test_nobody_but_the_owner_can_watch_a_shell() -> None:
    owner = _user("Developer")
    shell = _shell(owner)
    for role in ("Admin", "Developer", "Viewer"):
        stranger = _user(role)
        assert not authz.may_view_session(stranger, shell), (
            f"{role} must not attach to another user's system terminal"
        )
    assert authz.may_view_session(owner, shell)


def test_a_shell_cannot_be_taken_over() -> None:
    """`terminal.takeover` reaches every CLI session its holder may write. It must
    reach no shell at all — there is no second party to hand one to."""
    owner = _user("Developer")
    shell = _shell(owner)
    assert not authz.may_takeover_session(owner, shell)
    assert not authz.may_takeover_session(_user("Admin"), shell)


def test_a_shell_session_id_is_not_a_route_to_the_filesystem_relay() -> None:
    """The tree is bound to the CLI session that owns the workspace. Allowing the
    relay through a shell id would add a second path to the same data with a
    different owner check."""
    owner = _user("Developer")
    assert not authz.may_browse_files(owner, _shell(owner))
    assert authz.may_browse_files(owner, _session(owner))


def test_opening_a_shell_needs_the_action_and_ownership() -> None:
    owner = _user("Developer")
    cli = _session(owner)
    assert authz.may_open_shell(owner, cli)
    # Holds the action, does not own the session.
    assert not authz.may_open_shell(_user("Admin"), cli)
    # Owns nothing, holds nothing.
    assert not authz.may_open_shell(_user("Viewer"), _session(_user("Viewer")))


def test_a_shell_cannot_host_a_shell_and_a_dead_session_cannot_open_one() -> None:
    owner = _user("Developer")
    assert not authz.may_open_shell(owner, _shell(owner))
    ended = _session(owner)
    ended.status = "terminated"
    assert not authz.may_open_shell(owner, ended)


def test_an_admin_may_terminate_a_shell_they_may_not_watch() -> None:
    """The one asymmetry, and it is deliberate: cleaning up an orphan is not the
    same as looking inside it."""
    owner = _user("Developer")
    shell = _shell(owner)
    admin = _user("Admin")
    assert authz.may_terminate_session(admin, shell)
    assert not authz.may_view_session(admin, shell)
