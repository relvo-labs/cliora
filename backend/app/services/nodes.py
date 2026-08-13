"""Node registration, credential issuance, and node authentication.

Covers FR-NODE-001 and the credential half of FR-INSTALL/SEC-003 (ADR 0008).
Registration runs in one transaction: spend the enrollment token, create the
node with its runtimes/workspace roots, and issue a credential whose secret is
returned once and stored only as a keyed hash.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import Node, NodeCredential, NodeRuntime, NodeWorkspaceRoot
from app.repositories.node_metrics import NodeMetricRepository
from app.repositories.nodes import NodeCredentialRepository, NodeRepository
from app.security.node_keys import valid_public_key, verify_signature
from app.services import audit
from app.services.enrollment import EnrollmentService
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.settings import Settings, get_settings


def apply_tunnel_report(node: Node, report: TunnelReportInput | None) -> None:
    """Store a node's port-forwarding self-report, or leave the last one alone.

    `tunnel_prereq_ok` is the AND of the three environment checks and is stored as its own
    column so "which nodes are ready" is an indexable question rather than a JSON scan. The
    three values are kept individually as well, because "not ready" without saying *which*
    prerequisite is missing sends the operator to check all three.
    """
    if report is None:
        return
    node.tunnel_veto = report.veto
    node.tunnel_prereq_ok = (
        report.ssh_available
        and report.egress_ok
        and report.known_hosts_ok
        and report.daemon_supports_tunnel
    )
    node.tunnel_prereq_detail = {
        "ssh_available": report.ssh_available,
        "egress_ok": report.egress_ok,
        "known_hosts_ok": report.known_hosts_ok,
        "daemon_supports_tunnel": report.daemon_supports_tunnel,
    }
    node.tunnel_local_allowed_ports = report.allowed_ports
    node.tunnel_local_max = report.max_tunnels
    node.tunnel_reported_at = now_utc()


def ensure_node_enabled(node: Node) -> None:
    """Guard for establishing operations against a node (FR-NODE-005).

    A disabled node keeps its live connection but must refuse any new
    establishing operation (session start etc., which arrive in P2). This is the
    single choke point those code paths call, returning the stable NODE_DISABLED
    code so the behaviour is uniform and testable today.
    """
    if not node.is_enabled:
        raise ApiError("NODE_DISABLED", "Node is disabled", status.HTTP_409_CONFLICT)


@dataclass(slots=True)
class RuntimeInput:
    runtime: str
    available: bool
    version: str | None = None
    binary_path: str | None = None
    checked_at: datetime | None = None
    # What the node measured, not what its config asked for (ADR 0023 D3). Defaults to
    # False so an older daemon — which sends no such field — reads as "sandboxed",
    # never as "unknown".
    sandbox_bypass: bool = False


@dataclass(slots=True)
class WorkspaceRootInput:
    path: str
    is_enabled: bool
    display_name: str | None = None


@dataclass(slots=True)
class TunnelReportInput:
    """What a node says about its own port-forwarding prerequisites (P11, ADR 0022).

    Prerequisites, not a credential: the provider credential is the platform's (D18), so the
    node has nothing to report about it. Central stores this so it can answer "can this node
    forward a port" *before* somebody presses a button and waits twenty seconds for a
    timeout — and so the answer survives the node going offline, which is why
    `tunnel_reported_at` is written alongside: "not ready" and "not known yet" are different
    states and the UI has to be able to tell them apart.
    """

    veto: bool
    ssh_available: bool
    egress_ok: bool
    known_hosts_ok: bool
    daemon_supports_tunnel: bool
    allowed_ports: list[str] | None = None
    max_tunnels: int | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> TunnelReportInput | None:
        """Build from a `node.register`/`node.runtime_status` `tunnel` object.

        Returns None when the key is absent, which is what an agentd older than P11 sends.
        Absent is not "false": nothing is written, so the node keeps its last known report
        and `tunnel_reported_at` stays NULL until a daemon that has the capability speaks.
        """
        if not isinstance(payload, dict):
            return None
        ports = payload.get("allowed_ports")
        limit = payload.get("max_tunnels")
        return cls(
            veto=bool(payload.get("veto")),
            ssh_available=bool(payload.get("ssh_available")),
            egress_ok=bool(payload.get("egress_ok")),
            known_hosts_ok=bool(payload.get("known_hosts_ok")),
            daemon_supports_tunnel=bool(payload.get("daemon_supports_tunnel")),
            allowed_ports=[str(p) for p in ports] if isinstance(ports, list) else None,
            max_tunnels=limit if isinstance(limit, int) and limit > 0 else None,
        )


@dataclass(slots=True)
class RegisterNodeInput:
    name: str
    hostname: str
    os: str
    os_version: str
    architecture: str
    daemon_version: str
    run_user: str
    public_key: str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    runtimes: list[RuntimeInput] = field(default_factory=list)
    workspace_roots: list[WorkspaceRootInput] = field(default_factory=list)
    tunnel: TunnelReportInput | None = None
    # The node's own report that its system terminal can reach root through sudo
    # (ADR 0023). False for a daemon that predates the field, which is the correct
    # reading: a posture nobody has claimed is not one the console may imply.
    privileged_terminal: bool = False
    # The node's own report that the platform may write images into its workspaces
    # (ADR 0024 W4). False for a daemon that predates the field, which is the
    # correct reading: the console hides the entry point rather than offering a
    # button that would fail.
    image_upload: bool = False
    # The node's own report that the platform may place arbitrary files at
    # user-chosen paths in its workspaces (ADR 0026 §9). False for a daemon that
    # predates the field — and separate from image_upload, because a machine may
    # accept screenshots while refusing this.
    file_upload: bool = False
    context_projection: bool = False
    # The node's own report that its agentd can run agent work unattended (0.9.0+,
    # ADR 0029 §7). The fourth capability of the same shape, and false for anything
    # older — which is the correct reading: that daemon has no runner mode, so it is
    # never offered a run and the console says which version would be needed.
    agent_runner: bool = False


@dataclass(frozen=True, slots=True)
class RegisteredNode:
    node: Node


class NodeRegistrationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._nodes = NodeRepository(session)
        self._credentials = NodeCredentialRepository(session)
        self._enrollment = EnrollmentService(session, settings)
        self._audit = audit.AuditService(session)
        self._metrics = NodeMetricRepository(session)

    async def register(self, enrollment_token: str, data: RegisterNodeInput) -> RegisteredNode:
        if not valid_public_key(data.public_key):
            raise ApiError("INVALID_ARGUMENT", "public_key must be a raw Ed25519 public key")
        token = await self._enrollment.consume(enrollment_token)

        node = Node(
            name=data.name,
            hostname=data.hostname,
            os=data.os,
            os_version=data.os_version,
            architecture=data.architecture,
            daemon_version=data.daemon_version,
            run_user=data.run_user,
            status="offline",
        )
        node.runtimes = [
            NodeRuntime(
                runtime=r.runtime,
                available=r.available,
                version=r.version,
                binary_path=r.binary_path,
                checked_at=r.checked_at,
                sandbox_bypass=r.sandbox_bypass,
            )
            for r in data.runtimes
        ]
        node.workspace_roots = [
            NodeWorkspaceRoot(path=w.path, display_name=w.display_name, is_enabled=w.is_enabled)
            for w in data.workspace_roots
        ]
        self._nodes.add(node)
        await self._session.flush()

        self._credentials.add(
            NodeCredential(
                node_id=node.id,
                secret_hash=None,
                public_key=data.public_key,
                algorithm="ed25519",
                version=1,
            )
        )
        await self._audit.record(
            audit.NODE_REGISTER,
            node_id=node.id,
            metadata={"name": node.name, "hostname": node.hostname},
        )
        await self._audit.record(
            audit.ENROLLMENT_USE,
            user_id=token.created_by,
            node_id=node.id,
            metadata={
                "token_id": str(token.id),
                "result": "success",
                "hostname": data.hostname,
            },
        )
        return RegisteredNode(node=node)

    async def persist_registration(
        self, node_id: uuid.UUID, data: RegisterNodeInput
    ) -> Node | None:
        """Refresh a node's metadata from a post-auth node.register announce."""
        node = await self._nodes.get(node_id)
        if node is None:
            return None
        node.name = data.name
        node.hostname = data.hostname
        node.os = data.os
        node.os_version = data.os_version
        node.architecture = data.architecture
        node.daemon_version = data.daemon_version
        node.run_user = data.run_user
        node.last_seen_at = now_utc()
        # The daemon's announce is authoritative; replace the child rows.
        # Clear + flush so orphan deletes happen before the new inserts,
        # otherwise the (node_id, runtime) unique constraint is violated.
        node.runtimes.clear()
        node.workspace_roots.clear()
        await self._session.flush()
        node.runtimes = [
            NodeRuntime(
                runtime=r.runtime,
                available=r.available,
                version=r.version,
                binary_path=r.binary_path,
                checked_at=r.checked_at,
                sandbox_bypass=r.sandbox_bypass,
            )
            for r in data.runtimes
        ]
        node.workspace_roots = [
            NodeWorkspaceRoot(path=w.path, display_name=w.display_name, is_enabled=w.is_enabled)
            for w in data.workspace_roots
        ]
        apply_tunnel_report(node, data.tunnel)
        # Only a *change* is audited. Every reconnect re-registers, so recording the
        # posture each time would bury the announce that matters under one row per
        # reconnect — and "when did this node become able to reach root" is the
        # question an incident review starts from (ADR 0023 §2.5).
        posture_changed = (
            node.privileged_terminal != data.privileged_terminal
            or node.image_upload != data.image_upload
            or node.file_upload != data.file_upload
            or node.context_projection != data.context_projection
            or node.agent_runner != data.agent_runner
        )
        previous_posture = node.privileged_terminal
        previous_upload = node.image_upload
        previous_file_upload = node.file_upload
        node.privileged_terminal = data.privileged_terminal
        node.image_upload = data.image_upload
        node.file_upload = data.file_upload
        node.context_projection = data.context_projection
        previous_agent_runner = node.agent_runner
        node.agent_runner = data.agent_runner
        await self._audit.record(
            audit.NODE_REGISTER, node_id=node.id, metadata={"hostname": node.hostname}
        )
        if posture_changed:
            await self._audit.record(
                audit.NODE_POSTURE_CHANGED,
                node_id=node.id,
                metadata={
                    "privileged_terminal": data.privileged_terminal,
                    "previous": previous_posture,
                    "image_upload": data.image_upload,
                    "previous_image_upload": previous_upload,
                    "file_upload": data.file_upload,
                    "context_projection": data.context_projection,
                    "previous_file_upload": previous_file_upload,
                    "agent_runner": data.agent_runner,
                    "previous_agent_runner": previous_agent_runner,
                },
            )
        return node

    async def update_system_info(
        self, node_id: uuid.UUID, payload: dict[str, object]
    ) -> Node | None:
        """Apply a `node.system_info` frame (OS/arch/kernel/run_user refresh)."""
        node = await self._nodes.get(node_id)
        if node is None:
            return None
        node.os = str(payload["os"])
        node.os_version = str(payload["os_version"])
        node.architecture = str(payload["architecture"])
        node.run_user = str(payload["run_user"])
        kernel = payload.get("kernel")
        if isinstance(kernel, str):
            node.node_metadata = {**(node.node_metadata or {}), "kernel": kernel}
        node.last_seen_at = now_utc()
        return node

    async def update_runtime_status(
        self,
        node_id: uuid.UUID,
        runtimes: list[RuntimeInput],
        tunnel: TunnelReportInput | None = None,
    ) -> Node | None:
        """Apply a `node.runtime_status` frame (claude/codex detection refresh)."""
        node = await self._nodes.get(node_id)
        if node is None:
            return None
        # Clear + flush so orphan deletes precede the new inserts (the
        # (node_id, runtime) unique constraint would otherwise be violated).
        node.runtimes.clear()
        await self._session.flush()
        node.runtimes = [
            NodeRuntime(
                runtime=r.runtime,
                available=r.available,
                version=r.version,
                binary_path=r.binary_path,
                checked_at=r.checked_at,
                sandbox_bypass=r.sandbox_bypass,
            )
            for r in runtimes
        ]
        apply_tunnel_report(node, tunnel)
        node.last_seen_at = now_utc()
        return node

    async def record_heartbeat(self, node_id: uuid.UUID) -> None:
        await self._nodes.touch_last_seen(node_id, now_utc())

    async def persist_metric_sample(self, node_id: uuid.UUID, payload: dict[str, Any]) -> bool:
        """Append one resource sample from a heartbeat payload (P4-06).

        Best-effort by design. Heartbeat processing decides a node's liveness, so it
        must not fail or slow down because a history row could not be written:

        * the insert runs in a **savepoint**, so a failure (a hard-deleted node, a
          constraint, a dead connection) rolls back only this row instead of
          poisoning the transaction that is also recording `last_seen_at`;
        * any database error is counted and swallowed. `metric_persist_error_total`
          is therefore the only evidence that the history has gaps, which is why
          ADR 0018 alerts on it rather than treating it as a debug counter.

        Rate limiting is the caller's job (`registry.claim_metric_sample`).
        """
        raw = payload.get("resources")
        resources = raw if isinstance(raw, dict) else {}
        active = payload.get("active_sessions")
        try:
            async with self._session.begin_nested():
                self._metrics.add(
                    node_id=node_id,
                    sampled_at=now_utc(),
                    resources={
                        name: value if isinstance(value, int | float) else None
                        for name, value in resources.items()
                    },
                    active_sessions=active if isinstance(active, int) else None,
                )
        except SQLAlchemyError:
            metrics.increment(metrics.METRIC_PERSIST_ERROR_TOTAL, reason="write_failed")
            return False
        return True

    async def authenticate_signature(
        self, node_id: uuid.UUID, challenge_id: str, nonce: str, signature: str
    ) -> Node:
        """Verify a daemon signature against the stored Ed25519 public key.

        Raises NODE_AUTH_FAILED for unknown/deleted node, missing/revoked
        credential, or a bad secret. Disabled nodes still authenticate (the
        connection is allowed; new operations are refused elsewhere per FR-NODE-005).
        """
        failure = ApiError(
            "NODE_AUTH_FAILED", "Node authentication failed", status.HTTP_401_UNAUTHORIZED
        )
        node = await self._nodes.get(node_id)
        if node is None:
            raise failure
        credential = await self._credentials.active_for_node(node_id)
        if (
            credential is None
            or credential.algorithm != "ed25519"
            or credential.public_key is None
            or not verify_signature(credential.public_key, signature, node_id, challenge_id, nonce)
        ):
            raise failure
        return node


class NodeManagementService:
    """Admin operations: list/get, disable/enable, credential revoke/rotate, and
    soft-delete (remove). Actions that invalidate a credential also sever the
    live socket via the connection registry so the node cannot keep operating on
    a revoked key (SEC-006)."""

    def __init__(
        self, session: AsyncSession, registry: NodeConnectionRegistry | None = None
    ) -> None:
        self._session = session
        self._nodes = NodeRepository(session)
        self._credentials = NodeCredentialRepository(session)
        self._audit = audit.AuditService(session)
        self._registry = registry or get_node_registry()

    async def get(self, node_id: uuid.UUID) -> Node | None:
        return await self._nodes.get(node_id)

    async def list_active(self) -> list[Node]:
        return list(await self._nodes.list_active())

    async def _require(self, node_id: uuid.UUID) -> Node:
        node = await self._nodes.get(node_id)
        if node is None:
            raise ApiError("NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
        return node

    async def _sever_connection(self, node_id: uuid.UUID) -> None:
        """Evict and close any live socket for a node (credential no longer valid)."""
        connection = await self._registry.evict(node_id)
        if connection is not None:
            with suppress(Exception):
                await connection.websocket.close(code=1008)

    async def set_enabled(
        self,
        node_id: uuid.UUID,
        *,
        enabled: bool,
        actor_id: uuid.UUID,
        terminate_sessions: bool = False,
    ) -> Node:
        """Toggle a node's enabled flag.

        Disabling keeps the connection alive but blocks new establishing operations
        (ensure_node_enabled). Whether the sessions already running are torn down is
        the administrator's choice (FR-NODE-005): `terminate_sessions` stops each of
        them, and leaving it false lets existing work finish while nothing new starts.
        """
        node = await self._require(node_id)
        node.is_enabled = enabled
        terminated = (
            await self._terminate_running_sessions(node.id, actor_id=actor_id)
            if terminate_sessions and not enabled
            else []
        )
        # Tunnels are closed whether or not sessions are, and that asymmetry is deliberate: a
        # session is work in progress that may reasonably finish, while a tunnel is an open
        # door to the internet. "Stop anything new from starting" cannot leave the doors open.
        tunnels_closed = (
            await self._close_tunnels(node.id, actor_id=actor_id, reason="node_disabled")
            if not enabled
            else 0
        )
        # The action names the direction: filtering for "who disabled this node"
        # must not also return the re-enables (P4-04).
        await self._audit.record(
            audit.NODE_ENABLE if enabled else audit.NODE_DISABLE,
            user_id=actor_id,
            node_id=node.id,
            metadata={
                "terminate_sessions": terminate_sessions,
                # The count, not the ids: the per-session terminations write their
                # own rows, and this row should not duplicate them.
                "sessions_terminated": len(terminated),
                "tunnels_closed": tunnels_closed,
            },
        )
        return node

    async def _close_tunnels(self, node_id: uuid.UUID, *, actor_id: uuid.UUID, reason: str) -> int:
        """End every live tunnel on a node.

        Imported locally for the same reason as the session service: `TunnelService` imports
        `ensure_node_enabled` from this module.

        The tunnel would read as `unavailable` once the socket goes anyway, but a row left
        live keeps counting against the fleet budget and both caps until its TTL runs out —
        so "disable this node" would silently consume part of the platform's tunnel budget.
        """
        from app.services.tunnels import TunnelService

        service = TunnelService(self._session, registry=self._registry)
        return await service.close_for_node(node_id, actor_id=actor_id, reason=reason)

    async def _terminate_running_sessions(
        self, node_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Stop every session still running on a node, best effort.

        Imported here rather than at module scope: SessionService already imports
        `ensure_node_enabled` from this module.

        One session that will not stop must not leave the rest running, so each
        failure is recorded and the loop continues. The node is disabled either way
        — that part has already been applied and does not depend on the daemon
        answering.
        """
        from app.repositories.sessions import SessionRepository
        from app.services.sessions import SessionService

        sessions = SessionService(self._session, self._registry)
        terminated: list[uuid.UUID] = []
        for row in await SessionRepository(self._session).list_active_for_node(node_id):
            try:
                await sessions.terminate(actor_id=actor_id, session_id=row.id)
            except ApiError:
                # Already ended, or the daemon did not answer within the relay
                # budget. Audited by `terminate` itself where it got that far.
                continue
            terminated.append(row.id)
        return terminated

    async def _end_sessions_for_removal(
        self, node_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> tuple[int, int]:
        """End every active session before the node identity is made unusable.

        A reachable daemon gets a real ``session.stop`` first. If it cannot answer,
        the durable row is failed locally: after credential revocation and soft
        deletion this node id can never reconnect to deliver a later terminal state.

        Returns ``(ended, forced)`` for the node.remove audit metadata.
        """
        from app.repositories.sessions import SessionRepository
        from app.services.sessions import TERMINAL_STATES, SessionService

        service = SessionService(self._session, self._registry)
        rows = list(await SessionRepository(self._session).list_active_for_node(node_id))
        forced = 0
        for row in rows:
            # A parent termination may already have ended its shell child.
            if row.status in TERMINAL_STATES:
                continue
            try:
                await service.terminate(actor_id=actor_id, session_id=row.id)
            except ApiError:
                if row.status not in TERMINAL_STATES:
                    await service.fail_for_removed_node(session=row, actor_id=actor_id)
                    forced += 1
        return len(rows), forced

    async def revoke_credential(self, node_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        """Revoke all active credentials and drop the live connection immediately
        (stronger than disable: the node must re-enroll to reconnect)."""
        node = await self._require(node_id)
        await self._credentials.revoke_all(node.id, now_utc())
        # Before the socket is severed, so the node is still reachable to be told (P11): a
        # revoked node cannot reconnect, and a tunnel left running on it would outlive the
        # platform's ability to close it.
        await self._close_tunnels(node.id, actor_id=actor_id, reason="credential_revoked")
        await self._sever_connection(node.id)
        await self._audit.record(audit.CREDENTIAL_REVOKE, user_id=actor_id, node_id=node.id)

    async def rotate_credential(
        self, node_id: uuid.UUID, *, public_key: str, actor_id: uuid.UUID
    ) -> NodeCredential:
        """Rotate to a fresh credential version: revoke the current one, issue the
        next version bound to the new public key, and sever the live socket so the
        daemon re-authenticates with the rotated key (no version gap)."""
        node = await self._require(node_id)
        if not valid_public_key(public_key):
            raise ApiError("INVALID_ARGUMENT", "public_key must be a raw Ed25519 public key")
        await self._credentials.revoke_all(node.id, now_utc())
        version = await self._credentials.next_version(node.id)
        credential = NodeCredential(
            node_id=node.id,
            secret_hash=None,
            public_key=public_key,
            algorithm="ed25519",
            version=version,
        )
        self._credentials.add(credential)
        await self._sever_connection(node.id)
        # A rotation revokes *and* issues; recording it as a plain revocation lost
        # that distinction (P4-04).
        await self._audit.record(
            audit.CREDENTIAL_ROTATE,
            user_id=actor_id,
            node_id=node.id,
            metadata={"rotated_to_version": version},
        )
        return credential

    async def remove(self, node_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        """Soft delete the node after closing everything tied to its identity.

        Session rows remain as history, but none may remain active or visible in the
        fleet list once this node can no longer reconnect.
        """
        node = await self._require(node_id)
        sessions_ended, sessions_forced = await self._end_sessions_for_removal(
            node.id, actor_id=actor_id
        )
        node.deleted_at = now_utc()
        await self._credentials.revoke_all(node.id, now_utc())
        await self._close_tunnels(node.id, actor_id=actor_id, reason="node_removed")
        await self._sever_connection(node.id)
        # One operation, one row (ADR 0016). Removal implies credential revocation,
        # so the revocation is stated in metadata rather than written as a second
        # row — otherwise a filter on `credential.revoke` returns revocations that
        # were never a standalone administrative act.
        await self._audit.record(
            audit.NODE_REMOVE,
            user_id=actor_id,
            node_id=node.id,
            metadata={
                "credentials_revoked": True,
                "soft_delete": True,
                "sessions_ended": sessions_ended,
                "sessions_forced": sessions_forced,
            },
        )
