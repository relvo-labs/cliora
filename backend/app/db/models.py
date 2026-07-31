"""SQLAlchemy 2 models for the Phase 1 control plane.

All timestamps are timezone-aware (`TIMESTAMP WITH TIME ZONE`); the application
layer always holds aware UTC and rejects naive datetimes before they reach here
(see ADR 0009 / timezone-precision skill). Terminal bytes and secret plaintext
are never stored — only hashes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(128))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on logout / credential reset to invalidate outstanding refresh
    # tokens without a global blacklist (ADR 0007).
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    role: Mapped[Role] = relationship(lazy="joined")


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), index=True)
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    # Last known status label; the authoritative value is recomputed by the
    # connection registry from the monotonic heartbeat gap (ADR 0010).
    status: Mapped[str] = mapped_column(String(16), default="offline", index=True)
    os: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    architecture: Mapped[str | None] = mapped_column(String(16), nullable=True)
    daemon_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Soft delete: retained for audit, hidden from default queries, id never
    # reused (confirmed product decision — see ADR 0011).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Daemon update state (P4-10, ADR 0017) ---
    # Explicit columns rather than keys inside `metadata`: "which nodes failed to
    # update" has to be an indexable query, because it is the question an operator
    # asks after a fleet upgrade and the one the Dashboard sorts on.
    update_status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    update_target_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The stable `UPDATE_*` code from the last attempt, or "succeeded". Never a
    # daemon error string — those stay in the log (ADR 0017).
    update_last_result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    runtimes: Mapped[list[NodeRuntime]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )
    workspace_roots: Mapped[list[NodeWorkspaceRoot]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )


class NodeRuntime(Base):
    __tablename__ = "node_runtimes"
    __table_args__ = (UniqueConstraint("node_id", "runtime"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    runtime: Mapped[str] = mapped_column(String(16))
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    binary_path: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    node: Mapped[Node] = relationship(back_populates="runtimes")


class NodeWorkspaceRoot(Base):
    __tablename__ = "node_workspace_roots"
    __table_args__ = (UniqueConstraint("node_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(4096))
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    node: Mapped[Node] = relationship(back_populates="workspace_roots")


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Only the keyed hash is stored; plaintext is shown once at creation
    # (ADR 0008 / SEC-003).
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NodeCredential(Base):
    __tablename__ = "node_credentials"
    __table_args__ = (UniqueConstraint("node_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    public_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    algorithm: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TerminalSession(Base):
    """Durable session metadata (PRD §12.6, ADR 0013).

    Terminal bytes are never stored here — only lifecycle metadata. ``status``
    holds the state-machine value (starting/running/disconnected/exited/failed/
    terminating/terminated); the authoritative transitions live in the session
    service. ``exit_code`` may be the runtime's real status (via tmux
    ``#{pane_dead_status}``) or an attach-client approximation (ADR 0012).
    """

    __tablename__ = "terminal_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    runtime: Mapped[str] = mapped_column(String(16))
    workspace: Mapped[str] = mapped_column(String(4096))
    status: Mapped[str] = mapped_column(String(16), default="starting", index=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows: Mapped[int] = mapped_column(Integer, default=24)
    columns: Mapped[int] = mapped_column(Integer, default=80)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set only on a system-terminal session: the CLI session it belongs to
    # (FR-SHELL-001.AC-04). NULL for every CLI session, so nothing was backfilled.
    # A partial unique index (migration 0013) enforces one *live* shell per parent.
    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("terminal_sessions.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionConnection(Base):
    """One browser attachment to a session (writer or viewer), for audit and
    writer/viewer tracking (ADR 0013). No terminal bytes are stored."""

    __tablename__ = "session_connections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("terminal_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))  # writer | viewer
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkspaceFavorite(Base):
    """A user's saved workspace path on one node (P4-13, FR-WORKSPACE-005).

    **A shortcut, never an authorization.** Creating a session from a favorite runs the
    identical path as typing it: Central's prefix check against the node's enabled roots,
    then the daemon's canonical `os.Root` resolution. A stored path is never treated as
    "already validated" — roots get removed, directories get deleted, and a favorite that
    was legal when saved may not be now (SEC-001).

    Per-user, so one user's favorites can never disclose their workspace layout to
    another. Bound to a node because an absolute path only means something there.
    """

    __tablename__ = "workspace_favorites"
    # Idempotent: favouriting the same path twice returns the existing row rather than
    # creating a duplicate the user would then have to delete twice.
    __table_args__ = (UniqueConstraint("user_id", "node_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(4096))
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NodeMetricSample(Base):
    """One persisted heartbeat resource sample (P4-06, ADR 0018).

    The live sample lives in the connection registry, in this process's memory.
    That answers "how is this node right now" and nothing else: a Central restart
    empties it, so without this table the Dashboard cannot say whether a node was
    healthy an hour ago and a runbook has nothing to look back at.

    Written at a reduced rate (`node_metric_sample_interval_seconds`, default 60 s
    per node) rather than on every heartbeat, and bounded by
    `node_metric_retention_days`. Every measurement is nullable because the daemon
    collects each field best-effort (`internal/systeminfo`) — a missing value must
    be recorded as unknown, never as zero.
    """

    __tablename__ = "node_metric_samples"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cpu_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    daemon_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    audit_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
