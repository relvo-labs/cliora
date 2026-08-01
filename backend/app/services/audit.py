"""Audit trail: the single write point for accountable operations (SEC-006, ADR 0016).

Rules this module enforces, each for a reason:

* **One operation, one row.** Audit is written only in the service layer (or, where
  no service exists, at the one place marked as sole writer). Two rows for one API
  call makes a filter on either action misleading.
* **`request_id` on every row.** Without it an audit entry cannot be joined to the
  logs from the same request, which is most of its investigative value. It is
  filled automatically from the request context, so a caller cannot forget it.
* **Minimized, redacted metadata.** Terminal bytes, file content, directory
  listings, search keywords, passwords, tokens, private keys and full server
  absolute paths never appear. `redact_mapping` is a backstop, not permission to
  pass secrets in.

Every action constant below must have a real write site. An action nobody writes
is a filter that silently returns nothing — the audit-side twin of the dead
`audit.view` permission — so `test_every_audit_action_has_a_write_site` fails on
one that does not.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import redact_mapping, request_id_var
from app.repositories.audit import AuditRepository

# --- P1: authentication, enrollment, node control plane (SEC-006) ---
USER_LOGIN = "user.login"
# A separate action, not a `result` field on user.login: the audit query API
# filters by action, and finding failed sign-ins is the entire point of recording
# them (brute force, credential stuffing). A metadata flag would not be findable.
USER_LOGIN_FAILED = "user.login_failed"
USER_LOGOUT = "user.logout"
ENROLLMENT_CREATE = "enrollment.create"
ENROLLMENT_REVOKE = "enrollment.revoke"
ENROLLMENT_USE = "enrollment.use"
NODE_REGISTER = "node.register"
NODE_DISABLE = "node.disable"
# P4-04: `node.disable` used to record enables too, with the direction hidden in
# metadata — an operator filtering for "who disabled this node" also got the
# re-enables. The action now names what happened.
NODE_ENABLE = "node.enable"
NODE_REMOVE = "node.remove"
CREDENTIAL_REVOKE = "credential.revoke"
# P4-04: rotation used to be recorded as a revocation. It revokes *and* issues, so
# it is a distinct operation.
CREDENTIAL_ROTATE = "credential.rotate"
# --- P2: session / terminal lifecycle (ADR 0013) ---
SESSION_CREATE = "session.create"
SESSION_ATTACH = "session.attach"
SESSION_TAKEOVER = "session.takeover"
SESSION_TERMINATE = "session.terminate"
SESSION_FAILED = "session.failed"
# --- P3: a sensitive file preview was refused (SEC-006). Classification and
# extension only — never the rel_path, filename stem, absolute path or content
# (ADR 0014). ---
FILE_SENSITIVE_READ_DENIED = "file.sensitive_read_denied"
# --- P4: daemon update (SEC-006 item 8, ADR 0017) ---
# Two actions, not one with a `phase` field: the request and the outcome can be
# minutes apart and can be separated by a Central restart, so a filter for "which
# updates were started" and one for "which ones failed" are different questions
# with different answers. A single action would make the first unanswerable.
DAEMON_UPDATE_STARTED = "daemon.update_started"
DAEMON_UPDATE_RESULT = "daemon.update_result"
# --- P4: security events ---
# An authorization refusal on a mutation or a cross-owner access attempt. Ordinary
# read 403s and validation 422s are deliberately *not* audited: they are frequent,
# uninteresting, and would bury the signal (ADR 0016).
AUTHZ_DENIED = "authz.denied"
# --- P11: port forwarding through a third-party provider (ADR 0022) ---
# The integration actions are separate from the tunnel actions because they answer different
# questions: "who decided this organisation would use this service, and with whose account"
# versus "who exposed which port on which machine". A single action would make the first
# unanswerable, and it is the one with the longer consequences.
INTEGRATION_ENABLE = "integration.enable"
INTEGRATION_DISABLE = "integration.disable"
# Records the credential's *fingerprint*, never the credential. That is what lets a later
# investigation say which credential a given tunnel was opened with.
INTEGRATION_CREDENTIAL_SET = "integration.credential_set"
INTEGRATION_NODE_SETTINGS_UPDATED = "integration.node_settings_updated"
# The tunnel-level actions. `url` is deliberately absent from all three: it is assigned by
# the provider and it *is* part of the access credential (under `public` protection it is the
# whole of it), so writing it into a table every `audit.view` holder may read would hand each
# of them access to the preview after the fact.
TUNNEL_CREATE = "tunnel.create"
TUNNEL_CLOSE = "tunnel.close"
# A separate action rather than a flag on `tunnel.create`: "who decided this port would be
# reachable by anyone holding the link" is the question that gets asked later, and a metadata
# field inside another action cannot be filtered on.
TUNNEL_PUBLIC_ACKNOWLEDGED = "tunnel.public_acknowledged"
# --- Privileged node posture (ADR 0023) ---
# Recorded when a node's reported posture changes: its system terminal became able to
# reach root through sudo, or stopped being able to. The change happens on the machine
# (systemd unit + sudoers), so the platform is the only place it is written down at
# all — and "when did this node become privileged, and who was working on it then" is
# the question an incident review starts from. Not recorded on every register: a
# reconnect is not a change, and a row per heartbeat would bury the ones that matter.
NODE_POSTURE_CHANGED = "node.posture_changed"

# The closed vocabulary, used by the audit query API to reject unknown filter
# values rather than pattern-matching them into an arbitrary query surface.
ALL_ACTIONS: frozenset[str] = frozenset(
    {
        USER_LOGIN,
        USER_LOGIN_FAILED,
        USER_LOGOUT,
        ENROLLMENT_CREATE,
        ENROLLMENT_REVOKE,
        ENROLLMENT_USE,
        NODE_REGISTER,
        NODE_DISABLE,
        NODE_ENABLE,
        NODE_REMOVE,
        CREDENTIAL_REVOKE,
        CREDENTIAL_ROTATE,
        SESSION_CREATE,
        SESSION_ATTACH,
        SESSION_TAKEOVER,
        SESSION_TERMINATE,
        SESSION_FAILED,
        FILE_SENSITIVE_READ_DENIED,
        DAEMON_UPDATE_STARTED,
        DAEMON_UPDATE_RESULT,
        AUTHZ_DENIED,
        INTEGRATION_ENABLE,
        INTEGRATION_DISABLE,
        INTEGRATION_CREDENTIAL_SET,
        INTEGRATION_NODE_SETTINGS_UPDATED,
        TUNNEL_CREATE,
        TUNNEL_CLOSE,
        TUNNEL_PUBLIC_ACKNOWLEDGED,
        NODE_POSTURE_CHANGED,
    }
)

# Keys that must never reach audit metadata. Asserted by test, because the ban is
# only as good as its enforcement.
FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "content",
        "contents",
        "data",
        "body",
        "output",
        "input",
        "bytes",
        "keyword",
        "password",
        "token",
        "secret",
        "credential",
        "private_key",
        "signature",
        "absolute_path",
        "abs_path",
        "rel_path",
        "filename",
        "workspace_path",
    }
)


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AuditRepository(session)

    async def record(
        self,
        action: str,
        *,
        user_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append one audit row.

        `request_id` defaults to the current request's id so an audit row can
        always be joined to that request's logs. A daemon-initiated or background
        event passes its own correlation id, or none — in which case `source` says
        so rather than leaving the field silently absent.
        """
        payload: dict[str, Any] = dict(metadata or {})
        correlation = request_id or request_id_var.get()
        if correlation is not None:
            payload["request_id"] = correlation
        else:
            payload.setdefault("source", "system")
        # Never persist secrets, terminal content or oversized payloads.
        await self._repo.add(
            action,
            user_id=user_id,
            node_id=node_id,
            session_id=session_id,
            metadata=redact_mapping(payload) if payload else {},
        )
