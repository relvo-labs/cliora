"""Session lifecycle domain service and state machine (P2-05, ADR 0013).

Central owns durable session metadata and the legal state transitions; it never
accepts a command/binary/shell string — only a runtime id, an allowed-root
workspace path, a name and a terminal size (SEC-002). The actual filesystem and
process safety checks are the daemon's job; Central does prefix authorization of
the workspace against the node's enabled roots and relays start/stop through the
correlated request path (services/registry.py).
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import Node, TerminalSession
from app.repositories.nodes import NodeRepository
from app.repositories.sessions import SessionRepository
from app.services import audit
from app.services.nodes import ensure_node_enabled
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.settings import Settings, get_settings

# --- State machine (FR-SESSION-002, ADR 0013). Values match the daemon's
# lowercase session states so a status_changed frame maps directly. ---
STARTING = "starting"
RUNNING = "running"
DISCONNECTED = "disconnected"
EXITED = "exited"
FAILED = "failed"
TERMINATING = "terminating"
TERMINATED = "terminated"

TERMINAL_STATES = frozenset({EXITED, FAILED, TERMINATED})

_TRANSITIONS: dict[str, frozenset[str]] = {
    STARTING: frozenset({RUNNING, FAILED, EXITED}),
    RUNNING: frozenset({DISCONNECTED, EXITED, TERMINATING, FAILED}),
    DISCONNECTED: frozenset({RUNNING, EXITED, TERMINATING, FAILED}),
    TERMINATING: frozenset({TERMINATED, FAILED, EXITED}),
    EXITED: frozenset(),
    FAILED: frozenset(),
    TERMINATED: frozenset(),
}

# The system terminal (FR-SHELL-001, ADR 0021). Named because several modules
# branch on it and a bare "shell" literal scattered across them would drift.
SHELL_RUNTIME = "shell"

RUNTIMES = frozenset({"claude", "codex", SHELL_RUNTIME, "fake"})


def can_transition(frm: str, to: str) -> bool:
    return to in _TRANSITIONS.get(frm, frozenset())


def authorize_workspace(node: Node, workspace: str) -> None:
    """Prefix-authorize `workspace` against the node's enabled roots.

    Public because `services/favorites.py` must use *this* function rather than its own
    copy: a stored favourite that could not start a session must not be storable as a
    shortcut to starting one, and two implementations of the same prefix rule would
    eventually disagree.

    Uses PurePosixPath.relative_to so a prefix collision (/a/projects vs
    /a/projects-other) is correctly rejected. This is Central's coarse gate;
    the daemon re-validates canonically after symlink resolution (P2-07).
    """
    if not workspace.startswith("/"):
        raise ApiError(
            "WORKSPACE_OUTSIDE_ALLOWED_ROOT",
            "Workspace must be an absolute path inside an allowed root",
            status.HTTP_400_BAD_REQUEST,
        )
    target = PurePosixPath(workspace)
    for root in node.workspace_roots:
        if not root.is_enabled:
            continue
        try:
            target.relative_to(PurePosixPath(root.path))
            return
        except ValueError:
            continue
    raise ApiError(
        "WORKSPACE_OUTSIDE_ALLOWED_ROOT",
        "Workspace is outside the node's allowed roots",
        status.HTTP_400_BAD_REQUEST,
    )


def _require_runtime(node: Node, runtime: str) -> None:
    if runtime not in RUNTIMES:
        raise ApiError("RUNTIME_NOT_ALLOWED", "Runtime is not allowed")
    if runtime == "fake":
        return  # test/dev runtime is not enumerated in node.runtimes
    # `shell` deliberately does *not* get the same shortcut: the node's report is
    # the only place its availability (and an operator's `enabled: false`) is
    # expressed, so skipping it would make the node's veto unenforceable.
    match = next((r for r in node.runtimes if r.runtime == runtime), None)
    if match is None or not match.available:
        raise ApiError(
            "RUNTIME_NOT_FOUND",
            "Runtime is not available on this node",
            status.HTTP_409_CONFLICT,
        )


def _payload_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None


class SessionService:
    def __init__(
        self,
        session: AsyncSession,
        registry: NodeConnectionRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = SessionRepository(session)
        self._nodes = NodeRepository(session)
        self._audit = audit.AuditService(session)
        self._registry = registry or get_node_registry()

    async def get(self, session_id: uuid.UUID) -> TerminalSession:
        session = await self._repo.get(session_id)
        if session is None:
            raise ApiError("SESSION_NOT_FOUND", "Session not found", status.HTTP_404_NOT_FOUND)
        return session

    async def list(
        self,
        *,
        node_id: uuid.UUID | None = None,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TerminalSession]:
        return list(
            await self._repo.list(node_id=node_id, status=status_filter, limit=limit, offset=offset)
        )

    async def create(
        self,
        *,
        actor_id: uuid.UUID,
        node_id: uuid.UUID,
        runtime: str,
        name: str,
        workspace: str,
        rows: int,
        columns: int,
    ) -> TerminalSession:
        node = await self._nodes.get(node_id)
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
        ensure_node_enabled(node)  # NODE_DISABLED
        if not self._registry.is_connected(node_id):
            raise ApiError("NODE_OFFLINE", "Node is not connected", status.HTTP_409_CONFLICT)
        _require_runtime(node, runtime)
        authorize_workspace(node, workspace)
        if rows < 2 or rows > 300 or columns < 2 or columns > 500:
            raise ApiError("INVALID_TERMINAL_SIZE", "Terminal size out of range")
        active = await self._repo.active_count_for_node(node_id)
        if active >= self._settings.sessions_per_node_max:
            raise ApiError(
                "SESSION_LIMIT_REACHED",
                "Node has reached its session limit",
                status.HTTP_409_CONFLICT,
            )
        # Both halves of tech §23 #14. Until P4-14 only the per-node cap existed, which
        # left one account able to hold `nodes x (per_node - 1)` sessions without ever
        # tripping a limit — a bound that grows with the fleet is not a bound. The same
        # error code on purpose: from the caller's side it is the same situation ("you
        # cannot start another one now"), and a distinct code would only tell them which
        # ceiling to work around.
        mine = await self._repo.active_count_for_user(actor_id)
        if mine >= self._settings.sessions_per_user_max:
            raise ApiError(
                "SESSION_LIMIT_REACHED",
                "You have reached your session limit",
                status.HTTP_409_CONFLICT,
            )

        session = TerminalSession(
            id=uuid.uuid4(),
            node_id=node_id,
            user_id=actor_id,
            name=name,
            runtime=runtime,
            workspace=workspace,
            status=STARTING,
            rows=rows,
            columns=columns,
        )
        self._repo.add(session)
        await self._session.flush()
        await self._audit.record(
            audit.SESSION_CREATE,
            user_id=actor_id,
            node_id=node_id,
            session_id=session.id,
            metadata={"runtime": runtime},
        )

        try:
            message = await self._registry.request(
                node_id,
                "session.start",
                {
                    "session_id": str(session.id),
                    "runtime": runtime,
                    "workspace": workspace,
                    "rows": rows,
                    "columns": columns,
                },
                timeout_seconds=self._settings.session_start_timeout_seconds,
            )
        except ApiError as exc:
            await self._fail(session, exc.code, actor_id=actor_id)
            raise

        if message.type == "session.started" and message.success:
            self._transition(session, RUNNING)
            session.pid = _payload_int(message.payload, "pid")
            session.started_at = now_utc()
            session.last_activity_at = session.started_at
            return session

        code = "SESSION_START_FAILED"
        if message.error and isinstance(message.error.get("code"), str):
            code = str(message.error["code"])
        await self._fail(session, code, actor_id=actor_id)
        raise ApiError(
            "SESSION_START_FAILED", "Runtime failed to start", status.HTTP_502_BAD_GATEWAY
        )

    async def open_shell(
        self, *, actor_id: uuid.UUID, parent: TerminalSession, rows: int, columns: int
    ) -> TerminalSession:
        """Open a system terminal inside an existing CLI session (FR-SHELL-001).

        Deliberately not reachable through `create()`: the parent comes from the URL,
        so there is no code path that can produce a shell session without one. That
        is what keeps the New Session dialog and the Sessions list free of shells
        rather than relying on every caller to remember (ADR 0021).

        Authorization (`may_open_shell`) is the caller's job — the HTTP layer does it
        before we get here, the same split every other mutation uses.
        """
        node = await self._nodes.get(parent.node_id)
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
        ensure_node_enabled(node)
        if not self._registry.is_connected(node.id):
            raise ApiError("NODE_OFFLINE", "Node is not connected", status.HTTP_409_CONFLICT)
        # A node that disabled the shell, or has no usable binary, reports it
        # unavailable; this is where that veto takes effect.
        _require_runtime(node, SHELL_RUNTIME)
        if await self._repo.live_shell_for_parent(parent.id) is not None:
            raise ApiError(
                "SHELL_ALREADY_OPEN",
                "This session already has a system terminal",
                status.HTTP_409_CONFLICT,
            )
        session = await self.create(
            actor_id=actor_id,
            node_id=parent.node_id,
            runtime=SHELL_RUNTIME,
            name=f"{parent.name} · terminal",
            # The shell starts where the CLI is. It can walk out of the directory
            # afterwards — that is the trade recorded in ADR 0021 — but the launch
            # point is still an allowed root, and `create()` re-checks it.
            workspace=parent.workspace,
            rows=rows,
            columns=columns,
        )
        session.parent_session_id = parent.id
        await self._session.flush()
        return session

    async def terminate(self, *, actor_id: uuid.UUID, session_id: uuid.UUID) -> TerminalSession:
        session = await self.get(session_id)
        if session.status in TERMINAL_STATES:
            raise ApiError(
                "SESSION_INVALID_STATE",
                "Session has already ended",
                status.HTTP_409_CONFLICT,
            )
        self._transition(session, TERMINATING)
        message = await self._registry.request(
            session.node_id,
            "session.stop",
            {"session_id": str(session.id)},
            timeout_seconds=self._settings.session_stop_timeout_seconds,
        )
        self._transition(session, TERMINATED)
        session.ended_at = now_utc()
        session.exit_code = _payload_int(message.payload, "exit_code")
        await self._audit.record(
            audit.SESSION_TERMINATE,
            user_id=actor_id,
            node_id=session.node_id,
            session_id=session.id,
            metadata={
                "forced": bool(message.payload.get("forced")),
                "runtime": session.runtime,
            },
        )
        await self._terminate_children(session, actor_id=actor_id)
        return session

    async def _terminate_children(self, parent: TerminalSession, *, actor_id: uuid.UUID) -> None:
        """Stop any system terminal that belonged to a session that just ended.

        Best-effort per child: a node that fails to stop one shell must not stop the
        parent from being reported terminated, and the row is marked ended either way
        so the node's own reconciliation is what cleans up the process. Leaving the
        row alive would be worse — it would occupy the parent's unique-index slot and
        block the user from ever opening another terminal.
        """
        for child in await self._repo.live_children(parent.id):
            try:
                await self._registry.request(
                    child.node_id,
                    "session.stop",
                    {"session_id": str(child.id)},
                    timeout_seconds=self._settings.session_stop_timeout_seconds,
                )
            except ApiError:
                pass
            child.status = TERMINATED
            child.ended_at = now_utc()
            await self._audit.record(
                audit.SESSION_TERMINATE,
                user_id=actor_id,
                node_id=child.node_id,
                session_id=child.id,
                metadata={"runtime": child.runtime, "reason": "parent_ended"},
            )

    async def delete(self, *, session_id: uuid.UUID) -> None:
        session = await self.get(session_id)
        if session.status not in TERMINAL_STATES:
            raise ApiError(
                "SESSION_INVALID_STATE",
                "Only ended sessions can be deleted",
                status.HTTP_409_CONFLICT,
            )
        await self._session.delete(session)

    async def apply_status_changed(
        self, session_id: uuid.UUID, new_status: str, *, exit_code: int | None = None
    ) -> TerminalSession | None:
        """Apply a daemon-pushed status_changed event (P2-08). Ignores unknown
        sessions and illegal transitions (logged by the caller)."""
        session = await self._repo.get(session_id)
        if session is None or not can_transition(session.status, new_status):
            return None
        session.status = new_status
        if new_status in TERMINAL_STATES:
            session.ended_at = now_utc()
            if exit_code is not None:
                session.exit_code = exit_code
            # A CLI that exits on its own reaches a terminal state here rather than
            # through `terminate()`, and its shell must not outlive it either
            # (FR-SHELL-001.AC-04). `actor_id` is the session owner: nobody pressed
            # a button, so attributing it to the owner is the honest record.
            await self._terminate_children(session, actor_id=session.user_id)
        elif new_status == RUNNING:
            session.last_activity_at = now_utc()
        return session

    def _transition(self, session: TerminalSession, to: str) -> None:
        if not can_transition(session.status, to):
            raise ApiError(
                "SESSION_INVALID_STATE",
                f"Illegal transition {session.status} -> {to}",
                status.HTTP_409_CONFLICT,
            )
        session.status = to

    async def _fail(self, session: TerminalSession, code: str, *, actor_id: uuid.UUID) -> None:
        if can_transition(session.status, FAILED):
            session.status = FAILED
        session.error_message = code
        session.ended_at = now_utc()
        await self._audit.record(
            audit.SESSION_FAILED,
            user_id=actor_id,
            node_id=session.node_id,
            session_id=session.id,
            metadata={"error_code": code},
        )
