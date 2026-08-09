"""Resource-scope authorization: may this user act on *this* resource (ADR 0016).

`app/services/rbac.py` answers the action question ("may this role ever do this
kind of thing?"). This module answers the resource question ("may this user do it
to this session?"), and it is the **only** place that logic may live. Both layers
are mandatory for every session-scoped mutation; either one alone is a hole.

Why it exists: through P1-P3 authorization checked the role only, while
`TerminalSession.user_id` was recorded but never consulted. Any Developer could
therefore terminate — or seize the writer role of — any other user's session.
That is what this module closes.

Two shapes are provided deliberately:

* `may_*` predicates for the terminal WebSocket, which cannot raise an HTTP error
  mid-stream and instead drops the message;
* `authorize_*` raisers for the HTTP boundary.

Every refusal raises the **same** `FORBIDDEN` with the same message, so a caller
cannot use the response to learn whether a resource exists or who owns it. Where
absence is legitimate, check `session.view` first and only then answer 404.
"""

from __future__ import annotations

from fastapi import status

from app import metrics
from app.api.errors import ApiError
from app.api.middleware import denial_var
from app.db.models import NodeTunnel, TerminalSession, User
from app.services.rbac import (
    AUDIT_VIEW,
    FILE_BROWSE,
    FILE_UPLOAD,
    INTEGRATION_MANAGE,
    NODE_MANAGE,
    SESSION_CREATE,
    SESSION_TERMINATE,
    SESSION_VIEW,
    TERMINAL_OPERATE,
    TERMINAL_SHELL,
    TERMINAL_TAKEOVER,
    TUNNEL_MANAGE,
    TUNNEL_VIEW,
    has_action,
)
from app.services.sessions import SHELL_RUNTIME, TERMINAL_STATES

# Reasons are coarse and low-cardinality so they are safe as a metric label
# (ADR 0018): "action" = the role never holds it, "scope" = the role holds it but
# not for this resource.
REASON_ACTION = "action"
REASON_SCOPE = "scope"


def _forbidden(action: str, user: User, reason: str) -> ApiError:
    """Build the single, uniform refusal and count it.

    The counter is what makes a misconfigured role or a probing client visible
    (`authz_denied_total`, alerted per ADR 0018). Only the coarse action name,
    role name and reason are recorded — never a user id, session id or resource
    path, which would make the series high-cardinality and leak identifiers into
    the one sink that has no redaction (ADR 0018).

    The refusal is also published on a contextvar so `AuthzDenialAuditMiddleware`
    can write the `authz.denied` audit row after the response. This layer
    deliberately holds no database session: the decision must not depend on a
    write succeeding, and the audit row must land even if the request's own
    transaction rolled back.
    """
    denial_var.set((action, reason))
    metrics.increment(
        metrics.AUTHZ_DENIED_TOTAL,
        action=action,
        role=user.role.name,
        reason=reason,
    )
    return ApiError(
        "FORBIDDEN",
        "You do not have permission for this action",
        status.HTTP_403_FORBIDDEN,
    )


def is_owner(user: User, session: TerminalSession) -> bool:
    return session.user_id == user.id


# A system-terminal session (ADR 0021). Its authorization is *narrower* than a CLI
# session's at every point, so the predicates below branch on it first rather than
# inheriting the CLI rules and trying to subtract from them.
def is_shell(session: TerminalSession) -> bool:
    return session.runtime == SHELL_RUNTIME


# --- Predicates (terminal WebSocket) ---


def may_view_session(user: User, session: TerminalSession) -> bool:
    """Read-only attach. Any holder of `session.view`, including Viewer, matching
    P2's read-only viewer attach (ADR 0013).

    A shell session is the exception: **owner only**. Read-only attach exists so a
    colleague can watch a CLI do its work; nobody has that reason to watch another
    person's shell, and the contents are unbounded by the workspace (ADR 0021).
    """
    if is_shell(session):
        return is_owner(user, session) and has_action(user, TERMINAL_SHELL)
    return has_action(user, SESSION_VIEW)


def may_write_session(user: User, session: TerminalSession) -> bool:
    """Eligibility to hold the terminal writer role.

    Requires `terminal.operate` **and** either ownership or the explicit
    `terminal.takeover` action. `terminal.operate` is required even for the owner:
    a user demoted to Viewer still owns the sessions they created earlier, and
    permission contraction must actually contract.

    A shell session is owner-only and cannot be reached through
    `terminal.takeover`: the writer of a shell is the person who opened it, full
    stop.
    """
    if is_shell(session):
        return may_view_session(user, session)
    if not has_action(user, TERMINAL_OPERATE):
        return False
    return is_owner(user, session) or has_action(user, TERMINAL_TAKEOVER)


def may_takeover_session(user: User, session: TerminalSession) -> bool:
    """Eligibility to seize the writer role from the current writer.

    Identical to write eligibility by construction: whoever may hold the role may
    reclaim it. The difference is not in the permission but in the effect — a
    takeover displaces someone, so it is announced to every subscriber and
    audited (`session.takeover`).

    Never allowed for a shell session: there is no second party to hand it to.
    """
    if is_shell(session):
        return False
    return may_write_session(user, session)


def may_terminate_session(user: User, session: TerminalSession) -> bool:
    """Requires `session.terminate` and either ownership or Admin (`node.manage`).
    A Developer cannot end a colleague's session."""
    if not has_action(user, SESSION_TERMINATE):
        return False
    return is_owner(user, session) or has_action(user, NODE_MANAGE)


def may_browse_files(user: User, session: TerminalSession) -> bool:
    """File access is scoped by the session that owns the workspace, so it needs
    both `file.browse` and view access to that session (P3 semantics).

    Never through a shell session's id. The file tree is bound to the CLI session
    that owns the workspace, so routing the filesystem relay through a shell
    session would add a second path to the same data with a different owner check
    — a lateral route, not a feature.
    """
    if is_shell(session):
        return False
    return has_action(user, FILE_BROWSE) and may_view_session(user, session)


def may_open_shell(user: User, session: TerminalSession) -> bool:
    """Whether `user` may open a system terminal inside `session`.

    Requires `terminal.shell` and ownership of the *CLI* session. An Admin holds
    the action but not other people's sessions: they can terminate an orphan shell
    (`may_terminate_session`), which is cleaning up, but not open one inside a
    colleague's workspace, which is not.

    A shell cannot host a shell.
    """
    if is_shell(session) or session.status in TERMINAL_STATES:
        return False
    return has_action(user, TERMINAL_SHELL) and is_owner(user, session)


# --- Raisers (HTTP boundary) ---


def authorize_session_view(user: User, session: TerminalSession) -> None:
    if not may_view_session(user, session):
        raise _forbidden(SESSION_VIEW, user, REASON_ACTION)


def authorize_session_terminate(user: User, session: TerminalSession) -> None:
    if not has_action(user, SESSION_TERMINATE):
        raise _forbidden(SESSION_TERMINATE, user, REASON_ACTION)
    if not may_terminate_session(user, session):
        raise _forbidden(SESSION_TERMINATE, user, REASON_SCOPE)


def authorize_session_context_projection(user: User, session: TerminalSession) -> None:
    """A projection retry mints a fresh session credential: owner or Admin only."""
    if not has_action(user, SESSION_CREATE):
        raise _forbidden(SESSION_CREATE, user, REASON_ACTION)
    if not (is_owner(user, session) or has_action(user, NODE_MANAGE)):
        raise _forbidden(SESSION_CREATE, user, REASON_SCOPE)


def forbidden_shell(user: User, session: TerminalSession) -> ApiError:
    """The 403 for a refused system terminal, with the layer that refused it.

    Returned rather than raised so the route reads like the others. The reason
    label matters: `action` and `scope` are separate metric series, and with
    Developer holding `terminal.shell` (ADR 0021) the scope refusals — somebody
    reaching for a colleague's session — are the interesting signal.
    """
    if not has_action(user, TERMINAL_SHELL):
        return _forbidden(TERMINAL_SHELL, user, REASON_ACTION)
    return _forbidden(TERMINAL_SHELL, user, REASON_SCOPE)


def authorize_file_browse(user: User, session: TerminalSession) -> None:
    if not has_action(user, FILE_BROWSE):
        raise _forbidden(FILE_BROWSE, user, REASON_ACTION)
    if not may_browse_files(user, session):
        raise _forbidden(FILE_BROWSE, user, REASON_SCOPE)


def may_upload_files(user: User, session: TerminalSession) -> bool:
    """Whether this user may drop an image into the session's workspace.

    Scoped exactly like browsing — the workspace belongs to the CLI session, and
    a shell session is never a route to it — but gated on `file.upload`, which
    Viewer does not hold (ADR 0024 sec 6).
    """
    if is_shell(session):
        return False
    return has_action(user, FILE_UPLOAD) and may_view_session(user, session)


def authorize_file_upload(user: User, session: TerminalSession) -> None:
    if not has_action(user, FILE_UPLOAD):
        raise _forbidden(FILE_UPLOAD, user, REASON_ACTION)
    if not may_upload_files(user, session):
        raise _forbidden(FILE_UPLOAD, user, REASON_SCOPE)


def may_view_audit(user: User) -> bool:
    """Whether this user may see audit detail (actor identity, the trail itself).

    A predicate rather than a raiser because the Dashboard *degrades* on it instead
    of refusing: every role sees recent activity, only `audit.view` holders see who
    performed each action (FR-AUTH-002). It lives here so no route re-derives it —
    `test_authorization_logic_is_confined_to_two_modules` enforces that.
    """
    return has_action(user, AUDIT_VIEW)


# --- Port forwarding (P11, ADR 0022) ---
#
# The three-layer configuration policy (integration / per-node / the node's own veto) is
# *not* authorization and deliberately does not live here: it answers "may this port be
# forwarded from this machine at all", which is the same answer for every user. It belongs to
# `services/tunnels.effective_policy`, where it can be unit-tested against its four inputs.
# What is here is the part that depends on who is asking.


def may_view_tunnel(user: User) -> bool:
    """Seeing a tunnel's URL is being able to reach the preview behind it, so this is
    `tunnel.view` and Viewer does not hold it: a read-only platform role says nothing about
    what the forwarded application does with a request (ADR 0022)."""
    return has_action(user, TUNNEL_VIEW)


def may_close_tunnel(user: User, tunnel: NodeTunnel) -> bool:
    """Requires `tunnel.manage` and either ownership or Admin (`node.manage`).

    Same shape as terminating a session: a Developer may end what they exposed, and an
    administrator may end anything, because an unwanted exposure is exactly the thing that
    must be closeable by someone other than whoever left for the day.
    """
    if not has_action(user, TUNNEL_MANAGE):
        return False
    return tunnel.created_by == user.id or has_action(user, NODE_MANAGE)


def authorize_tunnel_close(user: User, tunnel: NodeTunnel) -> None:
    if not has_action(user, TUNNEL_MANAGE):
        raise _forbidden(TUNNEL_MANAGE, user, REASON_ACTION)
    if not may_close_tunnel(user, tunnel):
        raise _forbidden(TUNNEL_MANAGE, user, REASON_SCOPE)


def authorize_integration_manage(user: User) -> None:
    """The integration settings are a single global object, so there is no resource scope.

    Admin-only (`integration.manage`): it covers supplying the organisation's third-party
    credential and deciding that traffic may leave for a third party at all. A Developer may
    open tunnels; they may not decide whose service and whose account.
    """
    if not has_action(user, INTEGRATION_MANAGE):
        raise _forbidden(INTEGRATION_MANAGE, user, REASON_ACTION)


def authorize_node_manage(user: User) -> None:
    """Nodes have no owner; kept here so every authorization call site reads the
    same way and none of them re-implements a check locally."""
    if not has_action(user, NODE_MANAGE):
        raise _forbidden(NODE_MANAGE, user, REASON_ACTION)


def may_view_activity_actors(user: User) -> bool:
    """Whether this caller may see *who* performed a project-timeline event.

    Not a guard — a projection. The timeline itself is readable with `project.view`,
    which all three roles hold; this decides only whether each row keeps its actor,
    and `services/activity.py::redact_actors` applies it.

    The rule is not new. `services/dashboard.py::project_for` already withholds actor
    identity from the dashboard's recent activity for anyone without `audit.view`,
    reasoning that knowing *that* a node was removed is operational context while
    knowing *who* removed it is the audit trail (FR-AUTH-002). The project timeline is
    the second surface with that shape, and it is the wider one — so without this it
    would hand every Viewer the actor feed P4 deliberately closed.

    Lives here rather than in the route because this is a question about a user's
    reach, and `test_authorization_logic_is_confined_to_two_modules` is what keeps
    that kind of question from spreading across route modules.
    """
    return has_action(user, AUDIT_VIEW)


# --- Capability projection for the UI (ADR 0016) ---
#
# The browser must never re-implement these rules; it renders what the server
# computed. `SessionDetail` carries these flags so a "Terminate" button is hidden
# for exactly the requests the server would refuse — and the refusal is still
# tested independently, because UI hiding is not authorization.


def session_capabilities(user: User, session: TerminalSession) -> dict[str, bool]:
    return {
        "can_view": may_view_session(user, session),
        "can_write": may_write_session(user, session),
        "can_takeover": may_takeover_session(user, session),
        "can_terminate": may_terminate_session(user, session),
        "can_browse_files": may_browse_files(user, session),
        "can_upload_files": may_upload_files(user, session),
        "can_open_shell": may_open_shell(user, session),
    }
