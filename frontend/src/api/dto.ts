// TypeScript mirrors of the backend response models (backend/app/api/http/schemas.py).
// These names and value spaces are the wire contract; keep them in lockstep with
// the Pydantic models. Timestamps are RFC 3339 UTC strings.

export type NodeStatus = "online" | "degraded" | "offline" | "disabled";
export type RuntimeId = "claude" | "codex";
export type EnrollmentTokenStatus =
  | "active"
  | "expired"
  | "exhausted"
  | "revoked";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: string;
  permissions: string[];
  /** What this *deployment* has. **Not a permission** — `hasPermission` answers
   *  that, and the server checks both independently. The UI rule is
   *  `hasFeature(...) && hasPermission(...)`; neither alone is authorization.
   *
   *  It cannot live in `permissions`: seed migrations run unconditionally, so an
   *  Admin holds `project.manage` even where the project layer is switched off. */
  features: string[];
}

/** Feature keys carried by `User.features` (ADR 0027). V2.2 adds `agent_runs`. */
export const FEATURE_PROJECTS = "projects";
// The inner of the two flags: present only when the project layer is on as well,
// because the runner layer is nested inside it (ADR 0029).
export const FEATURE_AGENT_RUNS = "agent_runs";

export interface LoginResponse {
  tokens: TokenPair;
  user: User;
}

export interface NodeRuntime {
  runtime: string;
  available: boolean;
  version: string | null;
  binary_path: string | null;
  checked_at: string | null;
  // True when this runtime is launched on the node with its sandbox and approval
  // prompts disabled (ADR 0023). Measured on the node, not requested from here —
  // the console has no way to ask for either posture.
  sandbox_bypass: boolean;
}

export interface NodeWorkspaceRoot {
  path: string;
  display_name: string | null;
  is_enabled: boolean;
}

export interface NodeSummary {
  id: string;
  name: string;
  hostname: string;
  status: NodeStatus;
  os: string | null;
  architecture: string | null;
  claude_available: boolean;
  codex_available: boolean;
  session_count: number;
  last_seen_at: string | null;
}

// A live resource sample taken from the last heartbeat. Every field mirrors
// contracts/v1/schemas/messages/node-heartbeat.schema.json (single numbers,
// minimum 0); load_average is the system load, not a per-interval array. The
// whole object is null when the node is offline or has no heartbeat data yet.
export interface NodeResources {
  cpu_usage: number | null;
  memory_usage: number | null;
  load_average: number | null;
  disk_usage: number | null;
  daemon_uptime: number | null;
}

// What version a node is on, what it could be on, and what happened the last time
// it was asked to change (P4-10).
export type NodeUpdateState =
  | "in_progress"
  | "succeeded"
  | "failed"
  | "rolled_back"
  | "unknown";

export interface NodeUpdateStatus {
  current_version: string | null;
  // The newest allowlisted release. Null when nothing is published — not an error,
  // just nothing to offer.
  latest_version: string | null;
  // Null means this node has never been asked to update, which is a different fact
  // from `succeeded`.
  status: NodeUpdateState | null;
  target_version: string | null;
  // A stable `UPDATE_*` code, or "succeeded". Never a daemon error string.
  last_result: string | null;
  updated_at: string | null;
  // Still false: MVP updates are explicitly triggered, never scheduled (ADR 0017).
  auto_update_enabled: boolean;
}

// The only thing a client may say about an update. Deliberately not a URL, a
// filename or a digest: the daemon derives those from the release manifest and its
// own config, so a client that could name a binary could name any binary (SEC-002).
export interface UpdateNodeInput {
  target_version: string;
  allow_downgrade?: boolean;
}

export interface ReleaseArtifact {
  version: string;
  architecture: string;
  filename: string;
  sha256: string;
  size: number;
}

export interface ReleaseManifest {
  latest: string | null;
  artifacts: ReleaseArtifact[];
  generated_at: string;
}

export interface NodeRecentError {
  // RFC 3339 UTC instant; localized for display with a full-instant tooltip.
  occurred_at: string;
  message: string;
}

export interface NodeDetail extends NodeSummary {
  os_version: string | null;
  daemon_version: string | null;
  run_user: string | null;
  // True when this node's system terminal can reach root through sudo (ADR 0023).
  // Reported by the node; there is no endpoint that sets it.
  privileged_terminal: boolean;
  // Whether this node accepts image drop. Absent-means-no on the wire, so a
  // daemon that predates the field reads as false and the console hides the
  // affordance rather than offering one that fails (ADR 0024 W4).
  image_upload: boolean;
  // Whether this node accepts general file upload — an arbitrary file at a
  // user-chosen path (ADR 0026 §9). A second flag rather than a widening of the
  // first: the terminal's paste affordance is gated on `image_upload` and the file
  // tree's drop target on this one, and a machine may allow one without the other.
  file_upload: boolean;
  is_enabled: boolean;
  registered_at: string;
  runtimes: NodeRuntime[];
  workspace_roots: NodeWorkspaceRoot[];
  resources: NodeResources | null;
  update_status: NodeUpdateStatus;
  recent_errors: NodeRecentError[];
}

export interface EnrollmentToken {
  id: string;
  created_by: string;
  created_at: string;
  expires_at: string;
  max_uses: number;
  used_count: number;
  status: EnrollmentTokenStatus;
}

export interface EnrollmentTokenCreated {
  id: string;
  // Plaintext returned exactly once, at creation.
  token: string;
  expires_at: string;
  max_uses: number;
}

export type SessionStatus =
  | "starting"
  | "running"
  | "disconnected"
  | "exited"
  | "failed"
  | "terminating"
  | "terminated";

// What the signed-in user may do to one session, computed by the server from the
// role *and* the ownership rules (ADR 0016). The browser renders these flags and
// must never re-derive them: a role check alone would show a "Terminate" button
// on a colleague's session that the server refuses. Hiding a control is a
// courtesy, not the authorization — the server denies it either way.
export interface SessionCapabilities {
  can_view: boolean;
  can_write: boolean;
  can_takeover: boolean;
  can_terminate: boolean;
  can_browse_files: boolean;
  can_upload_files: boolean;
  // Already folds in the action, ownership and the node's own veto: the browser
  // renders it, it does not recombine it (ADR 0016/0021).
  can_open_shell: boolean;
}

export interface SessionSummary {
  id: string;
  node_id: string;
  user_id: string;
  name: string;
  runtime: string;
  workspace: string;
  status: SessionStatus;
  rows: number;
  columns: number;
  pid: number | null;
  started_at: string | null;
  last_activity_at: string | null;
  ended_at: string | null;
  created_at: string;
  capabilities: SessionCapabilities;
  /** `null` for an ad-hoc session, and for every session where the project layer
   *  is switched off. Always present, so the shape does not depend on config. */
  project_id: string | null;
  task_id: string | null;
}

export interface SessionDetail extends SessionSummary {
  exit_code: number | null;
  error_message: string | null;
  context_projection: "pending" | "ok" | "failed" | "node_unsupported" | null;
  context_projection_detail: string | null;
}

export interface CreateSessionInput {
  node_id: string;
  runtime: string;
  name: string;
  workspace: string;
  rows?: number;
  columns?: number;
  project_id?: string;
  /** Optional, and permanently so. Requires `project_id`: a card belongs to a
   *  project, and the platform never infers one from the other (FR-TASK-006). */
  task_id?: string;
}

export interface AttachTicket {
  session_id: string;
  ticket: string;
}

// --- P3 workspace files (read-only) ---
// Shapes come from the daemon filesystem.* response payloads relayed verbatim by
// Central (daemon/internal/connection/files_handlers.go). Paths are always
// workspace-relative: no server absolute path ever crosses this boundary.

export type FileEntryType = "directory" | "file" | "symlink";

export interface FileEntry {
  name: string;
  rel_path: string;
  type: FileEntryType;
  size: number;
  modified_at: string;
  hidden: boolean;
  symlink: boolean;
  // An excluded directory (node_modules, .venv, …) is listed but not loadable.
  excluded: boolean;
  expandable: boolean;
}

export interface FileTreePage {
  path: string;
  entries: FileEntry[];
  truncated: boolean;
  next_cursor?: string;
}

export interface FileSearchHit {
  name: string;
  rel_path: string;
  type: FileEntryType;
  modified_at: string;
}

// Why the daemon stopped a bounded filename walk early (ADR 0015).
export type FileSearchStopReason = "depth" | "results" | "scanned" | "timeout";

export interface FileSearchResult {
  results: FileSearchHit[];
  partial: boolean;
  stopped_reason?: FileSearchStopReason;
  scanned_count: number;
}

// A preview denial arrives in-band with success:false (HTTP 200) so the browser
// can render a specific "cannot preview" pane. error.reason is a coarse
// classification (dotenv/private_key/binary/…), never a content fragment.
// One dropped image, as the daemon stored it (ADR 0024). `path` is
// workspace-relative and daemon-chosen — the browser never sent a name.
export interface FileUploadResult {
  path: string;
  mime: string;
  size: number;
  modified_at: string;
}

// The response to a general file upload (ADR 0026). No `mime`: this path does not
// judge content type, so there is nothing honest to put there.
export interface FileStoreResult {
  path: string;
  size: number;
  modified_at: string;
}

export interface FileContent {
  success: boolean;
  rel_path: string;
  size?: number;
  modified_at?: string;
  encoding?: string;
  language_hint?: string;
  content?: string;
  mime?: string;
  error?: { code: string; reason?: string };
}

// --- P4 dashboard aggregates (backend/app/services/dashboard.py) ---
// Every block is fetched independently and carries its own status and fetch time.
// `generated_at` is when the data was *fetched*, not when the request was served:
// a cached value must be visible as one, so the UI shows the age rather than
// implying every number is live.
//
// A block that could not be loaded is always {status:"degraded", data:null,
// error_code}. That is the one uniform shape on this endpoint, and it is what lets
// one card say "temporarily unavailable" while the others show real numbers.

export type DashboardBlockStatus = "ok" | "stale" | "degraded";

export interface DashboardBlock<T> {
  status: DashboardBlockStatus;
  generated_at: string;
  data: T | null;
  error_code: string | null;
}

export interface DashboardNodeCounts {
  online: number;
  degraded: number;
  offline: number;
  disabled: number;
  total: number;
}

export interface DashboardSessionCounts {
  starting: number;
  running: number;
  disconnected: number;
  terminating: number;
  total_active: number;
  // Only runtimes that actually have active sessions. A zero entry would be
  // indistinguishable from a runtime that does not exist.
  per_runtime: Record<string, number>;
}

export interface DashboardRuntimeAvailability {
  available: number;
  unavailable: number;
  // Nodes that have never reported this runtime. Silence is not a negative:
  // folding it into `unavailable` would show a fresh fleet as broken.
  unknown: number;
  checked_at: string | null;
}

export interface DashboardRuntimes {
  runtimes: Record<string, DashboardRuntimeAvailability>;
  eligible_nodes: number;
}

// `nodes` is how many nodes reported this measurement, not the fleet size. When it
// is 0 there is no data — the UI must say so and never render it as 0%.
export interface DashboardMeasurement {
  average: number | null;
  maximum: number | null;
  nodes: number;
}

export interface DashboardResources {
  measurements: Record<string, DashboardMeasurement>;
  sampled_nodes: number;
  latest_sample_at: string | null;
  window_seconds: number;
}

export interface DashboardActivityItem {
  id: string;
  action: string;
  created_at: string;
  // Null for a system/daemon event, and also for every event when the viewer
  // lacks `audit.view` — see `actors_hidden`.
  actor_id: string | null;
  actor_name: string | null;
  node_id: string | null;
  node_name: string | null;
}

export interface DashboardActivity {
  items: DashboardActivityItem[];
  limit: number;
  // True when actor identity was withheld for this viewer, so the UI can say the
  // column is hidden rather than imply the events had no actor.
  actors_hidden?: boolean;
}

export type UnhealthyReason =
  | "offline_but_enabled"
  | "heartbeat_degraded"
  | "no_runtime_available"
  | "recent_session_failure";

export interface UnhealthyNode {
  id: string;
  name: string;
  status: NodeStatus;
  reasons: UnhealthyReason[];
  last_seen_at: string | null;
}

export interface DashboardUnhealthyNodes {
  items: UnhealthyNode[];
  // The count before truncation, so "10 of 37" is honest instead of implying the
  // list is complete.
  total: number;
  limit: number;
}

export interface DashboardSummary {
  generated_at: string;
  blocks: {
    nodes: DashboardBlock<DashboardNodeCounts>;
    sessions: DashboardBlock<DashboardSessionCounts>;
    runtimes: DashboardBlock<DashboardRuntimes>;
    resources: DashboardBlock<DashboardResources>;
    recent_activity: DashboardBlock<DashboardActivity>;
    unhealthy_nodes: DashboardBlock<DashboardUnhealthyNodes>;
  };
}

// --- P4 audit trail (read-only, Admin) ---
// Shapes mirror backend/app/api/http/schemas.py (AuditItemDTO / AuditPageDTO).
// `actor` and `node` are null when the row has no such resource *or* when the id
// no longer resolves: the audit table stores ids without a foreign key so history
// survives deletion, and a name that cannot be resolved is reported as null
// rather than dropping the row.

export interface AuditActor {
  id: string;
  username: string | null;
  display_name: string | null;
}

export interface AuditNodeRef {
  id: string;
  name: string | null;
}

export interface AuditItem {
  id: string;
  action: string;
  created_at: string;
  actor: AuditActor | null;
  node: AuditNodeRef | null;
  session_id: string | null;
  // Correlates the entry with that request's server logs; null for daemon or
  // system-initiated events.
  request_id: string | null;
  // Already minimized on write and re-filtered on read. Never contains terminal
  // bytes, file content, secrets or absolute paths.
  metadata: Record<string, unknown>;
}

export interface AuditPage {
  items: AuditItem[];
  // Null when the window is exhausted. There is deliberately no total count —
  // the UI shows how many rows it has loaded and never invents a total.
  next_cursor: string | null;
}

export interface AuditQuery {
  action?: string[];
  user_id?: string;
  node_id?: string;
  session_id?: string;
  from?: string;
  to?: string;
  limit?: number;
  cursor?: string;
}

// The closed action vocabulary (backend/app/services/audit.py ALL_ACTIONS). The
// filter offers exactly these: the server answers 422 for anything else, so an
// input that allowed free text would only produce failed queries. Kept in
// lockstep by test_audit_actions_match_the_frontend_constants.
export const AUDIT_ACTIONS = [
  "authz.denied",
  "credential.revoke",
  "credential.rotate",
  "daemon.update_result",
  "daemon.update_started",
  "enrollment.create",
  "enrollment.revoke",
  "enrollment.use",
  "file.sensitive_read_denied",
  "file.upload",
  "node.disable",
  "node.enable",
  "node.register",
  "node.remove",
  "session.attach",
  "session.create",
  "session.failed",
  "session.takeover",
  "session.terminate",
  "user.login",
  "user.login_failed",
  "user.logout",
  // 埠轉發整合（ADR 0022）。整合層與隧道層是不同的問題：「誰決定本組織使用這個服務、
  // 用誰的帳號」與「誰把哪台機器的哪個 port 對外」；隧道層的動作與 TunnelService 一起落地。
  "integration.enable",
  "integration.disable",
  "integration.credential_set",
  "integration.node_settings_updated",
  "tunnel.create",
  "tunnel.close",
  "tunnel.public_acknowledged",
  "node.posture_changed",
  // 專案層（ADR 0027）。`project.archive` 與 `project.update` 分開，理由與
  // `node.enable`／`node.disable` 分開相同：「誰封存了那個專案」是一個會被單獨問的
  // 問題，而在另一個動作的 metadata 裡過濾不是答案。綁定與解綁同理。
  "project.create",
  "project.update",
  "project.archive",
  "project.workspace_bind",
  "project.workspace_unbind",
  // 任務層（ADR 0028）。三個動作而不是一個：「建了一張卡」「改了一張卡」「核准了一個
  // 審查關卡」是分開被問的問題，而第三個正是稽核最常來找的那一個——在合併後的動作
  // metadata 裡過濾不是答案。
  "task.create",
  "task.update",
  "task.gate_approve",
  "requirement.create",
  "requirement.approve",
  "requirement.proposal_accept",
  "session_token.issue",
  "session_token.revoke",
  "session.context_project",
  // Agent Runner（ADR 0029）。派工與取消不併進 `task.update`：掛上佇列會在一台機器上
  // clone 一個 repo 並跑一個程序，與改一個欄位不是同一個量級，而稽核要分得出來。
  "agent.register",
  "agent.update",
  "run.dispatch",
  "run.cancel",
  "run_token.issue",
  "run_token.revoke",
  "artifact.upload",
  "artifact.delete",
  // V2.3 project secrets (ADR 0032). `secret.deliver` carries **names only** — never a
  // value, a length or a fingerprint.
  "secret.create",
  "secret.rotate",
  "secret.delete",
  "secret.deliver",
] as const;

// --- P4-13 workspace favourites and recents (FR-WORKSPACE-004/005) ---

// Why a favourite cannot be used right now. Computed per response by the server,
// never stored: a favourite saved while a root existed stops claiming to be usable
// once that root is withdrawn. The UI owns the wording for each code.
export type FavoriteUsability =
  | "usable"
  | "node_disabled"
  | "node_offline"
  | "outside_allowed_root";

export interface WorkspaceFavorite {
  id: string;
  node_id: string;
  node_name: string;
  path: string;
  display_name: string | null;
  created_at: string;
  usability: FavoriteUsability;
}

export interface RecentWorkspace {
  node_id: string;
  node_name: string;
  path: string;
  last_used_at: string;
  node_online: boolean;
  node_enabled: boolean;
}

// --- P11 port forwarding through a third-party provider (ADR 0022) ---

// What the browser may know about the stored provider credential. There is no field for
// the token because the server never sends one: a "reveal" control could not be built
// here even if somebody asked for it (D19).
export interface TunnelCredential {
  configured: boolean;
  // sha256 of the token, first 8 hex. Enough to answer "is this the one I rotated last
  // week", not enough to reconstruct anything.
  fingerprint: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface TunnelIntegration {
  enabled: boolean;
  provider: string;
  plan_tier: "free" | "pro";
  credential: TunnelCredential;
  // Fleet-wide: how many tunnels the provider plan allows at once. Checked as a global
  // count, never folded into a node's cap.
  concurrent_budget: number;
  default_protection: TunnelProtection;
  default_ttl_seconds: number;
  allowed_ports: string[] | null;
  acknowledged_at: string | null;
  // False when the deployment has no encryption key, in which case a credential cannot be
  // stored at all — said before the form is filled in, not after saving.
  secret_key_available: boolean;
  // Disabling does not close what is running; this is how the page can say how much.
  active_tunnel_count: number;
}

export interface UpdateTunnelIntegrationInput {
  enabled?: boolean;
  plan_tier?: "free" | "pro";
  concurrent_budget?: number;
  default_protection?: TunnelProtection;
  default_ttl_seconds?: number;
  allowed_ports?: string[];
  clear_allowed_ports?: boolean;
  acknowledge?: boolean;
}

export type TunnelProtection = "basic" | "ipallow" | "public";

// Derived by the server from closed_at/expires_at/state_error_code and whether the node is
// connected. There is no stored status, so there is nothing here that can disagree with it.
export type TunnelState =
  | "opening"
  | "running"
  | "unavailable"
  | "failed"
  | "expired"
  | "closed";

export interface TunnelCapabilities {
  can_close: boolean;
  can_rotate: boolean;
}

export interface TunnelSummary {
  id: string;
  node_id: string;
  node_name: string | null;
  port: number;
  label: string | null;
  url: string | null;
  url_updated_at: string | null;
  // How often the provider reassigned the URL. On the free tier this grows by one every
  // reconnect, which is why the UI warns that a copied link is short-lived.
  url_change_count: number;
  state: TunnelState;
  protection: TunnelProtection;
  basic_auth_user: string | null;
  provider: string;
  upstream_expires_at: string | null;
  expires_at: string;
  created_by_username: string | null;
  created_at: string;
  capabilities: TunnelCapabilities;
  state_error_code: string | null;
}

export interface TunnelDetail extends TunnelSummary {
  allowed_ips: string[] | null;
  rewrite_host: boolean;
  // Present only on the create and rotate responses. Only the hash is stored, so there is
  // no later request that could return it.
  basic_auth_password: string | null;
}

export interface CreateTunnelInput {
  node_id: string;
  port: number;
  protection?: TunnelProtection;
  allowed_ips?: string[];
  label?: string;
  ttl_seconds?: number;
  rewrite_host?: boolean;
  acknowledge_third_party?: boolean;
  acknowledge_public?: boolean;
}

// Which configuration layer refused. Three layers mean three different remedies, and the
// page has to name the one the user can actually act on.
export type TunnelBlockedBy = "integration" | "node_settings" | "node_local";

export interface NodeTunnelPolicy {
  node_id: string;
  enabled: boolean;
  blocked_by: TunnelBlockedBy | null;
  allowed_ports: string[];
  max_tunnels: number;
  live_tunnel_count: number;
  node_enabled: boolean;
  node_allowed_ports: string[] | null;
  node_max_tunnels: number | null;
  local_veto: boolean;
  prereq_ok: boolean;
  prereq_detail: Record<string, boolean> | null;
  local_allowed_ports: string[] | null;
  local_max_tunnels: number | null;
  // Null when the node has never reported: "we do not know" is a different state from
  // "not ready", and only one of them means "upgrade the daemon".
  reported_at: string | null;
  plan_tier: "free" | "pro";
  default_protection: TunnelProtection;
  default_ttl_seconds: number;
}

export interface UpdateNodeTunnelSettingsInput {
  enabled?: boolean;
  allowed_ports?: string[];
  clear_allowed_ports?: boolean;
  max_tunnels?: number;
  clear_max_tunnels?: boolean;
}

// Stable RBAC action keys (backend/app/services/rbac.py). Used to gate UI.
export const ACTION_NODE_VIEW = "node.view";
export const ACTION_NODE_MANAGE = "node.manage";
export const ACTION_ENROLLMENT_MANAGE = "enrollment.manage";
export const ACTION_SESSION_CREATE = "session.create";
export const ACTION_SESSION_VIEW = "session.view";
export const ACTION_SESSION_TERMINATE = "session.terminate";
export const ACTION_TERMINAL_OPERATE = "terminal.operate";
export const ACTION_TERMINAL_TAKEOVER = "terminal.takeover";
export const ACTION_TERMINAL_SHELL = "terminal.shell";
export const ACTION_FILE_BROWSE = "file.browse";
// Writing to a workspace is a different permission from reading one: Viewer
// holds file.browse and must not hold this (ADR 0024 sec 6).
export const ACTION_FILE_UPLOAD = "file.upload";
export const ACTION_AUDIT_VIEW = "audit.view";
export const ACTION_TUNNEL_VIEW = "tunnel.view";
export const ACTION_TUNNEL_MANAGE = "tunnel.manage";
export const ACTION_INTEGRATION_MANAGE = "integration.manage";
// V2.0 project layer (ADR 0027). `project.view` is held by every role, like
// `node.view`; `project.manage` is Admin-only, with enrollment and node
// management, because it decides which projects exist and what they cover.
export const ACTION_PROJECT_VIEW = "project.view";
export const ACTION_PROJECT_MANAGE = "project.manage";

// V2.1 task layer (ADR 0028). `task.approve` is separate from `task.update` even
// though the same two roles hold both: that split is what lets a session
// credential's scope exclude approval, and an action that does not exist cannot be
// excluded from a scope. Do not merge them.
export const ACTION_TASK_CREATE = "task.create";
export const ACTION_TASK_UPDATE = "task.update";
export const ACTION_TASK_APPROVE = "task.approve";

// V2.2 agent runner (ADR 0029). `agent.view` joins the read-only set for the same
// reason `node.view` is in it — a runner is part of the shape of the fleet.
// `agent.manage` is Admin-only because it is the disposition of compute: enabling a
// runner and setting its concurrency. It does **not** cover editing tags, which the
// node's own config declares (ADR 0029 amendment B5). `run.dispatch` is separate from
// `task.update` because queueing work clones a repository onto a machine and starts a
// process there.
export const ACTION_AGENT_VIEW = "agent.view";
export const ACTION_AGENT_MANAGE = "agent.manage";
export const ACTION_RUN_DISPATCH = "run.dispatch";
export const ACTION_RUN_CANCEL = "run.cancel";

// V2.3 project secrets (ADR 0032). Admin-only for the same reason `enrollment.manage`
// is: a credential the platform holds on a user's behalf, hands to a machine on demand
// and can revoke is an organisation-level asset. It also guards repository registration
// from V2.3, because a repository row stopped being "where the code is" and became
// "which credential fetches it".
export const ACTION_SECRET_MANAGE = "secret.manage";

// --- V2.0 project layer (ADR 0027) ---

/** Why a binding cannot be used right now. Deliberately the *same* vocabulary as
 *  `FavoriteUsability`: the question is identical — can this stored path start a
 *  session on that node — and a parallel set of names would mean two ways of
 *  saying the same thing.
 *
 *  `usable` does not promise the directory still exists. Detecting that needs a
 *  round trip to the node, which V2.0 does not add; a deleted directory surfaces
 *  when the session is created, exactly as for a hand-typed path. */
export type BindingUsability = FavoriteUsability;

export type ProjectStatus = "active" | "paused" | "archived";

export interface ProjectWorkspace {
  id: string;
  node_id: string;
  node_name: string;
  node_enabled: boolean;
  path: string;
  label: string | null;
  is_primary: boolean;
  usability: BindingUsability;
  created_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  status: ProjectStatus;
  owner_user_id: string;
  owner_name: string;
  workspace_count: number;
  node_count: number;
  active_session_count: number;
  last_activity_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends ProjectSummary {
  workspaces: ProjectWorkspace[];
}

export interface ActivityEvent {
  id: string;
  kind: string;
  occurred_at: string;
  payload: Record<string, unknown>;
  /** Both null together. Null means either a system-originated event *or* a
   *  reader without `audit.view`; `ActivityPage.actors_hidden` is what tells the
   *  two apart, and the UI must say which — a blank actor that silently means
   *  "you may not see this" reads as "nobody did it". */
  actor_id: string | null;
  actor_name: string | null;
  session_id: string | null;
  /** `user` / `agent` / `system` — what *kind* of actor, never which one, so it
   *  survives redaction. Without it those three render identically (ADR 0028). */
  actor_kind: "user" | "agent" | "system";
}

export interface ActivityPage {
  items: ActivityEvent[];
  actors_hidden: boolean;
  next_before: string | null;
}

// --- V2.1 task layer (ADR 0028) -------------------------------------------------

export type TaskStage =
  | "backlog"
  | "blocked"
  | "ready"
  | "implementing"
  | "verify"
  | "done";

/** A card as the *board* renders it. Deliberately without acceptance criteria and
 *  without gate detail: M1 measured the full card at 439 KB for 200 cards against
 *  74 KB for this shape, and that measurement is what replaced pagination
 *  (`plan/17/10-…md` §1). Widening this type is how that decision gets undone. */
export interface BoardCard {
  id: string;
  card_ref: string;
  title: string;
  stage: TaskStage;
  risk: string;
  priority: string;
  owner_user_id: string | null;
  owner_name: string | null;
  delivery: string;
  blocking_count: number;
  gates_approved_count: number;
  active_run_status: RunStatus | null;
  active_run_runner_name: string | null;
  waiting_reason: string | null;
  version: number;
  updated_at: string;
}

export interface BoardLane {
  stage: TaskStage;
  label: string;
  wip_suggested: number | null;
  count: number;
  cards: BoardCard[];
}

export interface Board {
  lanes: BoardLane[];
  /** Always false in V2.1, and present anyway: a field added later would force
   *  every existing client to handle its absence. */
  has_more: boolean;
}

export interface ProcessGate {
  key: string;
  label: string;
  order: number;
  requires_human: boolean;
  enabled: boolean;
  /** Set only when the gate is *derived*-disabled — the mockup gate without tunnel
   *  integration. A gate that quietly does not exist is worse than one that says
   *  why (D31), so the console shows this rather than hiding the row. */
  disabled_reason: string | null;
}

export interface ProcessDefinition {
  key: string;
  version: string;
  source: string;
  lanes: Array<{
    stage: TaskStage;
    label: string;
    order: number;
    wip_suggested: number | null;
  }>;
  readiness: Array<{ key: string; label: string; hint: string }>;
  gates: ProcessGate[];
  templates: Record<string, unknown>;
}

export interface TaskDependency {
  id: string;
  card_ref: string;
  title: string;
  stage: TaskStage;
}

export interface Task {
  id: string;
  project_id: string;
  card_ref: string;
  title: string;
  description: string | null;
  objective: string | null;
  scope: string | null;
  non_goals: string | null;
  stage: TaskStage;
  risk: string;
  priority: string;
  owner_user_id: string | null;
  epic_id: string | null;
  user_story_id: string | null;
  readiness: Record<string, boolean>;
  /** `{gate: {approved_by, approved_at}}` — never a boolean, because that cell is
   *  where "an agent's output is not an approval" lives. */
  gates: Record<string, { approved_by: string; approved_at: string } | null>;
  acceptance_criteria: Array<Record<string, unknown>>;
  links: Record<string, unknown>;
  required_labels: string[];
  version: number;
  /** Declared, and inert until V2.3/V2.4. The console labels this block so that a
   *  card saying `pull_request` does not read as a promise (ADR 0028 sec 9). */
  source: string;
  repository_id: string | null;
  base_branch: string | null;
  delivery: string;
  target_branch: string | null;
  existing_pr_ref: string | null;
  required_secrets: string[];
  assigned_runner_id: string | null;
  requirement_id: string | null;
  proposal_id: string | null;
  depends_on: TaskDependency[];
  /** The cards still blocking this one, by reference — the same list the refusal
   *  message names, so the board can show it before the user tries. */
  blocking_refs: string[];
  created_at: string;
  updated_at: string;
}

export interface TaskWrite {
  task: Task;
  /** Definition-of-Ready reporting. Never a refusal (ADR 0028 sec 1). */
  warnings: Array<{ code: string; missing?: string[] }>;
}

export interface RoadmapTask {
  id: string;
  card_ref: string;
  title: string;
  stage: TaskStage;
}

export interface RoadmapStory {
  id: string;
  card_ref: string;
  title: string;
  done_count: number;
  total_count: number;
  tasks: RoadmapTask[];
}

export interface RoadmapEpic {
  id: string;
  card_ref: string;
  title: string;
  done_count: number;
  total_count: number;
  stories: RoadmapStory[];
  /** Cards filed under this epic but under no story. Monstrare's semantics, kept
   *  because a card must never disappear because of how it was filed (D4). */
  unclassified: RoadmapTask[];
}

export interface Roadmap {
  epics: RoadmapEpic[];
  orphan_stories: RoadmapStory[];
  unclassified: RoadmapTask[];
  done_count: number;
  total_count: number;
}

export interface Requirement {
  id: string;
  project_id: string;
  card_ref: string;
  raw_text: string;
  status: string;
  created_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  spec_count: number;
  created_at: string;
  updated_at: string;
}

export interface FeatureSpec {
  id: string;
  seq: number;
  objective: string | null;
  scope: string | null;
  non_goals: string | null;
  acceptance_criteria: Array<Record<string, unknown>>;
  open_questions: Array<Record<string, unknown>>;
  authored_by_kind: string;
  authored_by: string | null;
  created_at: string;
}

export interface TaskProposal {
  id: string;
  seq: number;
  spec_id: string | null;
  tree: Record<string, unknown>;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface RequirementDetail extends Requirement {
  specs: FeatureSpec[];
  proposals: TaskProposal[];
  /** Why the approve button is disabled, in the same response that disables it. */
  blocking_questions: string[];
}

export interface AcceptProposalResult {
  created: Task[];
  incomplete: Record<string, string[]>;
}

// --- V2.2 agent runner (ADR 0029/0030/0031) --------------------------------

/** A secret's kind decides where its value goes on the node (ADR 0032 §4): `env`
 *  reaches the CLI child's environment, the two git kinds reach **only the daemon's own
 *  git environment**, and `provider_token` is not delivered at all in this phase. */
export type SecretKind = "env" | "git_pat" | "git_ssh_key" | "provider_token";

/** A project secret's metadata. **There is no field for the value, and there never will
 *  be** — nor for a fingerprint (`rotated_at` answers the same question without
 *  disclosing anything) or a length (a 93-character value is almost certainly a
 *  fine-grained PAT). */
export interface ProjectSecret {
  id: string;
  project_id: string;
  name: string;
  kind: SecretKind;
  created_by: string | null;
  created_at: string;
  rotated_at: string | null;
  /** The most useful column on the page: it separates a live credential from one
   *  nothing has touched since it was created. */
  last_used_at: string | null;
}

export interface AgentRunner {
  id: string;
  node_id: string;
  node_name: string;
  name: string;
  runtimes: string[];
  // **Matched from V2.3**, as a superset: a card reaches this runner when its
  // `required_labels` are a subset of these. Read-only — the node's own config
  // declares them — and the console must never draw them as a security control: a tag
  // decides *which machine*, never *which machine may hold a secret*.
  labels: string[];
  // Read-only node declarations. `run_untagged` false reserves this machine for cards
  // that declare a tag; `accept_secrets` false keeps it away from cards that declare
  // secrets.
  run_untagged: boolean;
  accept_secrets: boolean;
  max_concurrent: number;
  max_waiting: number;
  enabled: boolean;
  // `len(workspace.allowed_roots) === 0` on the node, **as reported by the daemon**.
  // False means the machine also serves interactive sessions, and an agent running
  // there can read those directories — the platform does not prevent that and the
  // Agents page says so rather than implying an isolation that does not exist.
  dedicated: boolean;
  online: boolean;
  active_runs: number;
  waiting_runs: number;
  // Cards pinned to this runner, whether or not any has run. A machine can be
  // over-subscribed and still show zero occupancy.
  assigned_cards: number;
  // Why the runner stopped polling, as it last reported — **not** an online flag. A
  // runner with no capacity goes quiet, so without this a full runner and a dead
  // machine look identical and the page would call a healthy node offline.
  blocked_reason: RunnerBlockedReason | null;
  disk_used_bytes: number | null;
  disk_quota_bytes: number | null;
  registered_at: string;
  last_registered_at: string | null;
}

export type RunnerBlockedReason =
  | "at_capacity"
  | "waiting_limit"
  | "disk_quota"
  | "disk_low";

export interface ProjectRepository {
  id: string;
  project_id: string;
  scheme: "https" | "ssh";
  host: string;
  path: string;
  default_branch: string;
  label: string | null;
  // Assembled by the server from the three fields, for display. There is no stored URL
  // anywhere, which is what makes a credential in one impossible rather than filtered.
  url: string;
  created_at: string;
}

export interface DispatchResult {
  run_id: string;
  status: string;
  // "any" | "assigned_offline" | "no_eligible_runner". The three pieces of copy behind
  // this must read differently, or a person cannot tell "I misconfigured something"
  // from "wait a moment".
  waiting_reason: string;
  // Which tags nothing online has, when that is why nobody claimed it — **the smallest
  // missing set, not the intersection**. "Waiting for an available agent" is the wrong
  // sentence when the truth is "no machine has `docker`", and the two lead somewhere
  // different (V2.3, exit condition 3e). Empty for the other two reasons.
  missing_tags: string[];
  // Named only for `assigned_offline`, so the copy can say which machine.
  runner_name: string | null;
}

export type RunStatus =
  | "queued"
  | "claimed"
  | "running"
  | "waiting_for_input"
  | "succeeded"
  | "failed"
  | "lost"
  | "cancelled";

export interface TaskRun {
  id: string;
  task_id: string;
  project_id: string;
  seq: number;
  status: RunStatus;
  attempt: number;
  runner_id: string | null;
  runner_name: string | null;
  assigned_runner_id: string | null;
  runtime: string | null;
  source_kind: string | null;
  source_ref: string | null;
  commit_sha: string | null;
  disk_bytes: number | null;
  queued_at: string;
  claimed_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  // "is the child progressing", as opposed to the lease's "is the runner alive".
  last_event_at: string | null;
  result: string | null;
  error_code: string | null;
  summary: string | null;
  log_bytes: number;
  log_truncated_bytes: number;
  /** **The card's declaration, not a per-run snapshot.** The authoritative record of
   *  what was handed to which machine is the `secret.deliver` audit row. Names only —
   *  there is no version of this field that could carry a value. Absent on the list
   *  route, which renders rows rather than one run. */
  secret_names?: string[];
}

export interface RunLogLine {
  seq: number;
  // The stored segment, **unparsed**. The event schema belongs to a third-party CLI
  // and changes with its version; parsing it here would make that schema part of this
  // application.
  data: string;
  truncated: boolean;
  received_at: string;
}

export interface RunLogPage {
  lines: RunLogLine[];
  next_after_seq: number | null;
  log_bytes: number;
  truncated_bytes: number;
}

export interface TaskMessage {
  id: string;
  task_id: string;
  run_id: string | null;
  author_kind: "user" | "agent" | "system";
  author_user_id: string | null;
  author_name: string | null;
  author_runner_id: string | null;
  body: string;
  kind: "message" | "question" | "answer" | "event";
  event_kind: string | null;
  created_at: string;
}

export interface TaskArtifact {
  id: string;
  task_id: string;
  run_id: string | null;
  message_id: string | null;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_by_kind: string;
  uploaded_by_user_id: string | null;
  uploaded_by_runner_id: string | null;
  created_at: string;
  deleted_at: string | null;
  delete_reason: string | null;
  previewable: boolean;
}
