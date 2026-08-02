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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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

    # --- Execution posture, reported by the node (ADR 0023) ---
    # True when this machine's system terminal can reach root through sudo. Indexed
    # because "which nodes are privileged" is a fleet-level security question, not a
    # detail of one row. Report-only: no API path writes it, and the platform cannot
    # change a node's posture — only the machine's own systemd unit and sudoers can.
    privileged_terminal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), index=True
    )
    # True when this machine accepts image drop into a session workspace (ADR 0024).
    # Report-only for the same reason and indexed for the same reason: "which nodes
    # will accept a file from a browser" is a fleet-level security question.
    image_upload: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), index=True
    )

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

    # --- Port-forwarding prerequisites, as last reported by the daemon (P11, ADR 0022) ---
    # Reported rather than inferred: whether a node *can* forward a port depends on three
    # things Central cannot see (an ssh client, egress to the provider, the pinned host key)
    # plus one it must never override (the node owner's veto). Stored so the answer survives
    # the node going offline — "we do not know" and "it was not ready" are different states,
    # and `tunnel_reported_at` is what tells them apart.
    tunnel_veto: Mapped[bool] = mapped_column(Boolean, default=False)
    tunnel_prereq_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    tunnel_prereq_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # A list of port specs ("5173", "3000-3999"), matching the platform-side columns: the
    # narrowing layers all speak the same shape so the intersection has nothing to convert.
    tunnel_local_allowed_ports: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    tunnel_local_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tunnel_reported_at: Mapped[datetime | None] = mapped_column(
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
    # What the runtime will actually be launched with, as measured on the node — not
    # what its config asked for (ADR 0023 D3). False for every runtime that has no
    # sandbox to bypass, and for a node whose CLI does not accept the flag.
    sandbox_bypass: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

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


class NodeTunnel(Base):
    """One port-forwarding tunnel on a node (P11, FR-TUNNEL-001, ADR 0022).

    The tunnel itself lives on the node as a supervised `ssh -R` child process, and the
    traffic never passes through Central. What is durable here is the platform's view:
    who opened it, on which port, under which protection, until when, and the URL the
    provider most recently assigned.

    There is deliberately no `status` column. State is derived from `closed_at`,
    `expires_at`, `state_error_code` and whether the node is currently connected — a
    stored status would be a second answer to a question that already has one, and it
    would be the stale one (same reasoning as `Node.status`, ADR 0010).

    `url` is nullable and mutable: it arrives seconds after creation, and on the free
    tier the provider issues a new one on every reconnect (measured in PG-01), which is
    why `url_updated_at` exists — the UI has to be able to say "changed 3 minutes ago".

    The basic-auth password is never stored: only its Argon2 hash, and the plaintext
    appears in exactly one API response (the creation), following the enrollment-token
    discipline.
    """

    __tablename__ = "node_tunnels"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    port: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), default="pinggy")
    protection: Mapped[str] = mapped_column(String(16))
    basic_auth_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    basic_auth_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_ips: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rewrite_host: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url_change_count: Mapped[int] = mapped_column(Integer, default=0)
    # The stable TUNNEL_* code from the last status report, never a provider string.
    state_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The platform's own deadline. Kept apart from the provider's, because "we ended it"
    # and "they ended it" need different explanations in the UI.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    upstream_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class TunnelIntegration(Base):
    """The platform-level port-forwarding integration, as a single row (P11, FR-TUNNEL-004).

    This is the only place in the platform that holds a third-party credential, and it
    holds it encrypted: ciphertext plus a per-write nonce, with a short fingerprint of the
    plaintext kept alongside so a person can answer "is this the token I rotated last
    week" without any interface ever returning a character of it.

    `singleton` with a unique constraint is what makes "one row" a database property
    rather than a convention. Reading "the first row" would silently pick one if a second
    ever appeared.

    `concurrent_budget` is fleet-wide — the number of tunnels the provider plan allows at
    once — and is enforced as a global count, never folded into the per-node cap.
    """

    __tablename__ = "tunnel_integration"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    singleton: Mapped[bool] = mapped_column(Boolean, default=True, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(32), default="pinggy")
    plan_tier: Mapped[str] = mapped_column(String(16), default="free")
    token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    token_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    token_fingerprint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    concurrent_budget: Mapped[int] = mapped_column(Integer, default=8)
    default_protection: Mapped[str] = mapped_column(String(16), default="basic")
    default_ttl_seconds: Mapped[int] = mapped_column(Integer, default=4 * 3600)
    # A list of port specs ("5173", "3000-3999"), not a mapping: an empty list means "forbid
    # everything" and NULL means "do not narrow", and those are different settings.
    allowed_ports: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # The administrator's one-time acknowledgement that traffic leaves for a third party.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class NodeTunnelSettings(Base):
    """Per-node port-forwarding settings, decided in the platform (P11, FR-TUNNEL-004.AC-05).

    The middle of three layers: the integration decides whether the capability exists at
    all, this decides whether a given machine takes part and within which bounds, and the
    node's own config file holds an absolute veto the platform cannot override. Effective
    policy is the intersection; every layer may only narrow.

    `enabled` defaults to true because the platform-level switch is the real gate — a node
    that has been enrolled already grants the platform a shell runtime (ADR 0021), so
    requiring a second opt-in per machine would be form rather than substance. Turning a
    single machine off is a one-click platform action; vetoing it outright stays with its
    owner.

    NULL for `allowed_ports`/`max_tunnels` means "do not narrow further", which is a
    different statement from an empty list (forbid everything).
    """

    __tablename__ = "node_tunnel_settings"

    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_ports: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    max_tunnels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


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
