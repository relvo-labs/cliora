from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.models import EnrollmentToken, TerminalSession, User
from app.services.audit_query import AuditItem, AuditPage
from app.services.dashboard import Summary
from app.services.enrollment import token_status
from app.services.favorites import Usability
from app.services.integrations import IntegrationView
from app.services.nodes import RegisterNodeInput, RuntimeInput, WorkspaceRootInput
from app.services.rbac import role_actions
from app.services.releases import Manifest
from app.services.tunnels import TunnelView
from app.settings import Settings, get_settings


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: str
    permissions: list[str]
    # What this **deployment** has, as opposed to what this **person** may do. The
    # browser ANDs the two and the server checks both independently — a feature flag
    # is not a permission and must never be read as one.
    #
    # It cannot be folded into `permissions`: seed migrations run unconditionally, so
    # an Admin holds `project.manage` even where the project layer is switched off.
    # Shaped like `permissions` (a sorted string array) so V2.2 adds one string
    # rather than a new response shape.
    features: list[str] = []

    @classmethod
    def from_user(cls, user: User, *, settings: Settings | None = None) -> UserResponse:
        resolved = settings or get_settings()
        features: list[str] = []
        if resolved.projects_enabled:
            features.append("projects")
        # One more string, exactly as the comment above anticipated — not a new response
        # shape. **Both flags**, because the runner layer is the inner of two: a
        # deployment with the project layer off does not have agent runs either, and a
        # `features` array that said otherwise would have the console offer a page that
        # answers 404.
        if resolved.projects_enabled and resolved.agent_runs_enabled:
            features.append("agent_runs")
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role.name,
            permissions=sorted(role_actions(user)),
            features=features,
        )


class LoginResponse(BaseModel):
    tokens: TokenResponse
    user: UserResponse


class WsTicketRequest(BaseModel):
    resource: str = Field(min_length=1, max_length=256)


class WsTicketResponse(BaseModel):
    ticket: str


# --- P2 sessions (PRD §11.6, ADR 0013) ---
class CreateSessionRequest(BaseModel):
    node_id: uuid.UUID
    # `shell` is deliberately absent: a system terminal is opened through
    # POST /api/sessions/{id}/shell, which supplies the parent. Allowing it here
    # would put a shell in the New Session dialog and the session list, with no
    # parent to bind its lifetime to (ADR 0021).
    runtime: Literal["claude", "codex", "fake"]
    name: str = Field(min_length=1, max_length=128)
    workspace: str = Field(min_length=1, max_length=4096)
    rows: int = Field(default=24, ge=2, le=300)
    columns: int = Field(default=80, ge=2, le=500)
    # Optional, and permanently so (ADR 0027): a session belonging to no project is
    # an *ad-hoc* session, which is part of the product rather than a transitional
    # state. The platform never infers it from the workspace — one path may be bound
    # to several projects, so there is no unique answer, and "is this ad-hoc" has to
    # stay the caller's statement. Present in the schema whichever way the feature
    # flag is set, because the OpenAPI document is static; the refusal happens at
    # run time.
    project_id: uuid.UUID | None = None
    # Optional, and permanently so for the same reason `project_id` is (ADR 0028).
    # Requires `project_id`: a card belongs to a project, and inferring one from the
    # other would make "is this ad-hoc" a platform judgement instead of the caller's
    # statement.
    task_id: uuid.UUID | None = None


class OpenShellRequest(BaseModel):
    """Only a terminal size. Node, workspace and runtime all come from the parent
    session, and the binary comes from the node — there is nothing here for a
    caller to point at a command (SEC-002)."""

    rows: int = Field(default=24, ge=2, le=300)
    columns: int = Field(default=80, ge=2, le=500)


class SessionCapabilities(BaseModel):
    """What the requesting user may do to this session, computed by the server.

    The browser renders these flags instead of re-deriving the owner rules
    (ADR 0016). They are a UI convenience, never the authorization itself: every
    hidden control has an independent server-side 403 test.
    """

    can_view: bool
    can_write: bool
    can_takeover: bool
    can_terminate: bool
    can_browse_files: bool
    # Role plus ownership, computed here rather than in the browser: a
    # role-only check cannot express "may write to a colleague's session"
    # (ADR 0016, ADR 0024).
    can_upload_files: bool
    # Whether this viewer may open a system terminal *inside* this session. Already
    # folds in the action, ownership and the node's own veto, so the browser has
    # nothing left to combine (ADR 0021).
    can_open_shell: bool


class SessionSummary(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    runtime: str
    workspace: str
    status: str
    rows: int
    columns: int
    pid: int | None
    started_at: datetime | None
    last_activity_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    capabilities: SessionCapabilities
    # Always present, `null` for an ad-hoc session and for every session in a
    # deployment with the flag off. Deliberately not omitted in that case: a field
    # whose presence depends on configuration gives the browser two response shapes
    # to type.
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None

    @classmethod
    def from_model(cls, s: TerminalSession, *, viewer: User) -> SessionSummary:
        """`viewer` is required on purpose: with a default it was silently omitted
        on the create path, so a freshly created session reported that its own
        creator could do nothing with it. A missing viewer is now a type error."""
        return cls(
            id=s.id,
            node_id=s.node_id,
            user_id=s.user_id,
            name=s.name,
            runtime=s.runtime,
            workspace=s.workspace,
            status=s.status,
            rows=s.rows,
            columns=s.columns,
            pid=s.pid,
            started_at=s.started_at,
            last_activity_at=s.last_activity_at,
            ended_at=s.ended_at,
            created_at=s.created_at,
            capabilities=_capabilities(s, viewer),
            project_id=s.project_id,
            task_id=s.task_id,
        )


class SessionDetail(SessionSummary):
    exit_code: int | None = None
    error_message: str | None = None
    context_projection: str | None = None
    context_projection_detail: str | None = None

    @classmethod
    def from_model(
        cls,
        s: TerminalSession,
        *,
        viewer: User,
        context_projection: str | None = None,
        context_projection_detail: str | None = None,
    ) -> SessionDetail:
        base = SessionSummary.from_model(s, viewer=viewer)
        return cls(
            **base.model_dump(),
            exit_code=s.exit_code,
            error_message=s.error_message,
            context_projection=context_projection,
            context_projection_detail=context_projection_detail,
        )


def _capabilities(s: TerminalSession, viewer: User) -> SessionCapabilities:
    # Imported here: app.services.authz imports app.api.errors, and a top-level
    # import would make schemas <-> authz circular.
    from app.services.authz import session_capabilities

    return SessionCapabilities(**session_capabilities(viewer, s))


class AttachTicketResponse(BaseModel):
    session_id: uuid.UUID
    ticket: str


class CreateEnrollmentTokenRequest(BaseModel):
    ttl_seconds: int | None = Field(default=None, gt=0, le=30 * 24 * 3600)
    max_uses: int | None = Field(default=None, gt=0, le=1000)


class EnrollmentTokenCreatedResponse(BaseModel):
    id: uuid.UUID
    # Plaintext is returned exactly once, at creation (SEC-003).
    token: str
    expires_at: datetime
    max_uses: int


class EnrollmentTokenResponse(BaseModel):
    id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
    expires_at: datetime
    max_uses: int
    used_count: int
    status: str

    @classmethod
    def from_token(cls, token: EnrollmentToken) -> EnrollmentTokenResponse:
        return cls(
            id=token.id,
            created_by=token.created_by,
            created_at=token.created_at,
            expires_at=token.expires_at,
            max_uses=token.max_uses,
            used_count=token.used_count,
            status=token_status(token),
        )


# What a node may report about itself at enrolment. This is *not* the set a
# session may be started with: `fake` is a dev runtime that `_require_runtime`
# short-circuits and no node ever enumerates, while `shell` must appear here even
# though it cannot be named in CreateSessionRequest — the node's report is the only
# place the system terminal's availability and the operator's `enabled: false` are
# expressed (ADR 0021). `test_node_reported_runtimes_match_the_session_service`
# fails if this drifts from services.sessions.RUNTIMES again.
NodeReportedRuntime = Literal["claude", "codex", "shell"]


class RuntimeItemDTO(BaseModel):
    runtime: NodeReportedRuntime
    available: bool
    version: str | None = Field(default=None, max_length=128)
    binary_path: str | None = Field(default=None, max_length=4096)
    checked_at: datetime | None = None
    # Optional on the wire (contract 1.7.0): absent means the sandbox is enforced.
    sandbox_bypass: bool = False

    def to_input(self) -> RuntimeInput:
        return RuntimeInput(
            runtime=self.runtime,
            available=self.available,
            version=self.version,
            binary_path=self.binary_path,
            checked_at=self.checked_at,
            sandbox_bypass=self.sandbox_bypass,
        )


class WorkspaceRootDTO(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    display_name: str | None = Field(default=None, max_length=128)
    is_enabled: bool = True

    def to_input(self) -> WorkspaceRootInput:
        return WorkspaceRootInput(
            path=self.path, display_name=self.display_name, is_enabled=self.is_enabled
        )


class RegisterNodeRequest(BaseModel):
    token: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=128)
    hostname: str = Field(min_length=1, max_length=255)
    os: str = Field(min_length=1, max_length=64)
    os_version: str = Field(min_length=1, max_length=128)
    architecture: Literal["amd64", "arm64"]
    daemon_version: str = Field(min_length=1, max_length=64)
    run_user: str = Field(min_length=1, max_length=64)
    public_key: str = Field(min_length=43, max_length=44)
    # The installer reports the posture it just created (ADR 0023). Report-only: this
    # is the enrollment call, so there is no later API that can set it.
    privileged_terminal: bool = False
    image_upload: bool = False
    file_upload: bool = False
    runtimes: list[RuntimeItemDTO] = Field(default_factory=list, max_length=16)
    workspace_roots: list[WorkspaceRootDTO] = Field(default_factory=list, max_length=64)

    def to_input(self) -> RegisterNodeInput:
        return RegisterNodeInput(
            name=self.name,
            hostname=self.hostname,
            os=self.os,
            os_version=self.os_version,
            architecture=self.architecture,
            daemon_version=self.daemon_version,
            run_user=self.run_user,
            public_key=self.public_key,
            privileged_terminal=self.privileged_terminal,
            image_upload=self.image_upload,
            file_upload=self.file_upload,
            runtimes=[r.to_input() for r in self.runtimes],
            workspace_roots=[w.to_input() for w in self.workspace_roots],
        )


class RegisterNodeResponse(BaseModel):
    node_id: uuid.UUID
    server_url: str


class NodeRuntimeDTO(BaseModel):
    runtime: str
    available: bool
    version: str | None
    binary_path: str | None
    checked_at: datetime | None
    # True when this runtime is launched with its sandbox and approval prompts off
    # (ADR 0023). The console shows it next to the runtime, because the person about
    # to start a session is the one who needs to know.
    sandbox_bypass: bool = False


class NodeWorkspaceRootDTO(BaseModel):
    path: str
    display_name: str | None
    is_enabled: bool


class NodeSummary(BaseModel):
    id: uuid.UUID
    name: str
    hostname: str
    status: str
    os: str | None
    architecture: str | None
    claude_available: bool
    codex_available: bool
    session_count: int
    last_seen_at: datetime | None


class NodeResourcesDTO(BaseModel):
    """Latest heartbeat resource sample (live; null when the node is offline)."""

    cpu_usage: float | None = None
    memory_usage: float | None = None
    load_average: float | None = None
    disk_usage: float | None = None
    daemon_uptime: float | None = None


class UpdateStatusDTO(BaseModel):
    current_version: str | None
    # The newest allowlisted release, from `GET /api/releases/manifest`. None when
    # nothing is published — which is not an error, just nothing to offer.
    latest_version: str | None = None
    # None means this node has never been asked to update, which is a different
    # fact from `succeeded`.
    status: str | None = None
    target_version: str | None = None
    # A stable `UPDATE_*` code or "succeeded". Never a daemon error string.
    last_result: str | None = None
    updated_at: datetime | None = None
    # Still false: MVP updates are explicitly triggered, never scheduled (ADR 0017).
    auto_update_enabled: bool = False


class RecentErrorDTO(BaseModel):
    occurred_at: datetime
    message: str


class NodeDetail(NodeSummary):
    os_version: str | None
    daemon_version: str | None
    run_user: str | None
    # Posture, as reported by the node. Shown in the console and not settable here:
    # there is deliberately no endpoint that writes it (ADR 0023 D11).
    privileged_terminal: bool
    # Whether this node accepts image drop; the console hides the affordance when
    # false rather than offering a button that always fails (ADR 0024 W4).
    image_upload: bool
    # Whether this node accepts general file upload — an arbitrary file at a
    # user-chosen path (ADR 0026 §9). Two flags rather than one: the console gates
    # the terminal's paste affordance on the first and the file tree's drop target
    # on the second, and a machine may allow one without the other.
    file_upload: bool
    is_enabled: bool
    registered_at: datetime
    runtimes: list[NodeRuntimeDTO]
    workspace_roots: list[NodeWorkspaceRootDTO]
    resources: NodeResourcesDTO | None
    update_status: UpdateStatusDTO
    recent_errors: list[RecentErrorDTO]


class SetNodeEnabledRequest(BaseModel):
    enabled: bool
    # Reserved hook: P2 session teardown when disabling. No effect in P1.
    terminate_sessions: bool = False


class RotateCredentialRequest(BaseModel):
    # The daemon generates a fresh Ed25519 keypair locally and submits only the
    # public key; the private key never leaves the node.
    public_key: str = Field(min_length=43, max_length=44)


# --- P4-13 workspace favourites and recents (FR-WORKSPACE-004/005) ---


class WorkspaceFavoriteDTO(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    node_name: str
    path: str
    display_name: str | None
    created_at: datetime
    # Computed per request, never stored: a favourite saved while a root existed must not
    # keep claiming to be usable after that root is removed. `usable` means a session
    # could be created from it now; anything else carries the reason.
    usability: Usability


class CreateWorkspaceFavoriteRequest(BaseModel):
    node_id: uuid.UUID
    path: str = Field(min_length=1, max_length=4096)
    display_name: str | None = Field(default=None, max_length=128)


class RecentWorkspaceDTO(BaseModel):
    """A workspace this user recently started a session in.

    Derived from `terminal_sessions` — there is no table. A *terminated* session still
    counts: "recently used" is history, and getting back to somewhere you were is the
    whole point.
    """

    node_id: uuid.UUID
    node_name: str
    path: str
    last_used_at: datetime
    # Offline entries are shown rather than filtered: "your workspace is there but that
    # machine is down" is more useful than the entry silently vanishing (FR-NODE-002).
    node_online: bool
    node_enabled: bool


# --- P4-10 daemon release + update (ADR 0017) ---


class ReleaseArtifactDTO(BaseModel):
    version: str
    architecture: str
    filename: str
    sha256: str
    size: int


class ReleaseManifestDTO(BaseModel):
    """The closed set of installable releases.

    `latest` is null on an empty deployment; the response is still 200 so a daemon
    can tell "nothing published" from "no such endpoint".
    """

    latest: str | None
    artifacts: list[ReleaseArtifactDTO]
    generated_at: datetime

    @classmethod
    def from_manifest(cls, manifest: Manifest) -> ReleaseManifestDTO:
        return cls(
            latest=manifest.latest,
            artifacts=[
                ReleaseArtifactDTO(
                    version=artifact.version,
                    architecture=artifact.architecture,
                    filename=artifact.filename,
                    sha256=artifact.sha256,
                    size=artifact.size,
                )
                for artifact in manifest.artifacts
            ],
            generated_at=manifest.generated_at,
        )


class UpdateNodeRequest(BaseModel):
    """The only thing a client may say about an update.

    Deliberately not a URL, a filename or a digest: those are derived by the daemon
    from the release manifest and its own config (SEC-002). A client that could name
    an artifact could name any artifact.
    """

    target_version: str = Field(min_length=5, max_length=64)
    # A downgrade is refused unless asked for explicitly, so "update" can never
    # silently move a fleet backwards.
    allow_downgrade: bool = False


# --- P4-06 dashboard aggregates (PRD §10.2, ADR 0018) ---


class DashboardBlockDTO(BaseModel):
    """One independently-fetched aggregate.

    `data` is a per-block shape rather than a union: the invariant that matters on
    the wire is uniform, and it is the failure shape. A block that could not be
    fetched is always `status="degraded"`, `data=null`, `error_code` set — so a
    client renders "temporarily unavailable" for that card and nothing else. The
    concrete shapes are mirrored in `frontend/src/api/dto.ts` and asserted by
    `tests/db/test_dashboard_api.py`.
    """

    status: Literal["ok", "stale", "degraded"]
    # When the data was fetched, not when the request arrived: a cache hit must be
    # visible as one (ADR 0018).
    generated_at: datetime
    data: dict[str, Any] | None
    error_code: str | None = None


class DashboardSummaryDTO(BaseModel):
    generated_at: datetime
    blocks: dict[str, DashboardBlockDTO]

    @classmethod
    def from_summary(cls, summary: Summary) -> DashboardSummaryDTO:
        return cls(
            generated_at=summary.generated_at,
            blocks={
                name: DashboardBlockDTO(
                    status=block.status,  # type: ignore[arg-type]
                    generated_at=block.generated_at,
                    data=block.data,
                    error_code=block.error_code,
                )
                for name, block in summary.blocks.items()
            },
        )


# --- P4-05 audit query (ADR 0016) ---


class AuditActorDTO(BaseModel):
    """Who acted. `null` on the item when the row has no actor (a daemon- or
    system-initiated event) or when the account no longer exists — the ids are
    kept either way so the trail is never silently shortened."""

    id: uuid.UUID
    username: str | None
    display_name: str | None


class AuditNodeDTO(BaseModel):
    id: uuid.UUID
    name: str | None


class AuditItemDTO(BaseModel):
    id: uuid.UUID
    action: str
    created_at: datetime
    actor: AuditActorDTO | None
    node: AuditNodeDTO | None
    session_id: uuid.UUID | None
    # Correlates the row with that request's logs; None for daemon/system events.
    request_id: str | None
    # Already minimized on write and re-filtered on read (services/audit_query.py).
    metadata: dict[str, Any]

    @classmethod
    def from_item(cls, item: AuditItem) -> AuditItemDTO:
        return cls(
            id=item.id,
            action=item.action,
            created_at=item.created_at,
            actor=(
                AuditActorDTO(
                    id=item.user_id, username=item.username, display_name=item.display_name
                )
                if item.user_id is not None
                else None
            ),
            node=(
                AuditNodeDTO(id=item.node_id, name=item.node_name)
                if item.node_id is not None
                else None
            ),
            session_id=item.session_id,
            request_id=item.request_id,
            metadata=item.metadata,
        )


class AuditPageDTO(BaseModel):
    items: list[AuditItemDTO]
    # Absent when the window is exhausted. There is deliberately no total: a count
    # over the window would cost a second scan and the UI must not invent one.
    next_cursor: str | None = None

    @classmethod
    def from_page(cls, page: AuditPage) -> AuditPageDTO:
        return cls(
            items=[AuditItemDTO.from_item(item) for item in page.items],
            next_cursor=page.next_cursor,
        )


# --- P11 port forwarding through a third-party provider (ADR 0022) ---
#
# The one rule that shapes every DTO below: no response type has a field the provider
# credential or a tunnel password could travel in. `TunnelCredentialDTO` carries the
# fingerprint and nothing else, and `basic_auth_password` exists only on `TunnelDetail`,
# which is returned by exactly two routes. Both are asserted by test, because "we do not put
# it in the response" is a property of the type, not of the intention.


class TunnelCredentialDTO(BaseModel):
    """What an interface may know about the stored provider credential (D19).

    There is no "reveal" affordance to design for: the browser never receives the token, so
    a show-password control could not be built even if someone asked for one. The fingerprint
    answers the only question an administrator actually has — "is this the one I rotated
    last week".
    """

    configured: bool
    fingerprint: str | None
    updated_at: datetime | None
    updated_by: uuid.UUID | None


class TunnelIntegrationDTO(BaseModel):
    enabled: bool
    provider: str
    plan_tier: str
    credential: TunnelCredentialDTO
    concurrent_budget: int
    default_protection: str
    default_ttl_seconds: int
    allowed_ports: list[str] | None
    acknowledged_at: datetime | None
    # Reported by the server so the settings page can say "this environment cannot store a
    # credential" before an administrator types one, rather than after pressing save.
    secret_key_available: bool
    # Reported alongside because disabling does not close what is already running: the
    # consequence has to be visible before the switch is thrown, not explained afterwards.
    active_tunnel_count: int

    @classmethod
    def from_view(cls, view: IntegrationView, *, active_tunnel_count: int) -> TunnelIntegrationDTO:
        return cls(
            enabled=view.enabled,
            provider=view.provider,
            plan_tier=view.plan_tier,
            credential=TunnelCredentialDTO(
                configured=view.credential.configured,
                fingerprint=view.credential.fingerprint,
                updated_at=view.credential.updated_at,
                updated_by=view.credential.updated_by,
            ),
            concurrent_budget=view.concurrent_budget,
            default_protection=view.default_protection,
            default_ttl_seconds=view.default_ttl_seconds,
            allowed_ports=view.allowed_ports,
            acknowledged_at=view.acknowledged_at,
            secret_key_available=view.secret_key_available,
            active_tunnel_count=active_tunnel_count,
        )


class UpdateTunnelIntegrationRequest(BaseModel):
    enabled: bool | None = None
    plan_tier: Literal["free", "pro"] | None = None
    concurrent_budget: int | None = Field(default=None, ge=1, le=100)
    default_protection: Literal["basic", "ipallow", "public"] | None = None
    default_ttl_seconds: int | None = Field(default=None, ge=60, le=86400)
    allowed_ports: list[str] | None = Field(default=None, max_length=64)
    # Separate from `allowed_ports: null`, which means "leave it alone": an empty list forbids
    # every port and NULL removes the platform-wide narrowing, and those are opposite
    # intentions that must not share an encoding.
    clear_allowed_ports: bool = False
    # The administrator's one-time acknowledgement that forwarded traffic leaves for a third
    # party (D14). Never defaulted to true anywhere on the server.
    acknowledge: bool = False


class SetTunnelCredentialRequest(BaseModel):
    """The pattern is a security control, not tidiness.

    This value is concatenated into ssh's `<token>@<host>` argument on the node, where the
    provider separates modifiers with `+` and the host with `@`. A token containing `+tcp`
    would change the tunnel type; one containing `@evil.host` would change where the node
    connects. Validated here, on the wire, and again in the service.
    """

    token: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9]+$")
    plan_tier: Literal["free", "pro"] | None = None


class TunnelCapabilities(BaseModel):
    can_close: bool
    can_rotate: bool


class TunnelSummary(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    node_name: str | None
    port: int
    label: str | None
    # Assigned by the provider seconds after creation, and reassigned on every reconnect on
    # the free tier — which is why `url_updated_at` and `url_change_count` travel with it.
    url: str | None
    url_updated_at: datetime | None
    url_change_count: int
    # Derived per response from closed_at/expires_at/state_error_code and whether the node is
    # connected. There is no stored status to disagree with (ADR 0022).
    state: str
    protection: str
    basic_auth_user: str | None
    provider: str
    # The provider's own deadline, kept apart from ours: "we ended it" and "they ended it"
    # need different explanations.
    upstream_expires_at: datetime | None
    expires_at: datetime
    created_by_username: str | None
    created_at: datetime
    capabilities: TunnelCapabilities
    state_error_code: str | None

    @classmethod
    def from_view(cls, view: TunnelView) -> TunnelSummary:
        tunnel = view.tunnel
        return cls(
            id=tunnel.id,
            node_id=tunnel.node_id,
            node_name=view.node_name,
            port=tunnel.port,
            label=tunnel.label,
            url=tunnel.url,
            url_updated_at=tunnel.url_updated_at,
            url_change_count=tunnel.url_change_count,
            state=view.state,
            protection=tunnel.protection,
            basic_auth_user=tunnel.basic_auth_user,
            provider=tunnel.provider,
            upstream_expires_at=tunnel.upstream_expires_at,
            expires_at=tunnel.expires_at,
            created_by_username=view.created_by_username,
            created_at=tunnel.created_at,
            capabilities=TunnelCapabilities(can_close=view.can_close, can_rotate=view.can_rotate),
            state_error_code=tunnel.state_error_code,
        )


class TunnelDetail(TunnelSummary):
    """The creation and rotation response, and the only DTO with a password field.

    `basic_auth_password` is populated on those two paths and nowhere else, because only the
    Argon2 hash is stored: there is no later request that could return it. Rotating means
    closing and reopening the tunnel, so the URL may change — the field pair
    (`url`, `url_updated_at`) is how the caller sees that it did.
    """

    allowed_ips: list[str] | None = None
    rewrite_host: bool = False
    basic_auth_password: str | None = None

    @classmethod
    def from_view(cls, view: TunnelView) -> TunnelDetail:
        base = TunnelSummary.from_view(view)
        return cls(
            **base.model_dump(),
            allowed_ips=view.tunnel.allowed_ips,
            rewrite_host=view.tunnel.rewrite_host,
            basic_auth_password=view.basic_auth_password,
        )


class CreateTunnelRequest(BaseModel):
    """There is deliberately no `url`, `host`, `provider_options` or `ssh_options` field.

    Central must not become the source of what a node runs (SEC-002): the provider host is a
    daemon-side constant and the target is always the node's own loopback.
    """

    node_id: uuid.UUID
    port: int = Field(ge=1024, le=65535)
    protection: Literal["basic", "ipallow", "public"] | None = None
    allowed_ips: list[str] | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=128)
    ttl_seconds: int | None = Field(default=None, ge=60, le=86400)
    # Off by default: rewriting Host makes a dev server's own absolute URLs point at
    # loopback, which is worse than the allowlist refusal it works around (PG-01 #11).
    rewrite_host: bool = False
    acknowledge_third_party: bool = False
    acknowledge_public: bool = False


class NodeTunnelPolicyDTO(BaseModel):
    """The effective policy for one node, and what each layer contributed to it.

    The per-layer detail is the point rather than decoration: with three layers, "you cannot
    forward this port" has three possible causes and three different people who can fix it.
    A page that shows only the outcome makes the user change settings at random.
    """

    node_id: uuid.UUID
    enabled: bool
    # `integration` / `node_settings` / `node_local`, or null when nothing refuses.
    blocked_by: str | None
    allowed_ports: list[str]
    max_tunnels: int
    live_tunnel_count: int
    # The platform's per-node settings, which this page edits.
    node_enabled: bool
    node_allowed_ports: list[str] | None
    node_max_tunnels: int | None
    # The node's own last report. `reported_at` is null when it has never spoken, which is a
    # different state from "not ready" and the reason both are shown.
    local_veto: bool
    prereq_ok: bool
    prereq_detail: dict[str, Any] | None
    local_allowed_ports: list[str] | None
    local_max_tunnels: int | None
    reported_at: datetime | None
    # From the integration row, so the page can explain the free tier's hourly URL change and
    # the public IP embedded in its hostnames without hardcoding a plan.
    plan_tier: str
    default_protection: str
    default_ttl_seconds: int


class UpdateNodeTunnelSettingsRequest(BaseModel):
    enabled: bool | None = None
    allowed_ports: list[str] | None = Field(default=None, max_length=64)
    clear_allowed_ports: bool = False
    max_tunnels: int | None = Field(default=None, ge=1, le=100)
    clear_max_tunnels: bool = False


# --- V2.0 project layer (ADR 0027, PJ-04) ---


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    # Optional: derived from the name when absent. Never auto-suffixed on collision —
    # a name the user did not choose, chosen silently, is a name they will later fail
    # to find (the same judgement ADR 0026 makes about `data (1).csv`).
    slug: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=4096)
    # `owner_user_id` is deliberately absent: the server assigns the authenticated
    # caller, exactly as it does for a session's `user_id`.


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4096)
    # `slug` is deliberately absent: it is fixed at creation because V2.1 card
    # references and V2.3 secret namespaces are built on it.
    status: Literal["active", "paused", "archived"] | None = None


class BindWorkspaceRequest(BaseModel):
    node_id: uuid.UUID
    path: str = Field(min_length=1, max_length=4096)
    label: str | None = Field(default=None, max_length=128)
    is_primary: bool = False


class ProjectWorkspaceDTO(BaseModel):
    """One binding, with whether it can be used *right now*.

    `usability` reuses the favourites vocabulary rather than defining a parallel one:
    the question is identical (can this stored path start a session on that node), and
    the browser already renders these four values.

    One limitation is honest rather than hidden: `usable` does not promise the
    directory still exists. Detecting that needs a `filesystem.*` round trip, and V2.0
    adds no protocol message — so a deleted directory surfaces when the session is
    created, exactly as it does for a path typed by hand.
    """

    id: uuid.UUID
    node_id: uuid.UUID
    node_name: str
    node_enabled: bool
    path: str
    label: str | None
    is_primary: bool
    usability: Usability
    created_at: datetime


class ProjectSummaryDTO(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    status: str
    owner_user_id: uuid.UUID
    owner_name: str
    # Counts, not stored columns: a stored count is a second source of truth for a
    # fact the rows already carry.
    workspace_count: int
    node_count: int
    active_session_count: int
    last_activity_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectDetailDTO(ProjectSummaryDTO):
    """The project page in one response.

    Deliberately not split into `GET /{id}` plus `GET /{id}/overview`: both would
    serve one screen, need the same action, and have no separate caching semantics —
    so the split would only cost the page a second round trip. `/activity` *is*
    separate, because it has its own pagination and the overview needs only its head.
    """

    workspaces: list[ProjectWorkspaceDTO]


class ActivityEventDTO(BaseModel):
    id: uuid.UUID
    kind: str
    occurred_at: datetime
    payload: dict[str, Any]
    # Both null together, never one without the other. Null means either a
    # system-originated event or a reader without `audit.view` — `actors_hidden` on
    # the page is what tells those two apart, and the UI must say so, because a blank
    # actor that silently means "you may not see this" reads as "nobody did it".
    actor_id: uuid.UUID | None
    actor_name: str | None
    session_id: uuid.UUID | None
    # Survives redaction: it says what *kind* of actor, never which one. Without it a
    # blank actor means three different things at once — the system, an agent, or a
    # person the reader may not be told about (ADR 0028 sec 3).
    actor_kind: str = "user"


class ActivityPageDTO(BaseModel):
    items: list[ActivityEventDTO]
    # Same field name as the dashboard's recent-activity block, so one component can
    # render the same sentence in both places.
    actors_hidden: bool
    next_before: str | None


# --- V2.1: the task layer (ADR 0028) --------------------------------------------


class GateDTO(BaseModel):
    key: str
    label: str
    order: int
    requires_human: bool
    enabled: bool
    # Set only when the gate is derived-disabled. A gate that is merely unapproved is
    # available, not disabled — and a disabled one always says why, because a gate
    # that quietly does not exist is worse than one that explains itself.
    disabled_reason: str | None


class ProcessDTO(BaseModel):
    """The process **as it applies here**, with the project's overrides already applied.

    `overrides` carries the raw switches beside the resolved definition rather than
    instead of it: the console renders the applied process, and the settings screen
    renders the switches, and letting the client apply the overrides itself would mean
    implementing the same rules twice (ADR 0033 §5).
    """

    key: str
    version: str
    source: str
    lanes: list[dict[str, Any]]
    readiness: list[dict[str, Any]]
    gates: list[GateDTO]
    templates: dict[str, Any]
    overrides: dict[str, Any] = Field(default_factory=dict)


class BoardCardDTO(BaseModel):
    """One card as the board renders it.

    **Deliberately without `acceptance_criteria` and without gate detail.** M1
    measured the full shape at 439 KB for 200 cards and over a megabyte at 500, while
    this shape is 74 KB and 180 KB (`plan/17/10-…md` §1). That measurement is what
    replaced pagination, so `test_the_board_card_stays_a_summary` pins it: the day
    someone adds one of those fields back "just for convenience", the board silently
    becomes the thing the measurement ruled out.
    """

    id: uuid.UUID
    card_ref: str
    title: str
    stage: str
    risk: str
    priority: str
    owner_user_id: uuid.UUID | None
    owner_name: str | None
    delivery: str
    blocking_count: int
    gates_approved_count: int
    active_run_status: str | None = None
    active_run_runner_name: str | None = None
    waiting_reason: str | None = None
    version: int
    updated_at: datetime


class BoardLaneDTO(BaseModel):
    stage: str
    label: str
    wip_suggested: int | None
    count: int
    cards: list[BoardCardDTO]


class BoardDTO(BaseModel):
    lanes: list[BoardLaneDTO]
    # Always false in V2.1. Present from the first release anyway: a field added later
    # forces every existing client to handle its absence, while one that is always
    # there makes a future move to paging a server-side change only.
    has_more: bool = False


class TaskDependencyDTO(BaseModel):
    id: uuid.UUID
    card_ref: str
    title: str
    stage: str


class TaskDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    card_ref: str
    title: str
    description: str | None
    objective: str | None
    scope: str | None
    non_goals: str | None
    stage: str
    risk: str
    priority: str
    owner_user_id: uuid.UUID | None
    epic_id: uuid.UUID | None
    user_story_id: uuid.UUID | None
    readiness: dict[str, Any]
    # `{gate_key: {approved_by, approved_at}}` — never a boolean, because that cell
    # is where "an agent's output is not an approval" lives (ADR 0028 sec 1).
    gates: dict[str, Any]
    acceptance_criteria: list[dict[str, Any]]
    links: dict[str, Any]
    required_labels: list[str]
    version: int
    # Declared, inert until V2.3/V2.4. The console labels this block accordingly:
    # a card that says `pull_request` produces no pull request in this phase.
    source: str
    repository_id: uuid.UUID | None
    base_branch: str | None
    delivery: str
    target_branch: str | None
    existing_pr_ref: str | None
    required_secrets: list[str]
    assigned_runner_id: uuid.UUID | None
    requirement_id: uuid.UUID | None
    proposal_id: uuid.UUID | None
    depends_on: list[TaskDependencyDTO]
    blocking_refs: list[str]
    # --- conversation projections (V2-C1, `CV-13`) --------------------------
    # Written this phase, read by the detail view now and by `beta.1`'s work-items
    # read model later. **Deliberately not on `BoardCardDTO`**: that shape has a pinned
    # size budget which replaced pagination, and the board's own badge is `beta.1`'s
    # work (`research/03` D48).
    conversation_seq: int = 0
    open_question_count: int = 0
    #: `human` | `agent` | null. Derived from question state, so a card gives the same
    #: answer whether the asking run is still polling or has already ended.
    waiting_for_actor: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskWriteDTO(BaseModel):
    """A card plus anything the platform wants to say without refusing.

    `warnings` is part of the success response rather than a log line: the Definition
    of Ready reports through it, and a report nobody surfaces is no report.
    """

    task: TaskDTO
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class CreateEpicRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8000)


class CreateUserStoryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    narrative: str | None = Field(default=None, max_length=8000)
    epic_id: uuid.UUID | None = None


class UpdateEpicRequest(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    order_index: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, min_length=1, max_length=16)


class UpdateUserStoryRequest(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, min_length=1, max_length=200)
    narrative: str | None = Field(default=None, max_length=8000)
    epic_id: uuid.UUID | None = None
    order_index: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, min_length=1, max_length=16)


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    objective: str | None = Field(default=None, max_length=4000)
    scope: str | None = Field(default=None, max_length=4000)
    non_goals: str | None = Field(default=None, max_length=4000)
    stage: str = "backlog"
    risk: str = "medium"
    priority: str = "normal"
    epic_id: uuid.UUID | None = None
    user_story_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    acceptance_criteria: list[dict[str, Any]] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, Any] = Field(default_factory=dict)
    required_labels: list[str] = Field(default_factory=list)
    source: str = "repo"
    delivery: str = "pull_request"
    base_branch: str | None = None
    target_branch: str | None = None


class UpdateTaskRequest(BaseModel):
    """A patch, and the version it was written against.

    `version` is required rather than optional: an optional precondition is one every
    caller eventually forgets, and the failure it prevents — two people dragging the
    same card — is silent.

    `model_extra` is refused rather than ignored, so a typo'd field name is an error
    the caller can see instead of a change they believe they made.
    """

    model_config = {"extra": "forbid"}

    version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    objective: str | None = None
    scope: str | None = None
    non_goals: str | None = None
    stage: str | None = None
    risk: str | None = None
    priority: str | None = None
    owner_user_id: uuid.UUID | None = None
    epic_id: uuid.UUID | None = None
    user_story_id: uuid.UUID | None = None
    readiness: dict[str, Any] | None = None
    acceptance_criteria: list[dict[str, Any]] | None = None
    links: dict[str, Any] | None = None
    required_labels: list[str] | None = None
    # V2.5. Correctable until the card has been run, and never by an agent — it is in
    # `AGENT_FORBIDDEN_FIELDS`, because a clarification run able to rewrite its own kind
    # would have lifted the "this kind carries no secret" refusal for the next dispatch.
    card_kind: str | None = None
    source: str | None = None
    delivery: str | None = None
    base_branch: str | None = None
    target_branch: str | None = None
    existing_pr_ref: str | None = None
    required_secrets: list[str] | None = None
    assigned_runner_id: uuid.UUID | None = None
    # The Done Gate's escape hatch (V2.4, ADR 0033 §5). Not a field on the card: the
    # two travel with the patch that moves the card, because forcing is a property of
    # *this move* rather than a state somebody sets beforehand.
    #
    # `verification_commands` is deliberately **not** here. It has its own endpoint
    # requiring `task.approve`, an action a run credential never holds — reachable
    # through this body it would be writable with `task.update`, which a run credential
    # does hold, and the agent being verified would choose what verifies it.
    force: bool = False
    force_reason: str | None = Field(default=None, max_length=2000)


class VerificationCommand(BaseModel):
    """One check, as **argv** rather than a shell string.

    A shell string is an injection path and it would sit on the platform's own storage
    surface. Both stores — the project's and the card's — use this same model, because
    two nearly identical validators drift the moment either is fixed (ADR 0033 §3b).

    The bounds exist to keep the assembled `spec.allowed_verification_commands` inside
    the ceiling contract 1.12.0 already set: 16 items of 256 characters. One encoded
    command is `origin\tname\targv…`, so 1 + 32 + 16x128 would not fit — hence 16 argv
    elements of 128, which encodes to ~241 characters in the worst realistic case, and
    the service measures the encoded length at save time rather than at send time.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=32)
    argv: list[str] = Field(min_length=1, max_length=16)


class VerificationCommandsRequest(BaseModel):
    model_config = {"extra": "forbid"}

    commands: list[VerificationCommand] = Field(default_factory=list, max_length=8)


class ProjectVerificationRequest(BaseModel):
    model_config = {"extra": "forbid"}

    commands: list[VerificationCommand] = Field(default_factory=list, max_length=8)
    require_project_verification: bool = False


class ProjectVerificationDTO(BaseModel):
    commands: list[dict[str, Any]]
    require_project_verification: bool


class ProcessOverridesRequest(BaseModel):
    """Enable/disable of existing items only — never new items, never new lanes.

    The narrowness is the point: cross-project metrics have to keep comparing like with
    like, and a store that accepts arbitrary keys is one somebody puts a custom
    readiness item into (ADR 0033 §5).
    """

    model_config = {"extra": "forbid"}

    readiness_disabled: list[str] = Field(default_factory=list, max_length=32)
    gates_disabled: list[str] = Field(default_factory=list, max_length=32)
    wip: dict[str, int] = Field(default_factory=dict)


class ExecutionPlanDTO(BaseModel):
    """One version of a plan. There is no update DTO, because there is no update."""

    id: uuid.UUID
    seq: int
    note: str | None
    steps: list[dict[str, Any]]
    run_id: uuid.UUID | None
    created_by_kind: str
    created_at: datetime


class RecordPlanRequest(BaseModel):
    model_config = {"extra": "forbid"}

    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class VerificationReportDTO(BaseModel):
    """A report **with its provenance**, which is the point of the type.

    `source` is what the server decided from the write path, never what the payload
    asked for. The console renders the three levels differently and names the weakest
    one in words, because a qualifier nobody reads is not a qualifier (ADR 0033 §3b).
    """

    id: uuid.UUID
    result: str
    checks: list[dict[str, Any]]
    acceptance_criteria: list[dict[str, Any]]
    remaining_risks: list[dict[str, Any]]
    completion_summary: str | None
    source: str
    run_id: uuid.UUID | None
    reported_by_kind: str
    reported_at: datetime


class SubmitVerificationRequest(BaseModel):
    """`source` is accepted and **discarded**, which is deliberate.

    Refusing the field would tell a caller it exists and matters; accepting and ignoring
    it — while recording that it was ignored — makes the attempt visible without making
    it useful.
    """

    model_config = {"extra": "forbid"}

    result: str
    checks: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    acceptance_criteria: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    remaining_risks: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    completion_summary: str | None = Field(default=None, max_length=8000)
    source: str | None = None


class EvidenceItemDTO(BaseModel):
    id: uuid.UUID
    kind: str
    source: str
    payload: dict[str, Any]
    run_id: uuid.UUID | None
    written_by_kind: str
    collected_at: datetime


class AddEvidenceRequest(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AddDependencyRequest(BaseModel):
    depends_on_task_id: uuid.UUID


class GateDecisionRequest(BaseModel):
    approved: bool = True


class RoadmapTaskDTO(BaseModel):
    id: uuid.UUID
    card_ref: str
    title: str
    stage: str


class RoadmapStoryDTO(BaseModel):
    id: uuid.UUID
    card_ref: str
    title: str
    done_count: int
    total_count: int
    tasks: list[RoadmapTaskDTO]


class RoadmapEpicDTO(BaseModel):
    id: uuid.UUID
    card_ref: str
    title: str
    done_count: int
    total_count: int
    stories: list[RoadmapStoryDTO]
    # Cards filed under this epic but under no story. Monstrare's semantics, kept
    # deliberately: a card must never disappear because of how it was filed (D4).
    unclassified: list[RoadmapTaskDTO]


class RoadmapDTO(BaseModel):
    epics: list[RoadmapEpicDTO]
    # Stories with no epic, and — in `unclassified` — cards with neither.
    orphan_stories: list[RoadmapStoryDTO]
    unclassified: list[RoadmapTaskDTO]
    done_count: int
    total_count: int


# --- V2.1: requirements, specs and proposals (TK-05, D28) ------------------------


class FeatureSpecDTO(BaseModel):
    id: uuid.UUID
    seq: int
    objective: str | None
    scope: str | None
    non_goals: str | None
    acceptance_criteria: list[dict[str, Any]]
    # `[{id, question, answer, resolved_as}]`. An entry with neither an answer nor an
    # explicit `resolved_as` blocks approval — a known unknown is recorded, not
    # pretended away.
    open_questions: list[dict[str, Any]]
    # The nine sections Monstrare's specification template has and V2.1's five columns
    # did not (ADR 0034 §7). `user_stories` is the one a decomposition reads.
    sections: dict[str, Any]
    authored_by_kind: str
    authored_by: uuid.UUID | None
    # Which run wrote this version, when one did. Lets the review screen say "the second
    # clarification run wrote this" and link to its log, rather than "some machine".
    run_id: uuid.UUID | None
    created_at: datetime


class RequirementSummaryDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    card_ref: str
    raw_text: str
    status: str
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    spec_count: int
    created_at: datetime
    updated_at: datetime


class TaskProposalDTO(BaseModel):
    id: uuid.UUID
    seq: int
    spec_id: uuid.UUID | None
    tree: dict[str, Any]
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    run_id: uuid.UUID | None
    created_at: datetime
    # Which tree items already became cards, and which are still available. **Two
    # fields, not one plus arithmetic in the browser**: partial acceptance leaves the
    # rest *available* rather than declined, and a screen that cannot tell those apart
    # makes people think the decision was already made (ADR 0034 §6).
    accepted_item_ids: list[str] = Field(default_factory=list)
    remaining_item_ids: list[str] = Field(default_factory=list)


class RequirementDetailDTO(RequirementSummaryDTO):
    specs: list[FeatureSpecDTO]
    proposals: list[TaskProposalDTO]
    # Which questions currently block approval. Sent with the requirement so the
    # review screen can disable the button *and say why* in one response — a silently
    # disabled control is the thing FR-TASK-005.AC-03 exists to prevent.
    blocking_questions: list[str]


class CreateRequirementRequest(BaseModel):
    """Intake. One field, deliberately.

    The flow begins with someone saying what they want in their own words; a form with
    ten required fields at that moment is how it stops being used.
    """

    raw_text: str = Field(min_length=1, max_length=8000)


class CreateSpecRequest(BaseModel):
    objective: str | None = Field(default=None, max_length=8000)
    scope: str | None = Field(default=None, max_length=8000)
    non_goals: str | None = Field(default=None, max_length=8000)
    acceptance_criteria: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    # Keys are checked in the service against a closed set, not here: the refusal has to
    # name the unknown section, and one shared implementation serves both the human and
    # the agent route.
    sections: dict[str, Any] = Field(default_factory=dict)


class CreateProposalRequest(BaseModel):
    """The proposed tree. `{"tasks": [ … ]}` in V2.1; epics and stories join in V2.5."""

    tree: dict[str, Any]


class AcceptProposalRequest(BaseModel):
    # `None` means "all of them". Partial acceptance is the normal case, so the field
    # selects rather than confirms.
    accept_ids: list[str] | None = None
    note: str | None = Field(default=None, max_length=2000)
    # "Edit then create", the fourth decision `version2.md` §7.7 names and V2.1 did not
    # implement. Keyed by tree item id; the service refuses a key that is not being
    # accepted, and refuses `readiness` outright.
    overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class RejectProposalRequest(BaseModel):
    """A reason, required.

    A rejection with no reason produces a row indistinguishable from no row, and this is
    the only signal that accumulates on this path — the next decomposition receives it.
    """

    note: str = Field(min_length=1, max_length=2000)


class AcceptProposalResultDTO(BaseModel):
    created: list[TaskDTO]
    # card_ref -> the readiness items it lacked. A card that landed in `backlog`
    # instead of `ready` has to say why, on the same screen (FR-TASK-005.AC-06).
    incomplete: dict[str, list[str]]
    # card_ref -> tree item ids it depended on that were not accepted, so no dependency
    # row exists. Reported rather than dropped: a card claiming `dependencies_known`
    # while the database holds none is the failure this prevents (FR-SPEC-005.AC-04).
    unresolved_dependencies: dict[str, list[str]] = Field(default_factory=dict)


# --- V2.5 document patch proposals (FR-SPEC-007) ----------------------------


class DocumentPatchProposalDTO(BaseModel):
    """A proposed document edit, as the console renders it.

    `diff` travels as text and the console renders it as text. It is agent-produced
    content arriving in a single-origin deployment (ADR 0020), so nothing on this path
    may parse it as markup — and there is deliberately no download route, because a
    downloadable `.patch` relocates the applying step to a terminal where none of this
    phase's gates exist.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    requirement_id: uuid.UUID | None
    run_id: uuid.UUID | None
    seq: int
    target_path: str
    diff: str
    sections: dict[str, Any]
    reason: str | None
    related_task_ids: list[str]
    open_questions: list[dict[str, Any]]
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class CreatePatchProposalRequest(BaseModel):
    target_path: str = Field(min_length=1, max_length=512)
    diff: str = Field(min_length=1)
    sections: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=8000)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)


class DecidePatchProposalRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


# --- V2.2 agent runner (ADR 0029/0030/0031) ---------------------------------


class AgentRunnerDTO(BaseModel):
    """A runner as the console sees it.

    `online`, `active_runs` and `waiting_runs` are **derived**, not columns: a runner
    is online exactly when its node is, and storing a second copy of that is storing
    something that can go stale (ADR 0029 sec 1).
    """

    id: uuid.UUID
    node_id: uuid.UUID
    node_name: str
    name: str
    runtimes: list[str]
    # **Matched from V2.3**, as a superset: a card reaches this runner when its
    # `required_labels` are a subset of these. Read-only — the node's config declares
    # them (ADR 0029 amendment B5) — and the console must not draw them as a security
    # control: a tag decides which machine, never which machine may hold a secret.
    labels: list[str]
    # The two node-side declarations, also read-only. `run_untagged` false reserves the
    # machine for tagged work; `accept_secrets` false keeps it away from cards that
    # declare secrets.
    run_untagged: bool
    accept_secrets: bool
    max_concurrent: int
    max_waiting: int
    enabled: bool
    # `len(workspace.allowed_roots) == 0` on the node, as **reported** by the daemon.
    # False means the machine also serves interactive sessions, and an agent running
    # there can read those directories — the platform does not prevent that and says
    # so (ADR 0031 sec 6).
    dedicated: bool
    online: bool
    active_runs: int
    waiting_runs: int
    # Cards pinned to this runner, whether or not any of them has ever run. Shows an
    # over-subscribed machine that occupancy alone makes look idle.
    assigned_cards: int
    # Why the runner stopped polling, as it last reported. **Not** an online flag: a
    # runner expresses "no capacity" by going quiet, so without this a full runner and
    # a dead machine are the same silence — and the console would show a perfectly
    # healthy node as offline (exit condition 21). Null means it never said.
    blocked_reason: str | None
    disk_used_bytes: int | None
    disk_quota_bytes: int | None
    registered_at: datetime
    last_registered_at: datetime | None


class UpdateAgentRequest(BaseModel):
    """`runtimes` and `dedicated` are deliberately absent: they are the daemon's report
    about the machine, and a field an administrator can type would make the console
    display the posture somebody wished for (ADR 0023 D3).

    **`labels`, `run_untagged` and `accept_secrets` are absent for the same reason, and
    from V2.3 the reason is stronger.** They now decide which machine gets which card
    and which machine may hold a secret, so an edit here would be a second source of
    truth that the node's next `runner.register` silently overwrites. Changing them
    means changing that machine's config file (ADR 0029 amendment B5)."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    max_concurrent: int | None = Field(default=None, ge=0, le=64)
    max_waiting: int | None = Field(default=None, ge=0, le=64)


# The closed set of kinds, named once so the DTO, the create request and the route
# helper cannot drift apart.
SecretKind = Literal["env", "git_pat", "git_ssh_key", "provider_token"]


class ProjectSecretDTO(BaseModel):
    """A secret's metadata. **There is no field for the value, and there never will be.**

    Also absent, and each for its own reason: a **fingerprint** answers "is this the one
    I rotated last week", which `rotated_at` already answers without disclosing anything;
    a **length** is a side channel, because a 93-character value is almost certainly a
    fine-grained PAT (ADR 0032 §2 rule 8).
    """

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: SecretKind
    created_by: uuid.UUID | None
    created_at: datetime
    rotated_at: datetime | None
    # The most useful column on the page: it is how somebody tells a live credential
    # from one nothing has touched since it was created.
    last_used_at: datetime | None


class CreateProjectSecretRequest(BaseModel):
    # Bounded here as well as in the envelope module, so an oversized body is refused
    # before it is encrypted rather than after.
    name: str = Field(min_length=1, max_length=128)
    kind: SecretKind
    value: str = Field(min_length=1, max_length=8192)


class RotateProjectSecretRequest(BaseModel):
    """Only the value. Name and kind are immutable — see `SecretService.rotate`."""

    value: str = Field(min_length=1, max_length=8192)


class ProjectRepositoryDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    scheme: str
    host: str
    path: str
    default_branch: str
    label: str | None
    # Assembled from the three fields for display. There is no stored URL anywhere,
    # which is what makes a credential in one impossible rather than filtered.
    url: str
    created_at: datetime


class CreateRepositoryRequest(BaseModel):
    """Three fields, **never a URL**.

    An endpoint that accepted a URL would receive `https://user:token@host/…` on its
    first day, and that token would then live in the database, in `git remote -v`, in
    the reflog and in error messages. Split like this, userinfo cannot be expressed
    (ADR 0031 sec 5). An OpenAPI assertion in AR-12 pins the absence of a `url` field.
    """

    scheme: Literal["https", "ssh"]
    host: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=512)
    default_branch: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=128)


class DispatchRequest(BaseModel):
    # Absent means "any eligible runner", which is the default. Naming one makes it a
    # `WHERE` clause in that runner's own poll query — never a push (ADR 0029 sec 3).
    assigned_runner_id: uuid.UUID | None = None


class DispatchResponseDTO(BaseModel):
    run_id: uuid.UUID
    status: str
    # "any" | "assigned_offline" | "no_eligible_runner". Computed on the server because
    # it needs the eligibility rules; the three pieces of UI copy behind it must differ
    # word for word, or a person cannot tell "I misconfigured this" from "wait".
    waiting_reason: str
    # Which tags nothing online has, when that is why nobody claimed it. **The smallest
    # missing set across the online runners**, not the intersection: what the reader has
    # to do is make one machine eligible, and the minimum answers that directly
    # (exit condition 3e). Empty for the other two reasons.
    missing_tags: list[str] = []
    # Named only for `assigned_offline`, so the copy can say which machine.
    runner_name: str | None = None


class TaskRunDTO(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    seq: int
    status: str
    attempt: int
    runner_id: uuid.UUID | None
    runner_name: str | None
    assigned_runner_id: uuid.UUID | None
    runtime: str | None
    source_kind: str | None
    source_ref: str | None
    # Which version of the code this run actually executed. Reported by the runner
    # once the worktree exists.
    commit_sha: str | None
    disk_bytes: int | None
    queued_at: datetime
    claimed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    # "is the child making progress", as opposed to the lease's "is the runner alive".
    last_event_at: datetime | None
    result: str | None
    error_code: str | None
    summary: str | None
    log_bytes: int
    log_truncated_bytes: int
    # **The card's declaration, not a per-run snapshot** — and the difference is stated
    # rather than papered over. The authoritative record of what was actually handed to
    # which machine is the `secret.deliver` audit row; this is what the card asked for,
    # which is what a reader of the run page is trying to see. Names only: there is no
    # version of this field that could carry a value.
    secret_names: list[str] = []


class RunLogLineDTO(BaseModel):
    seq: int
    # The stored segment, returned **unparsed**. The event schema belongs to a
    # third-party CLI and changes with its version; parsing it here would make that
    # schema part of our API (plan/18/06-…md §2.1).
    data: str
    truncated: bool
    received_at: datetime


class RunLogPageDTO(BaseModel):
    lines: list[RunLogLineDTO]
    next_after_seq: int | None
    log_bytes: int
    truncated_bytes: int


class TaskMessageDTO(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    run_id: uuid.UUID | None
    # Monotonic and gapless within the card. The client's cursor, and the key it merges
    # new messages on — which is why it is not derivable from the list's position.
    conversation_seq: int
    author_kind: str
    author_user_id: uuid.UUID | None
    author_name: str | None
    author_runner_id: uuid.UUID | None
    # The runner's name, so a reader sees `runner-03` rather than a uuid. A run token
    # never produces a message attributed to a person (ADR 0037 §1).
    author_runner_name: str | None = None
    body: str
    # Six values, with the two V2.5 spellings mapped on read (ADR 0035 §8).
    kind: str
    event_kind: str | None
    reply_to_message_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    # Denormalised so the thread can render a question card without a second request.
    question_state: str | None = None
    created_at: datetime


class MessagePageDTO(BaseModel):
    """A page of the thread.

    Replaces the bare array this route used to return. That is the one breaking API
    change in V2-C1, taken rather than adding a permanent `?paged=` flag because both
    consumers are in this repository and both change in the same phase
    (`GATE-CV-NO-THIRD-CONSUMER` asserts that premise rather than assuming it).
    """

    items: list[TaskMessageDTO]
    next_after_seq: int | None
    # Present from the first release for the same reason `BoardDTO.has_more` was: a
    # field added later forces every existing client to handle its absence.
    has_more: bool


class TaskQuestionDTO(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    run_id: uuid.UUID | None
    asked_message_id: uuid.UUID
    state: str
    answered_message_id: uuid.UUID | None
    created_at: datetime
    answered_at: datetime | None
    expired_at: datetime | None


class PostMessageRequest(BaseModel):
    # 24000 rather than 20000: the service refuses at 20000 with `MESSAGE_TOO_LARGE`,
    # and a Pydantic bound at the same number would return a 422 with no machine code
    # instead — which a client cannot tell from any other validation failure
    # (ADR 0041 §3). The looser bound still stops an unbounded body reaching the
    # service.
    body: str = Field(min_length=1, max_length=24000)
    # `question` parks the run and makes the card say "waiting for your reply".
    # `message` and `event` are the V2.5 spellings, still accepted on write and
    # normalised to `comment` and `system`.
    kind: Literal["comment", "question", "answer", "proposal", "decision", "message"] = "comment"
    reply_to_message_id: uuid.UUID | None = None
    #: Same key + same content replays the original message with 200; same key +
    #: different content is a 409 (ADR 0036 §3).
    idempotency_key: str | None = Field(default=None, max_length=128)


class AnswerQuestionRequest(BaseModel):
    body: str = Field(min_length=1, max_length=24000)
    #: False writes the answer and closes the question without waking an agent — the
    #: difference between "留言" and "回覆並繼續" (ADR 0035 §8).
    resume: bool = True
    idempotency_key: str | None = Field(default=None, max_length=128)


class AnswerResultDTO(BaseModel):
    message: TaskMessageDTO
    question: TaskQuestionDTO
    #: `new_turn` | `live_run` | `no_run` | `none`. The interface needs to distinguish
    #: "a new round is queued" from "the running agent will read this on its next poll".
    mode: str
    continuation_run_id: uuid.UUID | None
    #: Present when `mode` is `refused`: the machine code that stopped the continuation.
    #: The answer was still written — that is why this is a field rather than an error.
    refusal_code: str | None = None


class ConversationInputDTO(BaseModel):
    """What one turn is being asked to read (ADR 0036 §2)."""

    messages: list[TaskMessageDTO]
    open_questions: list[TaskQuestionDTO]
    from_seq: int
    to_seq: int
    has_more: bool


class ConversationAckRequest(BaseModel):
    seq: int = Field(ge=0)


class ConversationCursorDTO(BaseModel):
    task_id: uuid.UUID
    last_delivered_seq: int
    last_acked_seq: int


class TaskArtifactDTO(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    run_id: uuid.UUID | None
    message_id: uuid.UUID | None
    filename: str
    # Determined by the server, never taken from the uploader. This field is the
    # primary stored-XSS entry point in the phase (ADR 0030 Part B).
    content_type: str
    size: int
    sha256: str
    uploaded_by_kind: str
    uploaded_by_user_id: uuid.UUID | None
    uploaded_by_runner_id: uuid.UUID | None
    created_at: datetime
    # A deleted artifact keeps its row and loses its bytes. The console shows it as a
    # grey line rather than removing it — the same rule the activity timeline follows,
    # and the reason a reason is required in the first place.
    deleted_at: datetime | None
    delete_reason: str | None
    # Whether `/preview` exists for this one. Computed rather than stored, because the
    # allowlist is a property of the code and not of the row.
    previewable: bool


class DeleteArtifactRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
