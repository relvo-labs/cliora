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

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role.name,
            permissions=sorted(role_actions(user)),
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
        )


class SessionDetail(SessionSummary):
    exit_code: int | None = None
    error_message: str | None = None

    @classmethod
    def from_model(cls, s: TerminalSession, *, viewer: User) -> SessionDetail:
        base = SessionSummary.from_model(s, viewer=viewer)
        return cls(**base.model_dump(), exit_code=s.exit_code, error_message=s.error_message)


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
