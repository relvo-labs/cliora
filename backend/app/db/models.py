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
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
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
    # True when this machine accepts general file upload — an arbitrary file, under a
    # name the user chose, into a directory the user chose (ADR 0026). A separate
    # column from `image_upload` rather than a widening of it: the two grants are
    # different sizes, and a node owner is entitled to answer them differently.
    file_upload: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), index=True
    )
    # True when this machine's agentd is new enough to receive a task context pack
    # (0.8.0+, ADR 0028 sec 5). A capability the daemon *reports*, exactly like the two
    # above — never something the platform sets. An older node keeps working: sessions
    # start and run as before, Central simply does not send `context.project`, and the
    # console says which version would be needed rather than answering 500 or dropping
    # the node from a list.
    context_projection: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), index=True
    )
    # True when this machine's agentd can run agent work unattended (0.9.0+, ADR 0029
    # sec 7). The fourth instance of the same shape, and reported for the same reason:
    # a 0.8.0 node keeps serving interactive sessions and is simply never offered a
    # run, so the console can say "needs 0.9.0" instead of failing.
    agent_runner: Mapped[bool] = mapped_column(
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
    # Nullable, and permanently so (ADR 0027): a session belonging to no project is
    # an *ad-hoc* session, which is part of the product rather than a transitional
    # state. The platform never infers this from the workspace — one path may be
    # bound to several projects, so there is no unique answer, and "is this ad-hoc"
    # has to stay the caller's statement rather than ours. `task_id` joins it in
    # V2.1's 0023, when `tasks` exists and it can be a real foreign key.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    # Nullable, and permanently so, for the same reason as ``project_id``: a session
    # that belongs to no card is part of the product, and the platform never infers
    # one from the workspace. ``SET NULL`` rather than cascade — an archived or
    # mistakenly removed card must not erase the record that a session really ran.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
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


class Project(Base):
    """A project: a name for work that spans workspaces on several nodes (ADR 0027).

    Platform data, not files in the user's repository. That is the whole of decision
    D1/D2 in one sentence — the repo holds code, the platform holds everything about
    the work.

    ``slug`` is fixed at creation while ``name`` is not, and the split is
    load-bearing: V2.1 builds card references (``TASK-123``) on the slug and V2.3
    namespaces secrets by it, so a mutable slug would strand both. Renaming is a
    display concern and stays free.

    There is no delete, only ``archived``. ``activity_events`` is history and
    ``terminal_sessions.project_id`` points here, so deleting would either orphan
    rows or erase something that really happened. Archiving refuses new sessions and
    new bindings; everything already running is untouched.
    """

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("slug"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # The card-reference counter (V2.1). Allocated with one `UPDATE … RETURNING`,
    # which takes the row lock — `count(*) + 1` collides between two browser tabs,
    # and `card_ref` goes on to name a branch and a pull request. Epics, stories and
    # tasks share it, so numbers skip: it is an identifier, not a count.
    next_card_seq: Mapped[int] = mapped_column(Integer, default=1)
    # Which secret **names** this project's cards may declare (V2.3, ADR 0032 sec 0).
    # Intent, not inventory: it is deliberately not derived from the rows that happen
    # to exist in `project_secrets`, because deriving it would make deleting one secret
    # silently un-dispatchable a batch of cards with nothing on screen relating the two.
    allowed_secret_names: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # The project half of "what verifies a card" (V2.4, ADR 0033 sec 3b). A list of
    # ``{"name": str, "argv": [str, ...]}``. **argv, never a shell string** — a shell
    # string is an injection path and it would sit on the platform's own storage
    # surface. The card half lives on ``Task.verification_commands`` and is written
    # through a different action; ``origin`` on a check records which store named it.
    verification_commands: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Enable/disable of existing process items only — never new items, never new lanes
    # (ADR 0033 sec 5). A JSONB column rather than a table on purpose: "which of the
    # seven readiness items are off" is a set of booleans, and a table would invite
    # somebody to put a custom item in it, which is what makes cross-project metrics
    # aggregatable in the first place.
    process_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # The convergence point for card-declared checks, **off by default**. On, the Done
    # Gate additionally requires that at least one ``origin: project`` check ran. Off by
    # default because a switch that blocks people on day one teaches them to stop using
    # the feature it guards.
    require_project_verification: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # --- project memory (V2-K1, ADR 0038 sec 7) -----------------------------
    # **Off by default, and per project rather than per deployment** (D52/D58). A
    # 500-file project and a 50,000-file monorepo need different answers about what is
    # worth indexing, and a deployment flag cannot give two. Turning it on takes
    # ``project.manage`` and writes an audit row; turning it off marks existing sources
    # inactive and deletes nothing, because deletion is a separate action with a second
    # confirmation.
    #
    # It is also the backfill trigger: the reconciler's watermark queries find every
    # entity that has no source yet, so there is no backfill script anywhere. One
    # filling routine is more correct than two that have to agree forever.
    knowledge_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Exclude globs and repository sync bounds. JSONB rather than a table for the reason
    # ``process_overrides`` above gives: read and written with the project, no query of
    # its own. It carries **no retention override** — ADR 0038 sec 6 decided knowledge
    # keeps no clock of its own, and a setting with no sweep behind it is worse than an
    # absent one because somebody will read it and believe it.
    knowledge_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectWorkspace(Base):
    """One workspace path on one node, bound to a project.

    **A binding, never an authorization** — the same sentence, and the same rule, as
    `WorkspaceFavorite`. `sessions.authorize_workspace()` runs when the binding is
    created *and again on every use*, because roots get disabled and directories get
    deleted: a path that was legal when bound may not be now (SEC-001). Two
    implementations of one prefix rule would eventually disagree, and the day they
    disagree is a security event rather than a bug.

    Node removal is a soft delete (ADR 0011), so the `ON DELETE CASCADE` in the
    migration is a safety net rather than the normal path; the service filters
    soft-deleted nodes out of its listing instead.

    Unique on `(project_id, node_id, path)`, which makes binding idempotent: a second
    request for the same triple returns the existing row rather than a duplicate the
    user would then have to unbind twice. At most one row per project may be
    `is_primary`, enforced by a partial unique index rather than by application code,
    because concurrency defeats the application-code version.
    """

    __tablename__ = "project_workspaces"
    __table_args__ = (UniqueConstraint("project_id", "node_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(4096))
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActivityEvent(Base):
    """What happened on a project (FR-PROJECT-004, ADR 0027 sec 7).

    **Not a second audit log.** The two answer different questions and are cleaned up
    differently, which is the distinction most easily lost:

    ==================  ==============================  ==========================
    .                   ``audit_logs``                  ``activity_events``
    ==================  ==============================  ==========================
    question            who did what, fleet-wide        what happened on *this*
                                                        project
    who may read it     metadata needs ``audit.view``   ``project.view`` — which
                                                        **all three roles hold**
    who cleans it up    existing retention              nobody; it lives as long
                                                        as the project
    ==================  ==============================  ==========================

    Two consequences follow from the wider audience, and both are enforced rather
    than documented: the audit module's forbidden-key list also guards this payload
    (a constraint on a wider surface can only be tighter), and **actor identity is
    redacted for callers without** ``audit.view`` — the same rule
    ``services/dashboard.py::project_for`` already applies to the dashboard's recent
    activity. Without that, this table would quietly reopen a channel P4 closed.

    ``task_id``, ``session_id`` and ``actor_user_id`` carry no foreign key, matching
    ``audit_logs``. ``task_id`` points at a table V2.1 creates; the other two are
    deliberate, because a timeline is history and a hard-deleted session must not
    blank out the row saying it once ran.
    """

    __tablename__ = "activity_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # ``user`` / ``agent`` / ``system`` (V2.1). Without it a NULL ``actor_user_id``
    # would mean three different things at once — a system event, an agent's write,
    # and a user event whose actor :func:`services.activity.redact_actors` stripped
    # for a reader without ``audit.view`` — and a timeline that cannot tell them
    # apart says none of them. ``redact_actors`` deliberately leaves this field
    # alone: "an agent did this" is the nature of the event, not an actor's identity.
    actor_kind: Mapped[str] = mapped_column(String(16), default="user")
    kind: Mapped[str] = mapped_column(String(64))
    activity_payload: Mapped[dict[str, Any]] = mapped_column("payload", JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProcessDefinition(Base):
    """The internalised process: lanes, readiness items, review gates, templates.

    Monstrare's process (MIT) as platform data rather than files in the user's
    repository — ADR 0027's central move, and ADR 0028 sec 1 is where it stops being
    prose and starts refusing requests.

    One global row in V2.1 (``key = 'default'``), not overridable per project: V2.4
    adds the minimal override, and configurability with no users is the easiest thing
    in this system to over-build (research/02/01 D15).

    ``version`` is a **content** version, not a serial. It becomes the directory name
    under ``.cliora/process/<version>/``, so it has to change when the content
    changes and stay put when it does not — otherwise a second session in the same
    workspace either re-projects unnecessarily or projects into a stale directory.

    Every entry in ``gates`` carries ``requires_human``. It is a constant today, and
    writing it as data anyway is the point: "an agent's output is not an approval"
    needs somewhere it can be pointed at.
    """

    __tablename__ = "process_definitions"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), default="monstrare")
    lanes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    readiness: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    gates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    templates: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Epic(Base):
    """A named body of work inside a project (FR-TASK-001).

    An entity rather than a string on a card: before internalisation an epic was a
    value in someone's JSON file and the platform could only group by it (D4). With a
    row, a story points at it with a foreign key, the roadmap is a join, and renaming
    it does not strand anything.
    """

    __tablename__ = "epics"
    __table_args__ = (UniqueConstraint("project_id", "card_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    card_ref: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserStory(Base):
    """A user story, optionally under an epic (FR-TASK-001).

    ``epic_id`` is nullable and its foreign key is ``SET NULL``: a story that has not
    been filed under an epic yet is a legitimate state, and an epic that goes away
    drops its stories into the unclassified bucket rather than taking them with it.
    A card must never vanish because of how it was filed — that bucket is Monstrare's
    semantics, kept deliberately (D4).
    """

    __tablename__ = "user_stories"
    __table_args__ = (UniqueConstraint("project_id", "card_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    epic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("epics.id", ondelete="SET NULL"), nullable=True
    )
    card_ref: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Requirement(Base):
    """One vague sentence, before it is a specification (FR-TASK-005).

    ``raw_text`` is the whole intake surface on purpose: the flow starts with someone
    saying what they want in their own words, and a form with ten required fields at
    that moment is how the flow stops being used. V2.5 lets an agent interrogate it
    into a spec through the same API; V2.1 is a human doing it, and whether anyone
    does is the early signal for whether V2.5 is worth building (D28 sec 4).
    """

    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("project_id", "card_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    card_ref: Mapped[str] = mapped_column(String(32))
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="intake")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FeatureSpec(Base):
    """One version of a requirement's specification. Append-only (FR-TASK-005).

    Rows are inserted, never updated — the same shape ADR 0027 chose for execution
    plans and for the same reason: "version N versus N-1" is what the review screen
    is for, and a specification that was quietly edited is exactly what someone will
    need to see later.

    ``open_questions`` is a column rather than a table because it is read and written
    with its version and has no independent query. It also carries a rule: while one
    is unresolved the requirement cannot be approved, and that refusal is in the API
    (FR-TASK-005.AC-03), not in a disabled button.
    """

    __tablename__ = "feature_specs"
    __table_args__ = (UniqueConstraint("requirement_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    non_goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    open_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # The nine sections Monstrare's specification template has and the five columns
    # above do not (ADR 0034 §7, MIT). One JSONB rather than nine columns by ADR 0027's
    # rule — read and written with the row, no independent query — and the same rule
    # that decided ``TaskProposal.tree``.
    #
    # Three of the nine are load-bearing rather than decorative: ``user_stories`` is
    # what a decomposition run reads to produce the Epic→Story→Task middle layer,
    # ``screens`` is the upstream of the ``ui`` gate, and ``verification_plan`` is where
    # a card's acceptance criteria come from. The **keys** are validated
    # (``services/requirements.py::SPEC_SECTION_KEYS``); the contents are not, because a
    # specification with empty sections is legal and the approval gate is what stops it.
    sections: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    authored_by_kind: Mapped[str] = mapped_column(String(16), default="user")
    authored_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # ``SET NULL`` rather than ``CASCADE``, the same choice ``TaskMessage.run_id`` made:
    # a run's record is reclaimed on a retention schedule and a specification is not.
    #
    # ``use_alter`` because this key **closes a loop** in the foreign-key graph
    # (``feature_specs`` → ``task_runs`` → ``tasks`` → ``task_proposals`` →
    # ``feature_specs``). Without it SQLAlchemy cannot order the four for ``create_all``
    # and warns that it may become an error; with it, the loop-closing edge is named and
    # emitted separately. Naming it is also the documentation: this is the edge that made
    # the graph cyclic.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "task_runs.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_feature_specs_run_id",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskProposal(Base):
    """A proposed epic/story/task tree, before a human accepts it (FR-TASK-005).

    Proposals are not cards. Accepting one is what creates rows in ``tasks``, which is
    "an agent's output is not an approval" applied to decomposition — and it is also
    where the Definition of Ready gets somewhere to bite: a proposed card missing its
    readiness items is accepted into ``backlog`` rather than into ``ready`` (D28).
    """

    __tablename__ = "task_proposals"
    __table_args__ = (UniqueConstraint("requirement_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE")
    )
    spec_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feature_specs.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    tree: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    # The other loop-closing edge: ``task_proposals`` → ``task_runs`` → ``tasks`` →
    # ``task_proposals``. Same reasoning as ``FeatureSpec.run_id``.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "task_runs.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_task_proposals_run_id",
        ),
        nullable=True,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    """A task card (FR-TASK-001…004, ADR 0028).

    Three columns carry decisions that are easy to undo by accident:

    * ``version`` is an optimistic lock. A plain integer is enough **because the
      platform is the only writer** — the design this replaced kept cards in the
      repository and needed a content hash for the same job (research/02/01 D6).
    * ``gates`` holds ``{gate_key: {approved_by, approved_at}}``, never a boolean.
      That cell always names a human, which is what makes "an agent's output is not
      an approval" a property of the data rather than a rule in a document.
    * ``card_ref`` comes from ``projects.next_card_seq`` and is **immutable**. It goes
      on to name a branch in V2.3 and a pull request in V2.4, so a value that could
      change — or that could collide — surfaces three phases after the mistake.

    ``acceptance_criteria``, ``readiness`` and ``links`` are JSONB by ADR 0027's rule:
    read and written with the card, no independent query, so a table would make
    "edit one acceptance criterion" a multi-row upsert with orphans to clean.

    The execution settings (``source``, ``delivery``, ``repository_id``,
    ``base_branch``, ``target_branch``, ``existing_pr_ref``, ``required_secrets``)
    are **declared but inert** in V2.1: nothing reads them until V2.3/V2.4. They exist
    now because people state the intent now, and because adding them later would
    leave every existing card without them (ADR 0028 sec 9).
    """

    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "card_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    epic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("epics.id", ondelete="SET NULL"), nullable=True
    )
    user_story_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_stories.id", ondelete="SET NULL"), nullable=True
    )
    card_ref: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    non_goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What this card *is*, as against what it is tagged with (ADR 0034 §5). Four values
    # and a default, so every card written before V2.5 has an explicit kind.
    #
    # **It takes no part in dispatch matching** — that is what `required_labels` is for
    # — and it is deliberately not derived from one. A tag is free text that decides
    # which machine claims the card; overloading it with "what kind of card is this"
    # means a typo silently turns a clarification card into an ordinary one, and the
    # secret refusal that reads this column exists precisely to catch that case.
    #
    # It is in ``AGENT_FORBIDDEN_FIELDS`` and locked once any run has existed: a
    # clarification run that could rewrite its own card to ``implementation`` would have
    # cleared the way for the next dispatch to carry secrets.
    card_kind: Mapped[str] = mapped_column(
        String(16), default="implementation", server_default=text("'implementation'")
    )
    stage: Mapped[str] = mapped_column(String(16), default="backlog")
    risk: Mapped[str] = mapped_column(String(16), default="medium")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # No foreign key: `agent_runners` lands in V2.2, `project_repositories` in V2.3.
    # `activity_events.task_id` set this precedent in 0021.
    assigned_runner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    required_labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    readiness: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    gates: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    acceptance_criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    links: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(16), default="repo")
    repository_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery: Mapped[str] = mapped_column(String(16), default="pull_request")
    target_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    existing_pr_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required_secrets: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # This card's own verification checks (V2.4, ADR 0033 sec 3b), same shape as the
    # project's. **Deliberately absent from ``EDITABLE_FIELDS``**: it is written through
    # its own endpoint requiring ``task.approve``, which ``RUN_TOKEN_SCOPES`` never
    # contains. Reachable through ``PATCH`` it would let the agent being verified choose
    # what verifies it — every exit code would stay real and every one would be
    # worthless.
    verification_commands: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # The Done Gate's escape hatch, recorded **on the card** and not only on the
    # timeline (ADR 0033 sec 5). A timeline entry scrolls away; "this card was forced"
    # has to be visible whenever the card is. Cleared only by taking the card out of
    # ``done`` and through the gate — there is no endpoint that clears these three
    # alone, because a record that can be erased on its own is not a record.
    force_done_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_done_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    force_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_proposals.id", ondelete="SET NULL"), nullable=True
    )
    # --- conversation (V2-C1, ADR 0035) -------------------------------------
    # The card's message counter. Every message takes its number from here in the same
    # transaction that inserts it, which locks *this* row — a row the write was going to
    # touch anyway, because ``updated_at`` has ``onupdate``. A sequence would be holed
    # per card and ``max(seq)+1`` would duplicate under concurrency (ADR 0035 §2).
    #
    # It is also what lets the board projection answer "how far has this conversation
    # got" without joining ``task_messages`` — a join that costs real time at 200 cards.
    conversation_seq: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Two projections of ``task_questions``, maintained in exactly one function
    # (``ConversationService._reproject``) and asserted by
    # ``GATE-CV-PROJECTION-ONE-WRITER``. A second writer's first missed branch shows a
    # card that says "waiting for your reply" after the reply arrived, and **nothing
    # errors** — which is why the guard is a gate rather than a test.
    open_question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # ``human`` | ``agent`` | NULL. Derived from question state, so it gives the same
    # answer whether the asking run is still polling or has already ended (ADR 0035 §8).
    waiting_for_actor: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # --- work views and ordering (V2-P1, ADR 0042) ---------------------------
    # A lexicographically ordered string, **scoped to the project rather than to the
    # lane** (ADR 0042 §5): a card crossing a lane keeps its rank, so the move is one
    # write instead of a renumbering. An integer column cannot do this — there is no
    # integer between adjacent integers, so every insert renumbers the tail.
    #
    # **`NOT NULL` in the database, with a default here.** The migration makes the
    # column mandatory because `ORDER BY rank` has to be total — a NULL would sort into
    # a bucket whose position depends on the query. But a mandatory column with no
    # default breaks every direct `Task(...)` insert, including the seed scripts and
    # most test fixtures, so the ORM supplies `INITIAL_RANK`. `TaskService.create_task`
    # overrides it with a real neighbour-derived value; anything that does not go
    # through the service lands on the shared default and is ordered by the secondary
    # key, which is the behaviour those callers had before this column existed.
    # The literal is `ranking.INITIAL_RANK`. Written out rather than imported: this
    # module is the bottom of the dependency graph and importing a service from it would
    # invert that. `test_the_model_default_is_the_ranking_modules_initial_rank` keeps
    # the two equal.
    rank: Mapped[str] = mapped_column(
        String(64), nullable=False, default="a", server_default=text("'a'")
    )
    # The blocked face of ADR 0040 §1, and it is **not the whole truth about being
    # blocked** until `beta.2`'s `HD-06`: `stage='blocked'` always projects onto
    # blocked regardless of this column, because the platform's three legacy writers
    # (`run_reaper.py` twice, `runs.py` once) still set the stage and not this.
    # Anyone reading this column directly is wrong about the cards the reaper touched;
    # `services/work/projection.py::project_is_blocked` is the reader.
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # No CHECK constraint, unlike every other enumeration here. Two of its values can
    # only come from the runtime phase of `derive_attention`, which no ordinary write
    # path can reach; a CHECK would turn "what we derived at the time" into "an
    # authoritative classification". The value set is a frozenset in
    # `services/work/projection.py` with a test.
    blocking_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    blocking_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkView(Base):
    """A saved question about a project's cards (V2-P1, FR-WORK-008, ADR 0042).

    Three properties are decisions rather than columns:

    * **`filter_json` is JSONB and not a child table.** The filter is a value object,
      read and written whole, and no query ever asks "which views use
      `priority=urgent`". A child table turns one read into a join and needs a schema
      change for every new filter dimension (the same argument ADR 0033 §5 makes about
      `process_overrides`).
    * **`scope` is two words and neither grants anything.** A shared view whose filter
      matches cards the caller cannot see returns those cards *missing* — not an error,
      and not the cards. `visible_fields_json` shapes the response and takes no part in
      authorization, which has a test because a field list is the most natural place for
      somebody to eventually put a permission.
    * **Deletion is asymmetric.** `deleted_at` is only ever set on a `project` view,
      because other people hold links to it and a hard delete turns a colleague's
      bookmark into an unexplained 404. A `personal` view is deleted outright: nobody
      else has a link, and a graveyard of one person's abandoned views only grows.

    `layout` admits `roadmap` although only `board` and `list` are implemented, for the
    reason `BoardDTO.has_more` exists: a value added later forces every existing client
    to handle its absence, while one present from the start is merely unwritten.
    """

    __tablename__ = "work_views"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # NULL means a personal view spanning every project its owner can see — the
    # cross-project My Work page is the only thing that writes one.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    # NULL means the view belongs to the project rather than to a person.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(64))
    layout: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(16))
    filter_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    group_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subgroup_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_by_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    visible_fields_json: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    density: Mapped[str] = mapped_column(
        String(16), default="comfortable", server_default=text("'comfortable'")
    )
    show_subtasks: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskDependency(Base):
    """ "This card cannot start until that one is done" (FR-TASK-003).

    A table rather than a JSONB list because it is the one relation with a query of
    its own: the cycle check walks it, and the board asks "is anything still blocking
    this" for every card in a lane.

    Self-dependency is refused by a database constraint; longer cycles are refused by
    a graph walk in the service, so that the error can name the path it found.
    """

    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionToken(Base):
    """The credential an agent inside a session may hold (FR-TASK-008, ADR 0028 sec 3).

    **Only the HMAC is stored**, keyed by the existing token pepper (ADR 0008). There
    is no path that returns a plaintext token, because none is kept — the value exists
    for exactly as long as it takes to project it into the workspace.

    ``scopes`` is snapshotted at issue time rather than read live: a credential is a
    fixed grant, and consulting a constant per request would mean editing that
    constant silently re-authorises every token already issued.

    Revocation is written into the session state machine rather than into the four
    routes that can end a session — the same reasoning
    ``SessionService._record_ended`` documents, and for the same reason: a fifth door
    will be added one day.
    """

    __tablename__ = "session_tokens"
    __table_args__ = (UniqueConstraint("token_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("terminal_sessions.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    issued_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRunner(Base):
    """A node's ability to run agent work, as one row (FR-AGENT-001, ADR 0029 sec 1).

    **One row per node**, and ``runtimes`` is a set rather than a row per runtime. The
    upstream plan modelled it the other way; on a single WebSocket that immediately
    raises "which row is online", and the answer is always the node's own status — so
    the column would be a fake indicator light.

    For the same reason there is no ``status`` and no ``last_seen_at``: a runner is
    online exactly when its node is, and the API computes that from
    ``NodeConnectionRegistry.is_connected`` on the same path the Nodes page uses.

    ``dedicated`` is a **posture report**, in the sense ADR 0023 established for the
    codex sandbox flag: the daemon sets it from ``len(workspace.allowed_roots) == 0``
    and the platform displays it. The platform has no technical isolation between a
    run and the node's allowed roots (ADR 0031 sec 6); on a node with none, "the run
    cannot read one" is vacuously true. Nothing refuses to register because of it —
    one person's dev VM serving both purposes is the common case, and it should be a
    visible choice rather than an unnoticed fact.

    ``labels`` were displayed and never compared in V2.2. **From V2.3 they are the
    fourth eligibility condition** (ADR 0029 amendment B2), matched as a superset:
    ``required_labels ⊆ labels``. They remain **read-only through the API** — a tag is
    what the node's own config declares, so a platform-side edit would be a second
    source of truth that ``runner.register`` overwrites on the next reconnect.

    **A tag is not authorization.** It is a string the runner reports about itself, so
    a compromised runner changes what it is offered by reporting one more. The
    authorization boundary is enrollment, permanently (ADR 0032 sec 0).
    """

    __tablename__ = "agent_runners"
    __table_args__ = (UniqueConstraint("node_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    runtimes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    max_concurrent: Mapped[int] = mapped_column(Integer, default=1)
    max_waiting: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    dedicated: Mapped[bool] = mapped_column(Boolean, default=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_registered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Why this runner stopped polling, reported on the heartbeat. **Not** an online
    # indicator: a runner at capacity and a runner whose machine is gone are both
    # silent, and the console needs to tell them apart (migration 0032). Null means
    # "no report", which is why these are nullable rather than defaulted.
    blocked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    disk_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Two node-side declarations, both defaulting to the permissive value — because a
    # default has to equal the behaviour before the upgrade, and a payload that omits
    # them is read as true (ADR 0029 amendment B3). `run_untagged` off reserves a
    # machine for tagged work; `accept_secrets` off keeps it away from cards that
    # declare secrets, which is the node operator's veto (ADR 0032 sec 0).
    run_untagged: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    accept_secrets: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # V2.4. **The empty list is the default**, and the opposite polarity from the two
    # above is the same rule underneath: an absent declaration means the behaviour
    # before the upgrade, and for a capability that is "cannot". Central puts
    # feature-gated content into an offer only for a node that named the feature
    # (ADR 0029 amendment C). Read-only from the platform's side, like `labels`.
    features: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectRepository(Base):
    """Where a project's code lives, as platform configuration (FR-AGENT-012).

    The URL is **three columns, not one string**, and that is a security property
    rather than tidiness: ``runner.git.allowed_hosts`` compares ``host`` exactly, and
    extracting a host from a free-form URL is how ``https://github.com@evil.example/``
    gets through. Split this way, userinfo is not representable at all — which is the
    schema form of ADR 0031's rule that a credential must never appear in a remote
    URL, where it would surface in ``git remote -v``, the reflog and error messages.

    The three credential columns arrived in V2.3 (migration 0033), once
    ``project_secrets`` existed for them to point at. ``auth_kind`` has **three**
    values rather than the two the design named: ``ambient`` is what every repository
    registered under V2.2 is actually using — the node's own git credentials — and
    after the 2026-08-13 ruling it is the default going forward as well, because
    platform-managed git credentials are gated behind
    ``CLIORA_GIT_SECRET_DELIVERY_ENABLED`` and that flag is off by default. Back-filling
    those rows as ``pat`` with a null credential would have written down a row that is
    not true.
    """

    __tablename__ = "project_repositories"
    __table_args__ = (UniqueConstraint("project_id", "host", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    scheme: Mapped[str] = mapped_column(String(8))
    host: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(512))
    default_branch: Mapped[str] = mapped_column(String(255))
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auth_kind: Mapped[str] = mapped_column(String(16), default="ambient", server_default="ambient")
    credential_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_secrets.id", ondelete="RESTRICT"), nullable=True
    )
    provider_token_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_secrets.id", ondelete="RESTRICT"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectSecret(Base):
    """A value the platform holds for a project and hands to a runner on demand.

    FR-RUNENV-001/002, ADR 0032. **Nothing about this row is readable back.** No API
    returns the value, the DTO has no field for it, and the service's queries name the
    columns they want so that a future ``dict(row.__dict__)`` cannot reach the
    ciphertext by accident.

    **Four ciphertext columns, because the envelope has two layers.** The value is
    encrypted under a per-row data key; the data key is encrypted under the master key.
    Each AES-GCM operation needs its own nonce, stored beside its ciphertext. Rotating
    the master key rewrites ``dek_wrapped`` and leaves ``value_encrypted`` byte-for-byte
    identical — which is what makes rotation something other than a full-table
    re-encryption, and what keeps the upgrade path to a KMS down to one function.

    **No fingerprint and no length.** A fingerprint answers "is this the one I rotated
    last week" and ``rotated_at`` answers that without disclosing anything; a length is
    a side channel, because a 93-character value is almost certainly a fine-grained PAT.

    ``kind`` decides where the value goes on the node (ADR 0032 sec 4): ``env`` reaches
    the CLI child's environment, ``git_pat``/``git_ssh_key`` reach **only the daemon's
    own git environment** and are gated off by default, and ``provider_token`` is not
    delivered at all in this phase.
    """

    __tablename__ = "project_secrets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    value_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # SET NULL, not CASCADE: somebody leaving must not delete a project's credentials.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stamped at the **claim**, not at the end of the run: a run may never end, and by
    # then "this machine was handed this secret" is already a fact.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft delete, with a partial unique index behind it, so that deleting a secret and
    # creating a new one under the same name — the commonest recovery there is — works.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskRun(Base):
    """One attempt at running a card unattended (FR-AGENT-003…005, ADR 0029).

    Three properties are easy to undo by accident:

    * ``assigned_runner_id`` is a **snapshot** of the card's assignment, not a live
      read of ``tasks.assigned_runner_id``. A re-queue must keep the original
      assignment while the card stays editable mid-run; editing the card affects the
      *next* dispatch. ``repository_id``, ``source_kind`` and ``source_ref`` are
      snapshots for the same reason — a run executes the card as it was at dispatch.
    * ``last_event_at`` is **not the lease**. The lease answers "is the runner alive"
      and Central judges it; this answers "is the child making progress" and the
      daemon judges it, because the daemon is where the event stream is. This column
      exists so the Run detail page can say "last activity: 3 minutes ago".
    * ``lost`` is terminal. A re-queue inserts a **new row** (``seq + 1``,
      ``attempt + 1``) rather than moving this one back to ``queued``, so the Run
      detail page can show where the second attempt failed. The upstream state diagram
      drew it the other way (ADR 0029 sec 4).

    There is no ``workspace_node_id`` and no ``workspace_path``, and that absence is
    load-bearing: while such a column exists, somebody joins it to
    ``project_workspaces``, and that join is the first step towards the run directory
    and the user's allowed roots sharing one authorization model.
    """

    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("task_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    assigned_runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_repositories.id", ondelete="SET NULL"), nullable=True
    )
    source_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(CHAR(40), nullable=True)
    disk_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    runtime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # How the result left, in three columns rather than one overloaded string (V2.4).
    #
    # ``delivery_state`` is the pull-request worker's queue: ``finish()`` sets
    # ``pending_pr`` and nothing else, because it runs on the node receive loop and that
    # loop also carries interactive terminal bytes — a 20-second HTTP call there stops
    # somebody's terminal for 20 seconds (ADR 0033 sec 3). No CHECK constraint: unlike
    # ``verification_reports.result`` this is an internal state machine rather than part
    # of a contract, and ``result`` above already set that precedent.
    #
    # ``pushed_branch`` is **the daemon's report, not Central's derivation**. Central
    # composes the name and could compute it; only the node knows whether the push
    # succeeded, and a pull request may only be opened on a branch that exists.
    delivery_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    pushed_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    log_truncated_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    logs_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- continuation turns (V2-C1, ADR 0035 §4) ----------------------------
    # A continuation is a *child run*, not a row in a second table. ``task_runs``
    # already owns the state machine, the lease, the retry counter, the log, the
    # cancellation path and the audit trail; a parallel table would mean keeping two
    # lifecycles in step for something the interface collapses into one thread anyway.
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "task_runs.id", ondelete="SET NULL", name="fk_task_runs_parent_run_id", use_alter=True
        ),
        nullable=True,
    )
    # Stored rather than walked. ``run_branch()`` needs the first run's ``seq`` so that
    # turn two pushes to the branch turn one created — otherwise a pull-request card
    # that asks a question splits its work across two branches and the PR points at
    # half of it, with no test going red (ADR 0035 §5).
    root_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "task_runs.id", ondelete="SET NULL", name="fk_task_runs_root_run_id", use_alter=True
        ),
        nullable=True,
    )
    # Which answer woke this run. Half of ``uq_task_runs_continuation``, which makes
    # "one question, two continuations" impossible in the database rather than
    # improbable in the service (ADR 0036 §5).
    resumed_question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "task_questions.id",
            ondelete="SET NULL",
            name="fk_task_runs_resumed_question_id",
            use_alter=True,
        ),
        nullable=True,
    )
    # **Not ``attempt``.** ``turn_seq`` counts rounds of conversation; ``attempt``
    # counts retries of one round. A continuation that is requeued three times has
    # ``turn_seq=2`` throughout. Conflating them would make neither answerable.
    turn_seq: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    input_from_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_to_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RunLog(Base):
    """One **aggregated segment** of a run's output, not one chunk (ADR 0030 Part A).

    Central buffers a run's chunks until 64 KiB or two seconds have passed, then
    writes one row. So ``seq`` — the first chunk number in the segment — **skips**; it
    is a sort key, not a counter, the same property ``card_ref`` has.

    The content is the CLI's JSONL event stream plus stderr, never terminal bytes. The
    chunker may not split a JSON line: half an event cannot be rendered, and "do not
    split a line" outranks "fill the chunk".

    Rows are normally deleted as a group by the retention sweep, driven by
    ``TaskRun.logs_expire_at``; the cascade is a safety net. Half a run's log is harder
    to explain than none of it.
    """

    __tablename__ = "run_logs"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    data: Mapped[str] = mapped_column(Text)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TaskMessage(Base):
    """The conversation on a card: human, agent and system, interleaved (FR-AGENT-007).

    ``author_kind`` plus two nullable author columns, rather than one polymorphic
    ``author_id``, for the reason ``ActivityEvent.actor_kind`` documents: a NULL author
    already means "the system", and giving that NULL a second meaning would make both
    unreadable.

    System events are stored **here as well as** in ``activity_events``, and the two
    have different readers: ``activity_events`` is the project timeline, this is one
    card's conversation, and the product requires the three sources interleaved. The
    duplication is the price of that, and it is cheap — system events are short and
    drawn from a closed vocabulary.

    ``run_id`` is SET NULL rather than CASCADE: a run's record may be reclaimed on a
    retention schedule, but **a card's conversation has no retention**.
    """

    __tablename__ = "task_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    author_kind: Mapped[str] = mapped_column(String(16))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    author_runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text)
    # Six values from V2-C1 (``comment``/``question``/``answer``/``proposal``/
    # ``decision``/``system``) plus the two V2.5 spellings still on disk: ``message``
    # reads as ``comment`` and ``event`` as ``system``. **No migration rewrites them**
    # (ADR 0035 §8) — a whole-table UPDATE on a table audit references, to change a
    # display string, is a worse trade than two lines of mapping where the DTO is built.
    kind: Mapped[str] = mapped_column(String(24), default="message")
    event_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # --- conversation (V2-C1, ADR 0035 / 0036) ------------------------------
    # Monotonic, gapless and unique within the card. Backfilled by `0040` in
    # ``(created_at, id)`` order — the second key is not decoration: it is exactly the
    # tie that made timestamp pagination unreliable.
    conversation_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_messages.id", ondelete="SET NULL"), nullable=True
    )
    # Set on an ``answer``. The FK closes a loop (``task_messages`` →
    # ``task_questions`` → ``task_messages``), so it is named and ``use_alter``, the
    # same treatment `0039` gave the specification loop.
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "task_questions.id",
            ondelete="SET NULL",
            name="fk_task_messages_question_id",
            use_alter=True,
        ),
        nullable=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # **Not the same thing as ``run_id``.** ``run_id`` is "which run wrote this"; this
    # is "which turn read this as input". A human's answer has the second and not the
    # first. Catch-up needs the second; audit needs the first.
    turn_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskQuestion(Base):
    """One question's whole life (ADR 0035 §3).

    V2.5 answered "has this been answered?" by scanning messages: any user message
    written after the question counted. That rule is right for a person reading a
    thread and useless to a database — it cannot say *which* question a reply closed,
    and two replies to two questions are indistinguishable from two replies to one.

    A row makes the answer a single-statement compare-and-set::

        UPDATE task_questions SET state='answered' WHERE id=? AND state='open'

    Zero rows is the conflict, one row is the go-ahead. That statement is the whole of
    the concurrency argument, exactly as it is for ``claim()``.

    ``asked_message_id`` cascades and ``answered_message_id`` does not, and the
    asymmetry is deliberate: a question row without its own text means nothing, while
    "answered, and the answer is gone" is a state that still says something. Neither
    happens today — ``task_messages`` has no delete path — but a constraint should be
    able to explain itself.
    """

    __tablename__ = "task_questions"
    __table_args__ = (
        CheckConstraint("state IN ('open','answered','cancelled','expired')", name="state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    asked_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "task_messages.id",
            ondelete="CASCADE",
            name="fk_task_questions_asked_message_id",
            use_alter=True,
        )
    )
    state: Mapped[str] = mapped_column(String(16), default="open")
    answered_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "task_messages.id",
            ondelete="SET NULL",
            name="fk_task_questions_answered_message_id",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationConsumer(Base):
    """How far one reader has got through one card's conversation (ADR 0036 §2).

    **``consumer_id`` has no foreign key**, the same precedent ``tasks.assigned_runner_id``
    set: a cursor may name a run the retention sweep has already removed, and it stays
    meaningful — it says where that reader stopped. A cursor deleted because its run
    aged out would make a reconnecting consumer start again from zero.

    ``last_acked_seq`` controls nothing. It exists so the interface can say
    ``agent_seen``, and a flow that waited on it would stall whenever an agent died
    between reading and acknowledging — precisely the case this design exists to
    survive.
    """

    __tablename__ = "conversation_consumers"
    __table_args__ = (CheckConstraint("last_acked_seq <= last_delivered_seq", name="order"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    consumer_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    consumer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    last_delivered_seq: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_acked_seq: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaskArtifact(Base):
    """A deliverable attached to a card — metadata only (FR-AGENT-009, ADR 0030 Part B).

    The bytes live in :class:`TaskArtifactBlob`. Splitting the tables is what makes
    "list ten artifacts and pull 100 MB into memory" impossible rather than merely
    discouraged.

    ``content_type`` is **determined by the server** from the extension and magic
    bytes, never taken from the uploader's declaration, and anything outside a closed
    table becomes ``application/octet-stream``. This column is the primary stored-XSS
    entry point in the phase.

    Deletion is soft **here** and hard for the bytes. Requiring ``project.manage`` and
    a written reason is pointless if the delete erases who did it and why; but a quota
    that cannot be freed by deleting something is not a quota. Metadata stays, content
    goes.

    There is no update path anywhere — an attached artifact is immutable, and an
    OpenAPI assertion in `AR-12` holds ``/api/artifacts/{id}`` to ``GET`` and
    ``DELETE``.
    """

    __tablename__ = "task_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_messages.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(BigInteger)
    # Not for deduplication — the same file attached twice is two artifacts, and the
    # timeline shows that as versions. It is for verification on download.
    sha256: Mapped[str] = mapped_column(CHAR(64))
    storage_ref: Mapped[str] = mapped_column(String(255))
    uploaded_by_kind: Mapped[str] = mapped_column(String(16))
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by_runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    delete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskArtifactBlob(Base):
    """An artifact's bytes, in a table nothing lists (ADR 0030 Part B).

    Read on download and on nothing else. The primary key is the artifact id rather
    than a surrogate: there is exactly one blob per artifact, and a second id would be
    a second thing to keep consistent.
    """

    __tablename__ = "task_artifact_blobs"

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    bytes: Mapped[bytes] = mapped_column(LargeBinary)


class RunToken(Base):
    """The credential an agent inside a run may hold (ADR 0029 sec 6, plan/18/05-…md).

    A separate table from :class:`SessionToken` for one concrete reason:
    ``session_tokens.session_id`` is NOT NULL against ``terminal_sessions``, and a run
    must not have a session row. Making that column nullable would put two kinds of
    subject in one table and turn "revoking for a session covers every token" into a
    false statement.

    Everything else is deliberately identical: only the HMAC is stored, keyed by the
    same ``CLIORA_TOKEN_PEPPER``; ``scopes`` is snapshotted at issue time; revoked rows
    are kept 90 days because the audit trail names a token id.

    There is no ``issued_by``. A run is not opened by a person — who dispatched it is
    ``TaskRun.created_by``, one join away — and copying it here would give "who holds
    this token" a second, plausible, wrong answer.
    """

    __tablename__ = "run_tokens"
    __table_args__ = (UniqueConstraint("token_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_runs.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class ExecutionPlan(Base):
    """One version of a card's plan (V2.4, FR-PLAN-001, ADR 0033).

    **Append-only, and nothing in the database enforces it.** There is no
    ``updated_at``, no update path in the repository layer, and ``GATE-DV-APPEND-ONLY``
    scans for one. A trigger was considered and rejected: it fires on the statement, so
    the first legitimate correction becomes a database error nobody can act on, and the
    trigger gets dropped rather than read.

    ``note`` is required from ``seq`` 2 onward — *why* the plan changed is the whole
    reason a version row exists rather than a mutable column — and that rule lives in
    the service layer, because as a CHECK the difference between a first plan and a
    revision would surface as an unreadable constraint violation.

    ``project_id`` is redundant (``task_id`` determines it) and deliberate: the
    cross-project metrics aggregate over this table, and without it every one of them
    joins ``tasks``. ``task_artifacts`` set the precedent.
    """

    __tablename__ = "execution_plans"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_execution_plans_task_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    # `SET NULL`, not `CASCADE`: a run row can be reaped after its logs expire, and
    # losing the plan with it would delete the record of what somebody intended because
    # a diagnostic aged out.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_by_kind: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VerificationReport(Base):
    """What the checks said, and **who observed it** (V2.4, FR-VERIFY-001/002, ADR 0033).

    ``source`` is decided by the write path, never by the payload, and the enforcement
    is structural rather than a check: the service function has no ``source`` parameter
    at all, so the caller — which route, which internal path — determines it. A payload
    that names one is discarded **and an activity row is written**, because otherwise an
    agent trying to overstate its evidence and an agent with a typo look identical.

    ``checks[]`` items carry ``origin`` (``project`` | ``card``) beside ``name``,
    ``argv``, ``exit_code``, ``duration_ms`` and ``output_tail``. ``origin`` is a
    **second axis, not a third level**: ``source`` answers who observed this,
    ``origin`` answers who chose to run it. Both origins are ``machine_verified``,
    because declaring a check on a card takes ``task.approve`` and a run token never
    holds it — so neither was chosen by the executor (ADR 0033 sec 3b).

    ``acceptance_criteria`` here is **this run's snapshot** and may disagree with the
    card's current values. That is not a defect: the report says what this run saw and
    the card says what is true now. Merging them would let an old run's report move the
    card's state backwards.
    """

    __tablename__ = "verification_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    result: Mapped[str] = mapped_column(String(16))
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    acceptance_criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    remaining_risks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    completion_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(24))
    reported_by_kind: Mapped[str] = mapped_column(String(16))
    reported_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reported_by_runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EvidenceItem(Base):
    """One observed fact about a card, with its provenance (V2.4, FR-EVIDENCE-001/002).

    **``kind`` decides ``source``, never the other way round.** A single table
    (``_SOURCE_FOR_KIND``) binds them, so "an agent wrote a ``git_state``" is
    *unrepresentable* rather than merely refused — it is rejected before it can become a
    row that looks like a machine fact. That is a level stronger than checking the
    writer's identity, because a check has a second call site and a mapping does not.

    **Contradictions are stored, not resolved.** When the agent's account of which files
    changed disagrees with ``git status``, both rows exist and both name their source.
    Implementing that costs nothing; it is written down because adding a reconciliation
    rule is the natural instinct, and its verdict would be a judgement with nobody
    accountable for it.

    ``payload`` is bounded in the service layer (16 KiB a row, 64 rows a run) and the
    refusal points at artifacts. Artifacts already have a quota, a retention period, a
    download path and a stored-XSS posture (ADR 0030 Part B); letting evidence grow into
    a file store would mean doing all four again here.
    """

    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(24))
    written_by_kind: Mapped[str] = mapped_column(String(16))
    written_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    written_by_runner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runners.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentPatchProposal(Base):
    """A proposed edit to a repository document, before a person decides (FR-SPEC-007).

    **The platform renders it and records the decision. The platform never applies it**
    (ADR 0034 §6). Three reasons, and the third is the one that decides: applying a
    markdown patch is general file editing, which `plan/14` designed and had withdrawn;
    Central holds no clone, so "apply" has nowhere to happen; and routing the edit
    through an ordinary ``delivery: pull_request`` card gives the document the same
    review a code change gets — which is better than the platform applying it, not
    merely safer.

    ``diff`` is ``Text`` and is never parsed. Parsing is half the distance to applying,
    and the service bounds its size instead.

    Deliberately **not** a ``TaskArtifact``. An artifact is inert — nothing about it is
    decided, it has no status, and it is listed per card. This has a decision attached,
    is listed per project as "still pending", and would give that table a state machine
    it was designed without (ADR 0030).

    Insert-only apart from the four decision columns, which one endpoint writes once.
    """

    __tablename__ = "document_patch_proposals"
    __table_args__ = (
        UniqueConstraint("project_id", "seq", name="uq_document_patch_proposals_project_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # Nullable: an implementation run that noticed a document was wrong has no
    # requirement behind it, and that is a legitimate origin for a proposal.
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Numbered per project rather than per requirement, because the row above may have
    # none and a proposal still needs a name a person can say out loud.
    seq: Mapped[int] = mapped_column(Integer)
    target_path: Mapped[str] = mapped_column(String(512))
    diff: Mapped[str] = mapped_column(Text)
    sections: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_task_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # A first-class column here for the same reason it is one on ``FeatureSpec``: an
    # unresolved question inside a proposal has to be visible. Unlike a specification's,
    # it does **not** block acceptance — accepting a patch proposal produces nothing,
    # while approving a specification unlocks decomposition. Asymmetric gates need
    # asymmetric reasons, and that is this one's.
    open_questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# V2-K1 — project memory (ADR 0038 / 0039)
# ---------------------------------------------------------------------------


class KnowledgeSource(Base):
    """One version of one fact the project already had, kept so it can be found again.

    **Nothing writes here by hand.** Every row is derived from something the platform
    already stores, or — for ``repo_doc`` — from a checkout the platform already caused
    to exist. That absence of an authoring path is the property that keeps this from
    becoming a wiki: a derived copy cannot go stale relative to its original, because
    it *is* its original, re-read.

    ``authority`` is **a column, not a derivation** (ADR 0038 sec 2). Deriving it would
    need a join to the origin table and there are eight of those; it changes over time
    and the change is itself auditable; and "what was this trusted as *at the time*" is
    a historical fact that a derivation cannot answer. Only the ingestion pipeline
    writes it — ``GATE-KN-AUTHORITY-SERVER-SIDE`` asserts no request schema has the
    field, the same structural rule ``FR-VERIFY-002`` states for a report's ``source``.

    ``source_version`` takes a monotonic counter where one exists, a content address
    where one does not, and a timestamp only when neither is available. The order
    matters both ways: a timestamp cannot be an identity when two workers may handle one
    entity in the same second, and a content hash cannot be one for a ticket, because
    then correcting a typo starts a new version and the supersede chain has two hundred
    links by the end of the week.

    ``active`` and ``deleted_at`` say different things and **neither deletes the row**:
    the first is "not in default retrieval" (the switch is off, superseded, or a person
    excluded it), the second is "the original is gone". ``context_packs.source_manifest``
    may cite this row, and a manifest that can answer "this source has since been
    deleted" is worth more than one holding a dangling id.
    """

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_type",
            "source_external_id",
            "source_version",
            name="uq_knowledge_sources_identity",
        ),
        CheckConstraint(
            "source_type IN ('policy','ticket','conversation','decision',"
            "'artifact','verification','repo_doc','activity')",
            name="source_type",
        ),
        CheckConstraint(
            "authority IN ('authoritative','accepted','canonical','verified','reviewed',"
            "'generated','discussion','diagnostic','superseded','retracted')",
            name="authority",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(32))
    source_external_id: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_version: Mapped[str] = mapped_column(String(128))
    authority: Mapped[str] = mapped_column(String(16))
    visibility: Mapped[str] = mapped_column(
        String(16), default="project", server_default=text("'project'")
    )
    checksum: Mapped[str] = mapped_column(CHAR(64))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authored_by_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    authored_by_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The comparison column for the idempotent upsert. **Not the same as
    # ``occurred_at``**: a message written yesterday may be ingested today, and it is
    # this that decides whether an arriving row is newer than the stored one.
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Derived, and stored anyway: the Sources panel asks for five source families at
    # once, and ``count(*)`` over ``knowledge_chunks`` five times a page load is five
    # scans of the largest table in the schema.
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    supersedes_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeChunk(Base):
    """A retrievable slice of a source, with the two indexes that find it.

    ``project_id`` **is denormalised on purpose.** It could be joined through
    ``source_id``; the column buys a shorter proof instead. Every table can then be
    asserted independently in an isolation test, and ``GATE-KN-PROJECT-SCOPED`` can
    require a ``project_id`` predicate on every select — a gate that is only *writable*
    because the column is on every table.

    ``search_document`` is ``NOT NULL`` although nothing in the database computes it. It
    is built in Python from a single tokenizer (ADR 0038 sec 4): ``to_tsvector`` is
    ``STABLE``, so PostgreSQL refuses it in a generated column, and a trigger would
    split "how is the index computed" across two languages. The constraint means any
    path that inserts a chunk without going through ``services/knowledge/`` fails
    loudly, which is the intent — the tokenizer must be the only writer, because when
    the index and the query disagree the result is silence rather than an error.

    ``chunk_key`` is an ordinal rather than a content hash. A hash would make "a
    sentence was added at the top" mean every chunk is new, and rebuild the whole GIN
    index for a typo.

    ``embedding_ref`` is reserved by D40 and is always ``NULL`` here. The column exists
    so that the day a vector channel is added is a data migration rather than a schema
    argument.
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("source_id", "chunk_key", name="uq_knowledge_chunks_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    chunk_key: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    token_count: Mapped[int] = mapped_column(Integer)
    embedding_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    search_document: Mapped[Any] = mapped_column(TSVECTOR)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeLink(Base):
    """An explicit relation between two sources, used by the graph boost.

    A table rather than a JSONB list on the source, because this is the one relation
    with queries of its own and it is read in **both** directions — "what supersedes
    this" and "what does this verify". The primary key serves only the first, which is
    why ``ix_knowledge_links_to`` exists.
    """

    __tablename__ = "knowledge_links"
    __table_args__ = (
        CheckConstraint(
            "relation IN ('supersedes','derived_from','references','verifies','delivers','blocks')",
            name="relation",
        ),
    )

    from_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(String(24), primary_key=True)
    to_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), primary_key=True
    )


class KnowledgeJob(Base):
    """ "This entity may have changed; go and look."

    **A job holds an entity key, never content** (ADR 0038 sec 3.2). The worker re-reads
    the entity's current state and upserts from that, which is what makes retries free,
    duplicate enqueues free, and the scheduled reconciler and a human's "resync" button
    the same code path. The bug class "the payload in the job was stale by the time it
    ran" does not exist here.

    Claiming is ``FOR UPDATE SKIP LOCKED``, so there is **no cursor** — which matters,
    because a cursor over ``activity_events`` would be unsafe: its ``id`` is a ``uuid4``
    and its ``occurred_at`` is the transaction's start time, so a row that began earlier
    and committed later is skipped, and a ``BIGSERIAL`` would only move the problem to
    sequence holes.

    ``started_at`` is how a job that was ``running`` when Central was killed is
    recognised. Its recovery deliberately does **not** count an attempt: that was not a
    failed try, it was a try with no conclusion, and counting it would send good jobs to
    the dead letter after three restarts.
    """

    __tablename__ = "knowledge_jobs"
    __table_args__ = (
        CheckConstraint("state IN ('pending','running','done','failed','dead')", name="state"),
        CheckConstraint(
            "source_type IN ('policy','ticket','conversation','decision',"
            "'artifact','verification','repo_doc','activity')",
            name="source_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaskKnowledgePin(Base):
    """A person overriding the ranking for one card.

    ``pin`` outranks every computed score rather than merely adding to it, and ``exclude``
    removes a source from this card alone. That asymmetry with a tombstone is the point:
    excluding is "this card should not use it" and is reversible per card, while a
    tombstone is "it does not exist" and is project-wide. Merging the two would mean one
    person excluding a document on one card silently removed it from forty others.

    ``created_by`` is ``SET NULL``, so a pin outlives the person who made it. That is
    correct — a pin is the project's decision about a card rather than that person's
    preference — but it is written down here because the first reader to see a NULL will
    otherwise assume the data is broken.
    """

    __tablename__ = "task_knowledge_pins"
    __table_args__ = (CheckConstraint("mode IN ('pin','exclude')", name="mode"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(8))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextPack(Base):
    """What one turn actually read, recorded when it read it.

    Written on **fetch**, not on offer (ADR 0039): at offer time nobody knows whether the
    agent will come and get it, and a row claiming it did would be a lie the audit trail
    tells. A run may fetch more than once — a retry, a continuation — and each fetch is
    its own row, deliberately without a unique key, because two fetches returning
    different content is exactly the thing that has to stay visible.

    ``source_manifest`` holds **ids and metadata, never content**. Storing the text would
    make a second copy of the most sensitive material in the system and place it outside
    every retention rule that governs the first.

    The row cascades from its run (ADR 0038 sec 6): "what this turn read" is a
    diagnostic and shares the run's lifetime, in the same way a run log does. The
    durable record is the citation inside the agent's message, and messages never
    expire — a manifest is a debugging tool, a citation is the record.
    """

    __tablename__ = "context_packs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    turn_seq: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    source_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    omitted_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
