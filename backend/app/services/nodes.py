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


@dataclass(slots=True)
class WorkspaceRootInput:
    path: str
    is_enabled: bool
    display_name: str | None = None


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
            )
            for r in data.runtimes
        ]
        node.workspace_roots = [
            NodeWorkspaceRoot(path=w.path, display_name=w.display_name, is_enabled=w.is_enabled)
            for w in data.workspace_roots
        ]
        await self._audit.record(
            audit.NODE_REGISTER, node_id=node.id, metadata={"hostname": node.hostname}
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
        self, node_id: uuid.UUID, runtimes: list[RuntimeInput]
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
            )
            for r in runtimes
        ]
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
        """Toggle a node's enabled flag. Disabling keeps the connection alive but
        blocks new establishing operations (ensure_node_enabled). `terminate_sessions`
        is a reserved hook for P2 session teardown; recorded in audit today."""
        node = await self._require(node_id)
        node.is_enabled = enabled
        # The action names the direction: filtering for "who disabled this node"
        # must not also return the re-enables (P4-04).
        await self._audit.record(
            audit.NODE_ENABLE if enabled else audit.NODE_DISABLE,
            user_id=actor_id,
            node_id=node.id,
            metadata={"terminate_sessions": terminate_sessions},
        )
        return node

    async def revoke_credential(self, node_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        """Revoke all active credentials and drop the live connection immediately
        (stronger than disable: the node must re-enroll to reconnect)."""
        node = await self._require(node_id)
        await self._credentials.revoke_all(node.id, now_utc())
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
        """Soft delete: retain the record + audit, revoke credentials, sever the
        live socket, and hide it from default queries."""
        node = await self._require(node_id)
        node.deleted_at = now_utc()
        await self._credentials.revoke_all(node.id, now_utc())
        await self._sever_connection(node.id)
        # One operation, one row (ADR 0016). Removal implies credential revocation,
        # so the revocation is stated in metadata rather than written as a second
        # row — otherwise a filter on `credential.revoke` returns revocations that
        # were never a standalone administrative act.
        await self._audit.record(
            audit.NODE_REMOVE,
            user_id=actor_id,
            node_id=node.id,
            metadata={"credentials_revoked": True, "soft_delete": True},
        )
