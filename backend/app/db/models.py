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
    authored_by_kind: Mapped[str] = mapped_column(String(16), default="user")
    authored_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_proposals.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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

    ``labels`` are **displayed and never compared** in V2.2. Label matching is V2.3.
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

    V2.3's three credential columns (``auth_kind``, ``credential_secret_id``,
    ``provider_token_secret_id``) are **deliberately not created yet**, unlike the
    card's execution settings which ADR 0028 declared early. The difference: those
    three would be foreign keys to ``project_secrets``, a table this phase does not
    have, and a nullable UUID pointing at a table that does not exist is something no
    reader can validate.
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
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
    log_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    log_truncated_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    logs_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    kind: Mapped[str] = mapped_column(String(24), default="message")
    event_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
