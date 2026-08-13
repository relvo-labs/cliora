// Contract-v1 decoder used to validate the wire format against the shared
// golden fixtures. The P0 browser runtime does not need to decode control
// envelopes (it forwards raw bytes and reads a few control types loosely), but
// this decoder pins TypeScript to the same accept/reject contract as the Python
// and Go consumers. It intentionally has no external dependencies.

const ULID = /^[0-9A-HJKMNP-TV-Z]{26}$/;
const UUID =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/;
const MAX_PAYLOAD = 64 * 1024;
const HEADER_SIZE = 18;

const TYPES = new Set([
  "session.start",
  "session.started",
  "session.start_failed",
  "session.attach",
  "session.attached",
  "session.stop",
  "session.stopped",
  "session.list",
  "session.list_result",
  "session.recover",
  "session.status_changed",
  "terminal.resize",
  "terminal.detach",
  "terminal.gap",
  "terminal.exited",
  "terminal.error",
  "terminal.control_acquire",
  "terminal.control_release",
  "filesystem.list",
  "filesystem.entries",
  "filesystem.read",
  "filesystem.content",
  "filesystem.search",
  "filesystem.search_result",
  "filesystem.upload",
  "filesystem.uploaded",
  "filesystem.store",
  "filesystem.stored",
  "context.project",
  "context.projected",
  "node.challenge",
  "node.auth",
  "node.authenticated",
  "node.heartbeat",
  "node.register",
  "node.registered",
  "node.system_info",
  "node.runtime_status",
  "node.shutdown",
  "daemon.version",
  "daemon.doctor",
  "daemon.doctor_result",
  "daemon.update",
  "daemon.update_result",
  // Tunnel control types (v1.6.0, ADR 0022). The browser never receives these — port
  // forwarding is managed over HTTP and its data path does not involve Central at all —
  // but the envelope type vocabulary is shared across all three consumers, so the
  // manifest-driven contract test validates them here too.
  "tunnel.open",
  "tunnel.opened",
  "tunnel.close",
  "tunnel.closed",
  "tunnel.status",
  // Agent runner control types (v1.11.0, ADR 0029). The browser never receives these
  // either — a run's log reaches it over HTTP, not over this socket — but the envelope
  // vocabulary is shared by all three consumers, so the manifest-driven contract test
  // validates them here too. That shared validation is what makes the SEC-002 and
  // no-workspace fixtures below assertions in three languages rather than one.
  "runner.register",
  "runner.registered",
  "runner.poll",
  "run.offer",
  "run.accept",
  "run.decline",
  "run.lease_renew",
  "run.progress",
  "run.log_chunk",
  "run.complete",
  "run.failed",
  "run.cancel",
  "error",
]);
const ENVELOPE_KEYS = new Set([
  "version",
  "type",
  "request_id",
  "node_id",
  "timestamp",
  "payload",
  "success",
  "error",
]);

export class ProtocolError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function reject(code: string, message: string): never {
  throw new ProtocolError(code, message);
}

function isSize(rows: unknown, columns: unknown): boolean {
  return (
    Number.isInteger(rows) &&
    Number.isInteger(columns) &&
    (rows as number) >= 2 &&
    (rows as number) <= 300 &&
    (columns as number) >= 2 &&
    (columns as number) <= 500
  );
}

function validateSizePayload(payload: Record<string, unknown>): void {
  const keys = Object.keys(payload);
  const allowed = new Set(["session_id", "rows", "columns"]);
  if (keys.some((key) => !allowed.has(key)))
    reject("INVALID_MESSAGE", "Unexpected payload field");
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (!isSize(payload.rows, payload.columns))
    reject("INVALID_MESSAGE", "Terminal size out of range");
}

const RUNTIME_START_IDS = new Set(["claude", "codex", "shell", "fake"]);

function validateStartPayload(payload: Record<string, unknown>): void {
  const keys = Object.keys(payload);
  const allowed = new Set([
    "session_id",
    "runtime",
    "workspace",
    "rows",
    "columns",
  ]);
  if (keys.some((key) => !allowed.has(key)))
    reject("INVALID_MESSAGE", "Unexpected payload field");
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (!RUNTIME_START_IDS.has(payload.runtime as string))
    reject("INVALID_MESSAGE", "Runtime not allowed");
  if (
    typeof payload.workspace !== "string" ||
    payload.workspace.length < 1 ||
    payload.workspace.length > 4096
  )
    reject("INVALID_MESSAGE", "Invalid workspace");
  if (!isSize(payload.rows, payload.columns))
    reject("INVALID_MESSAGE", "Terminal size out of range");
}

function validateSessionIdPayload(payload: Record<string, unknown>): void {
  const keys = Object.keys(payload);
  if (keys.some((key) => key !== "session_id"))
    reject("INVALID_MESSAGE", "Unexpected payload field");
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
}

// Phase 1 node control-plane payloads (protocol v1.1). These mirror
// contracts/v1/schemas/messages/node-*.schema.json so the browser consumer
// enforces the same accept/reject as the Python and Go consumers. The strict
// key check (additionalProperties:false) is what forbids injecting an
// executable/command field into a node.register.
const ARCHITECTURES = new Set(["amd64", "arm64"]);
const RUNTIME_IDS = new Set(["claude", "codex", "shell"]);

function requireKeys(
  payload: Record<string, unknown>,
  allowed: Set<string>,
  required: string[],
): void {
  if (Object.keys(payload).some((key) => !allowed.has(key)))
    reject("INVALID_MESSAGE", "Unexpected payload field");
  for (const key of required)
    if (!(key in payload)) reject("INVALID_MESSAGE", `Missing ${key}`);
}

function isNonEmptyString(value: unknown): boolean {
  return typeof value === "string" && value.length > 0;
}

function validateRuntimeItem(item: unknown): void {
  if (!isPlainObject(item)) reject("INVALID_MESSAGE", "Invalid runtime item");
  const obj = item as Record<string, unknown>;
  requireKeys(
    obj,
    new Set([
      "runtime",
      "available",
      "version",
      "binary_path",
      "checked_at",
      "sandbox_bypass",
    ]),
    ["runtime", "available"],
  );
  if (!RUNTIME_IDS.has(obj.runtime as string))
    reject("INVALID_MESSAGE", "Unknown runtime");
  if (typeof obj.available !== "boolean")
    reject("INVALID_MESSAGE", "runtime.available must be boolean");
  // Optional (contract 1.7.0, ADR 0023): an older daemon omits it, and absent means
  // the sandbox is enforced. The string "false" is rejected rather than coerced —
  // three languages read that truthiness three different ways.
  if ("sandbox_bypass" in obj && typeof obj.sandbox_bypass !== "boolean")
    reject("INVALID_MESSAGE", "sandbox_bypass must be boolean");
}

// A node's port-forwarding prerequisites. Optional, so a daemon that predates the capability
// still registers; a missing object reads as "this node cannot forward ports", which is also
// the right reading of an old daemon. Note what cannot appear here: anything about a
// credential — that is the platform's, and a field that does not exist cannot leak.
function validateTunnelReport(value: unknown): void {
  if (!isPlainObject(value))
    reject("INVALID_MESSAGE", "tunnel must be an object");
  requireKeys(
    value,
    new Set([
      "veto",
      "ssh_available",
      "egress_ok",
      "known_hosts_ok",
      "daemon_supports_tunnel",
      "allowed_ports",
      "max_tunnels",
    ]),
    [
      "veto",
      "ssh_available",
      "egress_ok",
      "known_hosts_ok",
      "daemon_supports_tunnel",
    ],
  );
  for (const flag of [
    "veto",
    "ssh_available",
    "egress_ok",
    "known_hosts_ok",
    "daemon_supports_tunnel",
  ]) {
    if (typeof value[flag] !== "boolean")
      reject("INVALID_MESSAGE", `tunnel.${flag} must be boolean`);
  }
  if (value.allowed_ports !== undefined) {
    if (!Array.isArray(value.allowed_ports) || value.allowed_ports.length > 64)
      reject("INVALID_MESSAGE", "Invalid tunnel allowed_ports");
    for (const spec of value.allowed_ports)
      if (typeof spec !== "string" || !/^[0-9]{1,5}(-[0-9]{1,5})?$/.test(spec))
        reject("INVALID_MESSAGE", "Invalid tunnel port spec");
  }
  if (
    value.max_tunnels !== undefined &&
    (typeof value.max_tunnels !== "number" ||
      !Number.isInteger(value.max_tunnels) ||
      value.max_tunnels < 1 ||
      value.max_tunnels > 100)
  )
    reject("INVALID_MESSAGE", "Invalid tunnel max_tunnels");
}

function validateRegisterPayload(payload: Record<string, unknown>): void {
  if (payload.tunnel !== undefined) validateTunnelReport(payload.tunnel);
  requireKeys(
    payload,
    new Set([
      "name",
      "hostname",
      "os",
      "os_version",
      "architecture",
      "daemon_version",
      "run_user",
      "runtimes",
      "workspace_roots",
      "tunnel",
      "privileged_terminal",
      "image_upload",
      "file_upload",
    ]),
    [
      "name",
      "hostname",
      "os",
      "os_version",
      "architecture",
      "daemon_version",
      "run_user",
      "runtimes",
      "workspace_roots",
    ],
  );
  for (const key of [
    "name",
    "hostname",
    "os",
    "os_version",
    "daemon_version",
    "run_user",
  ])
    if (!isNonEmptyString(payload[key]))
      reject("INVALID_MESSAGE", `Invalid ${key}`);
  if (!ARCHITECTURES.has(payload.architecture as string))
    reject("INVALID_MESSAGE", "Unknown architecture");
  if (
    !Array.isArray(payload.runtimes) ||
    !Array.isArray(payload.workspace_roots)
  )
    reject("INVALID_MESSAGE", "runtimes/workspace_roots must be arrays");
  // Report-only, and optional: a node that says nothing is not privileged.
  if (
    "privileged_terminal" in payload &&
    typeof payload.privileged_terminal !== "boolean"
  )
    reject("INVALID_MESSAGE", "privileged_terminal must be boolean");
  // Likewise: absent means "this node does not accept image drop", never
  // "unknown" (contract 1.8.0, ADR 0024 W4).
  if ("image_upload" in payload && typeof payload.image_upload !== "boolean")
    reject("INVALID_MESSAGE", "image_upload must be boolean");
  // Two switches, not one: a node may accept screenshots into .cliora/ and
  // refuse arbitrary files anywhere in its workspace (contract 1.9.0,
  // ADR 0026 §9). Absent means "no" here too.
  if ("file_upload" in payload && typeof payload.file_upload !== "boolean")
    reject("INVALID_MESSAGE", "file_upload must be boolean");
  for (const item of payload.runtimes as unknown[]) validateRuntimeItem(item);
  for (const root of payload.workspace_roots as unknown[]) {
    if (!isPlainObject(root))
      reject("INVALID_MESSAGE", "Invalid workspace root");
    const obj = root as Record<string, unknown>;
    requireKeys(obj, new Set(["path", "display_name", "is_enabled"]), [
      "path",
      "is_enabled",
    ]);
    if (!isNonEmptyString(obj.path))
      reject("INVALID_MESSAGE", "Invalid workspace path");
    if (typeof obj.is_enabled !== "boolean")
      reject("INVALID_MESSAGE", "is_enabled must be boolean");
  }
}

function validateHeartbeatPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["daemon_version", "active_sessions", "resources", "runner"]),
    ["daemon_version", "active_sessions"],
  );
  if (!isNonEmptyString(payload.daemon_version))
    reject("INVALID_MESSAGE", "Invalid daemon_version");
  if (
    !Number.isInteger(payload.active_sessions) ||
    (payload.active_sessions as number) < 0
  )
    reject("INVALID_MESSAGE", "Invalid active_sessions");
  if (payload.resources !== undefined && !isPlainObject(payload.resources))
    reject("INVALID_MESSAGE", "Invalid resources");
  if (payload.runner !== undefined) validateRunnerPressure(payload.runner);
}

// The runner half of the heartbeat: why this node stopped asking for work, plus how
// full its run root is. The reason is a **closed set** because it is rendered as console
// copy — the Agents page maps each value to a sentence, and an unrecognised one would
// either be printed raw or silently fall through to 「線上」.
function validateRunnerPressure(value: unknown): void {
  if (!isPlainObject(value)) reject("INVALID_MESSAGE", "Invalid runner");
  const runner = value as Record<string, unknown>;
  requireKeys(
    runner,
    new Set(["blocked_reason", "disk_used_bytes", "disk_quota_bytes"]),
    [],
  );
  if (
    runner.blocked_reason !== undefined &&
    !RUNNER_BLOCKED_REASONS.has(runner.blocked_reason as string)
  )
    reject("INVALID_MESSAGE", "Unknown blocked_reason");
  for (const key of ["disk_used_bytes", "disk_quota_bytes"]) {
    const size = runner[key];
    if (size === undefined) continue;
    if (!Number.isInteger(size) || (size as number) < 0)
      reject("INVALID_MESSAGE", `Invalid ${key}`);
  }
}

function validateRuntimeStatusPayload(payload: Record<string, unknown>): void {
  if (payload.tunnel !== undefined) validateTunnelReport(payload.tunnel);
  requireKeys(payload, new Set(["runtimes", "tunnel"]), ["runtimes"]);
  if (!Array.isArray(payload.runtimes))
    reject("INVALID_MESSAGE", "runtimes must be an array");
  for (const item of payload.runtimes as unknown[]) validateRuntimeItem(item);
}

function validateSystemInfoPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["os", "os_version", "architecture", "kernel", "run_user"]),
    ["os", "os_version", "architecture", "run_user"],
  );
  for (const key of ["os", "os_version", "run_user"])
    if (!isNonEmptyString(payload[key]))
      reject("INVALID_MESSAGE", `Invalid ${key}`);
  if (!ARCHITECTURES.has(payload.architecture as string))
    reject("INVALID_MESSAGE", "Unknown architecture");
}

// P3 filesystem request payloads (protocol v1.3). Mirror
// contracts/v1/schemas/messages/filesystem-*.schema.json so the browser
// consumer enforces the same accept/reject as Python (schema) and Go. Paths are
// workspace-relative; absolute/`..`/control-char inputs are rejected (ADR 0014).
function isRelPath(value: unknown): boolean {
  if (typeof value !== "string" || value.length < 1 || value.length > 4096)
    return false;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f]/.test(value)) return false;
  if (value.startsWith("/") || value.startsWith("~")) return false;
  const segments = value.split("/");
  return !segments.includes("..");
}

function validateFsListPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["session_id", "path", "cursor", "entry_limit"]),
    ["session_id", "path"],
  );
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (!isRelPath(payload.path))
    reject("INVALID_MESSAGE", "Invalid workspace path");
  if (payload.cursor !== undefined && typeof payload.cursor !== "string")
    reject("INVALID_MESSAGE", "Invalid cursor");
  if (
    payload.entry_limit !== undefined &&
    (!Number.isInteger(payload.entry_limit) ||
      (payload.entry_limit as number) < 1 ||
      (payload.entry_limit as number) > 2000)
  )
    reject("INVALID_MESSAGE", "Invalid entry_limit");
}

function validateFsReadPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["session_id", "path"]), ["session_id", "path"]);
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (!isRelPath(payload.path))
    reject("INVALID_MESSAGE", "Invalid workspace path");
}

// Image drop (contract 1.8.0, ADR 0024). The browser is neither producer nor
// consumer of these two frames — uploads travel over HTTP — but the decoder
// validates them anyway, for the same reason it validates the tunnel frames: a
// type accepted without checking is a type that forwards malformed data.
//
// The assertion that matters here is the *absence* of fields. Two keys, exactly:
// no filename, path, directory, extension or mime, so the sender cannot name
// the file it is creating.
const UPLOAD_MAX_BASE64 = 5592408; // base64 length of 4 MiB
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;
const UPLOAD_PATH =
  /^\.cliora\/uploads\/\d{4}-\d{2}-\d{2}\/[0-9A-HJKMNP-TV-Z]{26}\.(png|jpg|gif|webp)$/;
const UPLOAD_MIMES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
]);

function validateFsUploadPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["session_id", "data"]), ["session_id", "data"]);
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (
    typeof payload.data !== "string" ||
    payload.data.length < 4 ||
    payload.data.length > UPLOAD_MAX_BASE64 ||
    !BASE64.test(payload.data)
  )
    reject("INVALID_MESSAGE", "Invalid upload payload");
}

function validateFsUploadedPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["path", "mime", "size", "modified_at"]), [
    "path",
    "mime",
    "size",
    "modified_at",
  ]);
  // The daemon named this path, so a value that does not match the shape the
  // daemon produces means the frame did not come from where it claims.
  if (typeof payload.path !== "string" || !UPLOAD_PATH.test(payload.path))
    reject("INVALID_MESSAGE", "Invalid upload path");
  if (typeof payload.mime !== "string" || !UPLOAD_MIMES.has(payload.mime))
    reject("INVALID_MESSAGE", "Invalid upload mime");
  if (
    typeof payload.size !== "number" ||
    !Number.isInteger(payload.size) ||
    payload.size < 1 ||
    payload.size > 4 * 1024 * 1024
  )
    reject("INVALID_MESSAGE", "Invalid upload size");
  if (
    typeof payload.modified_at !== "string" ||
    !TIMESTAMP.test(payload.modified_at)
  )
    reject("INVALID_MESSAGE", "Invalid upload timestamp");
}

// General file upload (contract 1.9.0, ADR 0026). Uploads travel over HTTP, so
// the browser is neither producer nor consumer of these frames — the decoder
// validates them for the same reason it validates the tunnel and image-drop
// ones: a type accepted without checking is a type that would forward malformed
// data.
//
// The assertion that matters here is the mirror of validateFsUploadPayload's.
// There, the point was the ABSENCE of any naming field. Here the caller must
// name the destination, so the point is that `filename` cannot hold a path and
// that nothing can ask to replace anything: no overwrite, mode, mime,
// precondition or revision.
const STORE_FILENAME_MAX_BYTES = 255;

function isStoreFilename(value: unknown): boolean {
  if (
    typeof value !== "string" ||
    value === "" ||
    value === "." ||
    value === ".."
  )
    return false;
  // Bytes, not code points: 84 CJK runes plus an extension is 88 characters and
  // 256 bytes, and the wire schema's maxLength counts characters.
  if (new TextEncoder().encode(value).length > STORE_FILENAME_MAX_BYTES)
    return false;
  if (value.includes("/")) return false;
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if (code < 0x20 || code === 0x7f) return false;
  }
  return true;
}

function validateFsStorePayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["session_id", "directory", "filename", "data"]),
    ["session_id", "directory", "filename", "data"],
  );
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (!isRelPath(payload.directory))
    reject("INVALID_MESSAGE", "Invalid destination directory");
  if (!isStoreFilename(payload.filename))
    reject("INVALID_MESSAGE", "Invalid filename");
  // An empty file is a legitimate upload, so unlike filesystem.upload the empty
  // string is accepted here (measured across all three consumers:
  // plan/15/07-open-measurements.md §4).
  if (
    typeof payload.data !== "string" ||
    payload.data.length > UPLOAD_MAX_BASE64 ||
    (payload.data !== "" && !BASE64.test(payload.data))
  )
    reject("INVALID_MESSAGE", "Invalid upload payload");
}

// The projection (ADR 0028). The browser never sends or receives this message — it
// is Central → daemon — and it is validated here anyway, for the reason the whole
// three-consumer contract suite exists: a rule that only one implementation enforces
// is a rule that drifts. The two properties worth reading are the confinement to the
// three platform-owned subtrees and the single legal mode.
const PROJECT_PATH =
  // eslint-disable-next-line no-control-regex
  /^\.cliora\/(context|process|reference)\/[^/\u0000-\u001f]+(\/[^/\u0000-\u001f]+)*$/;
const PROCESS_VERSION = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const PROJECT_MAX_BASE64 = 87384;

function validateContextProjectPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["session_id", "process_version", "files"]), [
    "session_id",
    "process_version",
    "files",
  ]);
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (
    typeof payload.process_version !== "string" ||
    payload.process_version.length > 32 ||
    !PROCESS_VERSION.test(payload.process_version)
  )
    reject("INVALID_MESSAGE", "Invalid process version");
  const files = payload.files;
  if (!Array.isArray(files) || files.length === 0 || files.length > 32)
    reject("INVALID_MESSAGE", "Invalid file list");
  for (const entry of files as unknown[]) {
    if (typeof entry !== "object" || entry === null)
      reject("INVALID_MESSAGE", "Invalid projected file");
    const file = entry as Record<string, unknown>;
    requireKeys(file, new Set(["path", "mode", "data"]), [
      "path",
      "mode",
      "data",
    ]);
    if (
      typeof file.path !== "string" ||
      file.path.length > 4096 ||
      file.path.split("/").includes("..") ||
      !PROJECT_PATH.test(file.path)
    )
      reject("INVALID_MESSAGE", "Invalid projected path");
    if (file.mode !== "0600") reject("INVALID_MESSAGE", "Invalid mode");
    if (
      typeof file.data !== "string" ||
      file.data.length > PROJECT_MAX_BASE64 ||
      (file.data !== "" && !BASE64.test(file.data))
    )
      reject("INVALID_MESSAGE", "Invalid projected payload");
  }
}

function validateContextProjectedPayload(
  payload: Record<string, unknown>,
): void {
  requireKeys(payload, new Set(["session_id", "written", "skipped", "bytes"]), [
    "session_id",
    "written",
    "skipped",
    "bytes",
  ]);
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  for (const key of ["written", "skipped"] as const) {
    const list = payload[key];
    if (!Array.isArray(list) || list.length > 32)
      reject("INVALID_MESSAGE", "Invalid projection result");
    for (const item of list as unknown[]) {
      if (typeof item !== "string" || item.length === 0 || item.length > 4096)
        reject("INVALID_MESSAGE", "Invalid projection result");
    }
  }
  if (
    typeof payload.bytes !== "number" ||
    !Number.isInteger(payload.bytes) ||
    payload.bytes < 0 ||
    payload.bytes > 2097152
  )
    reject("INVALID_MESSAGE", "Invalid projection size");
}

function validateFsStoredPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["path", "size", "modified_at"]), [
    "path",
    "size",
    "modified_at",
  ]);
  // Unlike filesystem.uploaded there is no fixed shape to pin: the user chose
  // this path, not the daemon. The containment rule still applies.
  if (!isRelPath(payload.path))
    reject("INVALID_MESSAGE", "Invalid stored path");
  if (
    typeof payload.size !== "number" ||
    !Number.isInteger(payload.size) ||
    payload.size < 0 ||
    payload.size > 4 * 1024 * 1024
  )
    reject("INVALID_MESSAGE", "Invalid stored size");
  if (
    typeof payload.modified_at !== "string" ||
    !TIMESTAMP.test(payload.modified_at)
  )
    reject("INVALID_MESSAGE", "Invalid stored timestamp");
}

function validateFsSearchPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["session_id", "keyword", "root", "max_results"]),
    ["session_id", "keyword"],
  );
  if (typeof payload.session_id !== "string" || !UUID.test(payload.session_id))
    reject("INVALID_MESSAGE", "Invalid session id");
  if (
    typeof payload.keyword !== "string" ||
    payload.keyword.length < 1 ||
    payload.keyword.length > 256 ||
    // eslint-disable-next-line no-control-regex
    /[\u0000-\u001f]/.test(payload.keyword)
  )
    reject("INVALID_MESSAGE", "Invalid keyword");
  if (payload.root !== undefined && !isRelPath(payload.root))
    reject("INVALID_MESSAGE", "Invalid search root");
  if (
    payload.max_results !== undefined &&
    (!Number.isInteger(payload.max_results) ||
      (payload.max_results as number) < 1 ||
      (payload.max_results as number) > 200)
  )
    reject("INVALID_MESSAGE", "Invalid max_results");
}

// P4 daemon self-update payloads (protocol v1.4). Mirror
// contracts/v1/schemas/messages/daemon-update*.schema.json. The browser never
// sends or receives these frames — updates are triggered over HTTP and relayed
// by Central — but the decoder stays a full consumer of the contract so a
// change here cannot land in one language only. The strict key check is what
// pins the security property: `daemon.update` carries a version and nothing
// else, so no URL, path, checksum or binary can ride along (ADR 0017).
const TARGET_VERSION = /^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?$/;
const UPDATE_STATUSES = new Set(["succeeded", "failed", "rolled_back"]);
const UPDATE_STAGES = new Set([
  "manifest",
  "download",
  "checksum",
  "swap",
  "restart",
  "healthcheck",
]);
const UPDATE_ERROR_CODES = new Set([
  "UPDATE_NOT_ALLOWED",
  "UPDATE_DOWNLOAD_FAILED",
  "UPDATE_CHECKSUM_MISMATCH",
  "UPDATE_HEALTHCHECK_FAILED",
  "UPDATE_ROLLED_BACK",
  "UPDATE_IN_PROGRESS",
]);

// --- Tunnel payloads (v1.6.0, ADR 0022) ---
//
// The browser is not a producer or consumer of these frames: port forwarding is driven
// over HTTP and its data path never touches Central. They are validated here because the
// contract is cross-language by construction — one manifest, three consumers — and a type
// this consumer accepts without checking is a type it would happily forward malformed.
const TUNNEL_CREDENTIAL = /^[A-Za-z0-9]{8,128}$/;
const TUNNEL_URL =
  /^https:\/\/[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?(\/[^\s]*)?$/;
const TUNNEL_PROTECTION = new Set(["basic", "ipallow", "public"]);
const TUNNEL_STATE = new Set(["running", "reconnecting", "failed", "closed"]);
const TUNNEL_REASON = new Set([
  "requested",
  "expired",
  "provider_failed",
  "shutdown",
]);
const TUNNEL_ERROR_CODE = new Set([
  "TUNNEL_PROVIDER_UNAVAILABLE",
  "TUNNEL_PROVIDER_UNAUTHORIZED",
  "TUNNEL_PROVIDER_UNTRUSTED",
  "TUNNEL_PORT_NOT_ALLOWED",
  "INTERNAL_ERROR",
]);

// Basic-auth parts may not contain ':' — that is the provider option's own separator, so a
// colon would silently create a second credential pair or an unintended option.
function validBasicAuthPart(value: unknown, minLength: number): boolean {
  if (typeof value !== "string") return false;
  if (value.length < minLength || value.length > 64) return false;
  for (const ch of value) {
    const code = ch.charCodeAt(0);
    if (code <= 0x20 || code >= 0x7f || ch === ":") return false;
  }
  return true;
}

function validateTunnelOpenPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set([
      "tunnel_id",
      "port",
      "protection",
      "credential",
      "basic_auth",
      "allowed_ips",
      "rewrite_host",
      "ttl_seconds",
    ]),
    ["tunnel_id", "port", "protection", "ttl_seconds"],
  );
  if (typeof payload.tunnel_id !== "string" || !UUID.test(payload.tunnel_id))
    reject("INVALID_MESSAGE", "Invalid tunnel id");
  if (
    typeof payload.port !== "number" ||
    !Number.isInteger(payload.port) ||
    payload.port < 1024 ||
    payload.port > 65535
  )
    reject("INVALID_MESSAGE", "Invalid tunnel port");
  if (
    typeof payload.protection !== "string" ||
    !TUNNEL_PROTECTION.has(payload.protection)
  )
    reject("INVALID_MESSAGE", "Invalid protection mode");
  // The credential lands in ssh's "<token>@<host>" argument, where '+' selects a tunnel
  // type and '@' selects the host. Widening this character set widens what a credential
  // value can redirect.
  if (
    payload.credential !== undefined &&
    (typeof payload.credential !== "string" ||
      !TUNNEL_CREDENTIAL.test(payload.credential))
  )
    reject("INVALID_MESSAGE", "Invalid credential");
  if (payload.basic_auth !== undefined) {
    if (!isPlainObject(payload.basic_auth))
      reject("INVALID_MESSAGE", "basic_auth must be an object");
    requireKeys(payload.basic_auth, new Set(["username", "password"]), [
      "username",
      "password",
    ]);
    if (
      !validBasicAuthPart(payload.basic_auth.username, 1) ||
      !validBasicAuthPart(payload.basic_auth.password, 8)
    )
      reject("INVALID_MESSAGE", "Invalid basic auth credentials");
  }
  if (payload.allowed_ips !== undefined) {
    if (!Array.isArray(payload.allowed_ips) || payload.allowed_ips.length > 32)
      reject("INVALID_MESSAGE", "Invalid allowed_ips");
    for (const ip of payload.allowed_ips)
      if (typeof ip !== "string" || !/^[0-9a-fA-F:.]+(\/[0-9]{1,3})?$/.test(ip))
        reject("INVALID_MESSAGE", "Invalid allowed_ips entry");
  }
  if (
    payload.rewrite_host !== undefined &&
    typeof payload.rewrite_host !== "boolean"
  )
    reject("INVALID_MESSAGE", "rewrite_host must be boolean");
  if (
    typeof payload.ttl_seconds !== "number" ||
    !Number.isInteger(payload.ttl_seconds) ||
    payload.ttl_seconds < 60 ||
    payload.ttl_seconds > 86400
  )
    reject("INVALID_MESSAGE", "Invalid ttl_seconds");
  if (payload.protection === "basic" && payload.basic_auth === undefined)
    reject("INVALID_MESSAGE", "basic protection requires basic_auth");
  if (
    payload.protection === "ipallow" &&
    (!Array.isArray(payload.allowed_ips) || payload.allowed_ips.length === 0)
  )
    reject("INVALID_MESSAGE", "ipallow protection requires allowed_ips");
}

function validateTunnelOpenedPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set([
      "tunnel_id",
      "url",
      "provider",
      "upstream_expires_at",
      "authenticated",
    ]),
    ["tunnel_id", "url", "provider"],
  );
  if (typeof payload.tunnel_id !== "string" || !UUID.test(payload.tunnel_id))
    reject("INVALID_MESSAGE", "Invalid tunnel id");
  // https only: the daemon parsed this out of the provider's stdout, so it is external
  // input all the way to the browser's address bar.
  if (
    typeof payload.url !== "string" ||
    payload.url.length > 2048 ||
    !TUNNEL_URL.test(payload.url)
  )
    reject("INVALID_MESSAGE", "Invalid tunnel url");
  if (payload.provider !== "pinggy")
    reject("INVALID_MESSAGE", "Unknown tunnel provider");
  if (
    payload.upstream_expires_at !== undefined &&
    (typeof payload.upstream_expires_at !== "string" ||
      !TIMESTAMP.test(payload.upstream_expires_at))
  )
    reject("INVALID_MESSAGE", "Invalid upstream expiry");
  if (
    payload.authenticated !== undefined &&
    typeof payload.authenticated !== "boolean"
  )
    reject("INVALID_MESSAGE", "authenticated must be boolean");
}

function validateTunnelIdPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["tunnel_id"]), ["tunnel_id"]);
  if (typeof payload.tunnel_id !== "string" || !UUID.test(payload.tunnel_id))
    reject("INVALID_MESSAGE", "Invalid tunnel id");
}

function validateTunnelClosedPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["tunnel_id", "reason"]), [
    "tunnel_id",
    "reason",
  ]);
  if (typeof payload.tunnel_id !== "string" || !UUID.test(payload.tunnel_id))
    reject("INVALID_MESSAGE", "Invalid tunnel id");
  if (typeof payload.reason !== "string" || !TUNNEL_REASON.has(payload.reason))
    reject("INVALID_MESSAGE", "Invalid close reason");
}

function validateTunnelStatusPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["tunnel_id", "state", "url", "upstream_expires_at", "error_code"]),
    ["tunnel_id", "state"],
  );
  if (typeof payload.tunnel_id !== "string" || !UUID.test(payload.tunnel_id))
    reject("INVALID_MESSAGE", "Invalid tunnel id");
  if (typeof payload.state !== "string" || !TUNNEL_STATE.has(payload.state))
    reject("INVALID_MESSAGE", "Invalid tunnel state");
  if (
    payload.url !== undefined &&
    (typeof payload.url !== "string" ||
      payload.url.length > 2048 ||
      !TUNNEL_URL.test(payload.url))
  )
    reject("INVALID_MESSAGE", "Invalid tunnel url");
  if (
    payload.upstream_expires_at !== undefined &&
    (typeof payload.upstream_expires_at !== "string" ||
      !TIMESTAMP.test(payload.upstream_expires_at))
  )
    reject("INVALID_MESSAGE", "Invalid upstream expiry");
  if (
    payload.error_code !== undefined &&
    (typeof payload.error_code !== "string" ||
      !TUNNEL_ERROR_CODE.has(payload.error_code))
  )
    reject("INVALID_MESSAGE", "Invalid tunnel error code");
  if (payload.state === "failed" && payload.error_code === undefined)
    reject("INVALID_MESSAGE", "failed state requires an error code");
}

function validateDaemonUpdatePayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["target_version", "allow_downgrade"]), [
    "target_version",
  ]);
  if (
    typeof payload.target_version !== "string" ||
    payload.target_version.length < 5 ||
    payload.target_version.length > 64 ||
    !TARGET_VERSION.test(payload.target_version)
  )
    reject("INVALID_MESSAGE", "Invalid target version");
  if (
    payload.allow_downgrade !== undefined &&
    typeof payload.allow_downgrade !== "boolean"
  )
    reject("INVALID_MESSAGE", "allow_downgrade must be boolean");
}

function validateDaemonUpdateResultPayload(
  payload: Record<string, unknown>,
): void {
  requireKeys(
    payload,
    new Set(["from_version", "to_version", "status", "stage", "error_code"]),
    ["from_version", "to_version", "status", "stage"],
  );
  for (const key of ["from_version", "to_version"])
    if (!isNonEmptyString(payload[key]))
      reject("INVALID_MESSAGE", `Invalid ${key}`);
  if (!UPDATE_STATUSES.has(payload.status as string))
    reject("INVALID_MESSAGE", "Unknown update status");
  if (!UPDATE_STAGES.has(payload.stage as string))
    reject("INVALID_MESSAGE", "Unknown update stage");
  if (
    payload.error_code !== undefined &&
    !UPDATE_ERROR_CODES.has(payload.error_code as string)
  )
    reject("INVALID_MESSAGE", "Unknown update error code");
}

export interface DecodedControl {
  version: 1;
  type: string;
  request_id: string;
  node_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export function decodeControl(raw: Uint8Array | string): DecodedControl {
  if (raw instanceof Uint8Array && raw.byteLength > MAX_PAYLOAD)
    reject("FRAME_TOO_LARGE", "Control frame exceeds the limit");
  let text: string;
  try {
    text =
      typeof raw === "string"
        ? raw
        : new TextDecoder("utf-8", { fatal: true }).decode(raw);
  } catch {
    reject("INVALID_MESSAGE", "Control frame is not valid UTF-8");
  }
  if (new TextEncoder().encode(text).byteLength > MAX_PAYLOAD)
    reject("FRAME_TOO_LARGE", "Control frame exceeds the limit");
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    reject("INVALID_MESSAGE", "Control frame is not valid JSON");
  }
  if (!isPlainObject(data))
    reject("INVALID_MESSAGE", "Envelope must be an object");
  for (const key of Object.keys(data))
    if (!ENVELOPE_KEYS.has(key))
      reject("INVALID_MESSAGE", "Unexpected envelope field");
  if (data.version !== 1) reject("INVALID_MESSAGE", "Unsupported version");
  if (typeof data.type !== "string" || !TYPES.has(data.type))
    reject("INVALID_MESSAGE", "Unsupported message type");
  if (typeof data.request_id !== "string" || !ULID.test(data.request_id))
    reject("INVALID_MESSAGE", "Invalid request id");
  if (typeof data.node_id !== "string" || !UUID.test(data.node_id))
    reject("INVALID_MESSAGE", "Invalid node id");
  if (typeof data.timestamp !== "string" || !TIMESTAMP.test(data.timestamp))
    reject("INVALID_MESSAGE", "Invalid timestamp");
  if (!isPlainObject(data.payload))
    reject("INVALID_MESSAGE", "Payload must be an object");
  if (data.type === "session.start") validateStartPayload(data.payload);
  if (data.type === "session.attach" || data.type === "terminal.resize")
    validateSizePayload(data.payload);
  if (
    data.type === "session.stop" ||
    data.type === "session.recover" ||
    data.type === "terminal.detach" ||
    data.type === "terminal.control_acquire" ||
    data.type === "terminal.control_release"
  )
    validateSessionIdPayload(data.payload);
  if (data.type === "filesystem.list") validateFsListPayload(data.payload);
  if (data.type === "filesystem.read") validateFsReadPayload(data.payload);
  if (data.type === "filesystem.search") validateFsSearchPayload(data.payload);
  if (data.type === "filesystem.upload") validateFsUploadPayload(data.payload);
  if (data.type === "filesystem.uploaded")
    validateFsUploadedPayload(data.payload);
  if (data.type === "filesystem.store") validateFsStorePayload(data.payload);
  if (data.type === "filesystem.stored") validateFsStoredPayload(data.payload);
  if (data.type === "context.project")
    validateContextProjectPayload(data.payload);
  if (data.type === "context.projected")
    validateContextProjectedPayload(data.payload);
  if (data.type === "node.register") validateRegisterPayload(data.payload);
  if (data.type === "node.heartbeat") validateHeartbeatPayload(data.payload);
  if (data.type === "node.runtime_status")
    validateRuntimeStatusPayload(data.payload);
  if (data.type === "node.system_info") validateSystemInfoPayload(data.payload);
  if (data.type === "daemon.update") validateDaemonUpdatePayload(data.payload);
  if (data.type === "daemon.update_result")
    validateDaemonUpdateResultPayload(data.payload);
  if (data.type === "runner.register")
    validateRunnerRegisterPayload(data.payload);
  if (data.type === "runner.registered")
    validateRunnerRegisteredPayload(data.payload);
  if (data.type === "runner.poll") validateRunnerPollPayload(data.payload);
  if (data.type === "run.offer") validateRunOfferPayload(data.payload);
  if (data.type === "run.accept" || data.type === "run.lease_renew")
    validateRunIdPayload(data.payload);
  if (data.type === "run.decline") validateRunDeclinePayload(data.payload);
  if (data.type === "run.progress") validateRunProgressPayload(data.payload);
  if (data.type === "run.log_chunk") validateRunLogChunkPayload(data.payload);
  if (data.type === "run.complete") validateRunCompletePayload(data.payload);
  if (data.type === "run.failed") validateRunFailedPayload(data.payload);
  if (data.type === "run.cancel") validateRunCancelPayload(data.payload);
  if (data.type === "tunnel.open") validateTunnelOpenPayload(data.payload);
  if (data.type === "tunnel.opened") validateTunnelOpenedPayload(data.payload);
  if (data.type === "tunnel.close") validateTunnelIdPayload(data.payload);
  if (data.type === "tunnel.closed") validateTunnelClosedPayload(data.payload);
  if (data.type === "tunnel.status") validateTunnelStatusPayload(data.payload);
  return data as unknown as DecodedControl;
}

export function decodeBinary(raw: Uint8Array): {
  kind: number;
  payload: Uint8Array;
} {
  if (raw.byteLength <= HEADER_SIZE)
    reject("INVALID_MESSAGE", "Terminal frame is too short");
  if (raw[0] !== 1)
    reject("PROTOCOL_VERSION_UNSUPPORTED", "Unsupported version");
  if (raw[1] !== 1 && raw[1] !== 2)
    reject("INVALID_MESSAGE", "Unknown terminal frame kind");
  if (raw.byteLength - HEADER_SIZE > MAX_PAYLOAD)
    reject("FRAME_TOO_LARGE", "Terminal payload exceeds the limit");
  return { kind: raw[1], payload: raw.slice(HEADER_SIZE) };
}

// --- V2.2 agent runner (contract 1.11.0, ADR 0029/0031) ---------------------
//
// Two of these carry a decision rather than input hygiene, and both are enforced the
// same way in all three languages:
//
//   * a run spec has no `command`, no `args`, no `env` and **no `workspace`**. The
//     first three keep SEC-002's argv clause true on the wire; the fourth is the
//     2026-08-10 ruling's most direct mark on the contract — while that field existed,
//     Central would have to choose one of the user's paths and send it.
//   * a source URL may not carry userinfo, because a credential in a remote URL
//     surfaces in `git remote -v`, in the reflog and in error messages (ADR 0031 §5).

const RUN_RUNTIMES = new Set(["claude", "codex"]);
const RUN_SOURCE_KINDS = new Set(["none", "repo", "existing_branch"]);
// `provider_token` is deliberately absent: this phase has no code path that sends one,
// so it must be unrepresentable. The git kinds stay, because a deployment setting — not
// the wire — decides whether they travel (ADR 0032 §4).
const RUN_SECRET_KINDS = new Set(["env", "git_pat", "git_ssh_key"]);
const RUN_PHASES = new Set([
  "preparing",
  // 1.12.0: "stuck on a credential" and "stuck on the network" are different facts.
  "authenticating",
  "fetching",
  "checked_out",
  "running",
  "waiting_for_input",
  "finishing",
]);
// Absence means "polling normally" — there is no `""` member, because a runner that is
// fine says nothing rather than saying it is fine.
const RUNNER_BLOCKED_REASONS = new Set([
  "at_capacity",
  "waiting_limit",
  "disk_quota",
  "disk_low",
]);
const RUN_DECLINE_REASONS = new Set([
  "at_capacity",
  "runtime_unavailable",
  "disk_quota",
  "shutting_down",
  "internal_error",
]);
const RUN_RESULTS = new Set(["succeeded", "no_changes"]);
const RUN_CANCEL_REASONS = new Set([
  "user_cancelled",
  "lease_lost",
  "shutting_down",
]);
const RUN_FAILURE_CODES = new Set([
  "RUN_SOURCE_UNAVAILABLE",
  "RUN_DISK_QUOTA",
  "RUN_IDLE_TIMEOUT",
  "RUN_TIMEOUT",
  "RUN_RUNTIME_UNAVAILABLE",
  "RUN_CANCELLED",
  "RUN_INTERNAL_ERROR",
]);
// No leading `-`: a closed argv table cannot protect a value that *is* a flag.
const GIT_REF = /^[A-Za-z0-9._][A-Za-z0-9._/-]*$/;
const COMMIT_SHA = /^[0-9a-f]{40}$/;
// The only userinfo accepted is the literal `git@`, and only on ssh: that is the
// canonical ssh clone form and ssh needs a user name. What stays unrepresentable is
// a **password**, which is what would leak into `git remote -v`, the reflog and error
// messages. Central assembles this from three stored columns, so the accepted set is
// exactly the set it can produce.
const CLONE_URL =
  /^(https:\/\/|ssh:\/\/(git@)?)[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?\/[^@\s]*$/;

function requireUuid(value: unknown, field: string): void {
  if (typeof value !== "string" || !UUID.test(value))
    reject("INVALID_MESSAGE", `Invalid ${field}`);
}

function requireBoundedInt(
  value: unknown,
  field: string,
  min: number,
  max: number,
): void {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < min ||
    value > max
  )
    reject("INVALID_MESSAGE", `Invalid ${field}`);
}

function validateRunnerRegisterPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set([
      "runner_id",
      "name",
      "runtimes",
      "labels",
      // V2.3. Optional on the wire, and **absent means true** on both — the
      // compatibility rule is a property of the payload, not of a release version.
      "run_untagged",
      "accept_secrets",
      "max_concurrent",
      "max_waiting",
      "dedicated",
    ]),
    ["name", "runtimes", "max_concurrent", "max_waiting", "dedicated"],
  );
  if (
    typeof payload.name !== "string" ||
    payload.name.length === 0 ||
    payload.name.length > 128
  )
    reject("INVALID_MESSAGE", "Invalid runner name");
  const runtimes = payload.runtimes;
  if (!Array.isArray(runtimes) || runtimes.length > 8)
    reject("INVALID_MESSAGE", "Invalid runtimes");
  for (const runtime of runtimes as unknown[])
    if (typeof runtime !== "string" || !RUN_RUNTIMES.has(runtime))
      reject("INVALID_MESSAGE", "Unknown runtime");
  if (payload.labels !== undefined) {
    if (!Array.isArray(payload.labels) || payload.labels.length > 32)
      reject("INVALID_MESSAGE", "Invalid labels");
  }
  for (const key of ["run_untagged", "accept_secrets"] as const) {
    if (payload[key] !== undefined && typeof payload[key] !== "boolean")
      reject("INVALID_MESSAGE", `Invalid ${key}`);
  }
  requireBoundedInt(payload.max_concurrent, "max_concurrent", 0, 64);
  requireBoundedInt(payload.max_waiting, "max_waiting", 0, 64);
  if (typeof payload.dedicated !== "boolean")
    reject("INVALID_MESSAGE", "Invalid dedicated");
}

function validateRunnerRegisteredPayload(
  payload: Record<string, unknown>,
): void {
  requireKeys(
    payload,
    new Set(["runner_id", "accepted", "enabled", "reason"]),
    ["accepted"],
  );
  if (typeof payload.accepted !== "boolean")
    reject("INVALID_MESSAGE", "Invalid accepted");
}

function validateRunnerPollPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["runner_id", "capacity"]), [
    "runner_id",
    "capacity",
  ]);
  requireUuid(payload.runner_id, "runner id");
  requireBoundedInt(payload.capacity, "capacity", 1, 16);
}

function validateRunIdPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["run_id"]), ["run_id"]);
  requireUuid(payload.run_id, "run id");
}

function validateRunSource(value: unknown): void {
  if (typeof value !== "object" || value === null)
    reject("INVALID_MESSAGE", "Invalid source");
  const source = value as Record<string, unknown>;
  requireKeys(source, new Set(["kind", "url", "ref"]), ["kind"]);
  if (typeof source.kind !== "string" || !RUN_SOURCE_KINDS.has(source.kind))
    reject("INVALID_MESSAGE", "Unknown source kind");
  if (source.kind === "none") {
    // Absent, not null-and-ignored.
    if ("url" in source || "ref" in source)
      reject("INVALID_MESSAGE", "source none carries no url or ref");
    return;
  }
  if (typeof source.url !== "string" || !CLONE_URL.test(source.url))
    reject("INVALID_MESSAGE", "Invalid source url");
  if (typeof source.ref !== "string" || !GIT_REF.test(source.ref))
    reject("INVALID_MESSAGE", "Invalid source ref");
}

function validateRunSpec(value: unknown): void {
  if (typeof value !== "object" || value === null)
    reject("INVALID_MESSAGE", "Invalid spec");
  const spec = value as Record<string, unknown>;
  requireKeys(
    spec,
    new Set([
      "runtime",
      "source",
      "context",
      "credential",
      "secrets",
      "branch",
      "allowed_verification_commands",
      "timeout_seconds",
      "idle_timeout_seconds",
    ]),
    ["source", "context", "timeout_seconds", "idle_timeout_seconds"],
  );
  if (spec.runtime !== undefined) {
    if (typeof spec.runtime !== "string" || !RUN_RUNTIMES.has(spec.runtime))
      reject("INVALID_MESSAGE", "Unknown runtime");
  }
  validateRunSource(spec.source);
  if (
    typeof spec.context !== "string" ||
    spec.context.length === 0 ||
    // 32 KiB from 1.12.0. The old ceiling of 65536 was the *whole* control frame, so one
    // field could consume the entire budget on its own — and it now shares that budget
    // with the secrets below.
    spec.context.length > 32768
  )
    reject("INVALID_MESSAGE", "Invalid context");
  if (spec.credential !== undefined) {
    // A run credential and nothing else can be delivered through this field.
    if (
      typeof spec.credential !== "string" ||
      !/^cliora_rt_[A-Za-z0-9_-]+$/.test(spec.credential)
    )
      reject("INVALID_MESSAGE", "Invalid run credential");
  }
  if (spec.secrets !== undefined) {
    // Values reach a node on exactly one message, and only from the platform's own
    // store (ADR 0032 §1). `provider_token` is absent from the accepted kinds because
    // this phase can never send one — unlike the git kinds, which a run-time setting
    // gates rather than the wire.
    if (!Array.isArray(spec.secrets) || spec.secrets.length > 8)
      reject("INVALID_MESSAGE", "Invalid secrets");
    for (const entry of spec.secrets as unknown[]) {
      if (typeof entry !== "object" || entry === null)
        reject("INVALID_MESSAGE", "Invalid secret");
      const secret = entry as Record<string, unknown>;
      requireKeys(secret, new Set(["name", "kind", "value"]), [
        "name",
        "kind",
        "value",
      ]);
      if (
        typeof secret.name !== "string" ||
        !/^[A-Z][A-Z0-9_]*$/.test(secret.name) ||
        secret.name.length > 128
      )
        reject("INVALID_MESSAGE", "Invalid secret name");
      if (typeof secret.kind !== "string" || !RUN_SECRET_KINDS.has(secret.kind))
        reject("INVALID_MESSAGE", "Invalid secret kind");
      if (
        typeof secret.value !== "string" ||
        secret.value.length === 0 ||
        secret.value.length > 8192
      )
        reject("INVALID_MESSAGE", "Invalid secret value");
    }
  }
  if (spec.branch !== undefined) {
    // The daemon re-checks this prefix too: the five hard constraints are its
    // responsibility, and a constraint that trusts the frame it was sent is not one.
    if (
      typeof spec.branch !== "string" ||
      spec.branch.length > 255 ||
      !/^cliora\/[A-Za-z0-9._][A-Za-z0-9._-]*$/.test(spec.branch)
    )
      reject("INVALID_MESSAGE", "Invalid branch");
  }
  requireBoundedInt(spec.timeout_seconds, "timeout_seconds", 60, 86400);
  requireBoundedInt(
    spec.idle_timeout_seconds,
    "idle_timeout_seconds",
    30,
    21600,
  );
  if (spec.allowed_verification_commands !== undefined) {
    if (
      !Array.isArray(spec.allowed_verification_commands) ||
      spec.allowed_verification_commands.length > 16
    )
      reject("INVALID_MESSAGE", "Invalid verification commands");
  }
}

function validateRunOfferPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set([
      "run_id",
      "task_id",
      "project_id",
      "card_ref",
      "title",
      "attempt",
      "delivery",
      "spec",
    ]),
    ["run_id"],
  );
  // `null` is the "nothing for you" answer, and it carries nothing else.
  if (payload.run_id === null) return;
  requireUuid(payload.run_id, "run id");
  if (payload.delivery !== undefined) {
    // `branch` joins in 1.12.0; the two pull-request modes need a provider API and are
    // still refused at dispatch, so they cannot reach a node.
    if (
      payload.delivery !== "none" &&
      payload.delivery !== "artifact" &&
      payload.delivery !== "branch"
    )
      reject("INVALID_MESSAGE", "Unsupported delivery");
  }
  validateRunSpec(payload.spec);
}

function validateRunDeclinePayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["run_id", "reason"]), ["run_id", "reason"]);
  requireUuid(payload.run_id, "run id");
  if (
    typeof payload.reason !== "string" ||
    !RUN_DECLINE_REASONS.has(payload.reason)
  )
    reject("INVALID_MESSAGE", "Unknown decline reason");
}

function validateRunProgressPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["run_id", "phase", "message", "commit_sha", "waiting_for_input"]),
    ["run_id", "phase"],
  );
  requireUuid(payload.run_id, "run id");
  if (typeof payload.phase !== "string" || !RUN_PHASES.has(payload.phase))
    reject("INVALID_MESSAGE", "Unknown phase");
  if (payload.message !== undefined) {
    if (typeof payload.message !== "string" || payload.message.length > 512)
      reject("INVALID_MESSAGE", "Invalid message");
  }
  if (payload.commit_sha !== undefined) {
    if (
      typeof payload.commit_sha !== "string" ||
      !COMMIT_SHA.test(payload.commit_sha)
    )
      reject("INVALID_MESSAGE", "Invalid commit sha");
  }
}

function validateRunLogChunkPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["run_id", "seq", "data", "truncated"]), [
    "run_id",
    "seq",
    "data",
  ]);
  requireUuid(payload.run_id, "run id");
  requireBoundedInt(payload.seq, "seq", 0, Number.MAX_SAFE_INTEGER);
  // 32 KiB, deliberately far below the large-frame ceiling: this type is not in that
  // set, because the same socket carries interactive terminal bytes.
  if (typeof payload.data !== "string" || payload.data.length > 32768)
    reject("INVALID_MESSAGE", "Log chunk too large");
}

function validateRunCompletePayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set([
      "run_id",
      "result",
      "summary",
      "disk_bytes",
      "git_remotes",
      "unpushed_commits",
      "untracked_files",
    ]),
    ["run_id", "result"],
  );
  requireUuid(payload.run_id, "run id");
  if (typeof payload.result !== "string" || !RUN_RESULTS.has(payload.result))
    reject("INVALID_MESSAGE", "Unknown result");
  if (payload.summary !== undefined) {
    if (typeof payload.summary !== "string" || payload.summary.length > 4096)
      reject("INVALID_MESSAGE", "Invalid summary");
  }
  if (payload.git_remotes !== undefined) {
    if (!Array.isArray(payload.git_remotes) || payload.git_remotes.length > 16)
      reject("INVALID_MESSAGE", "Invalid git remotes");
  }
}

function validateRunFailedPayload(payload: Record<string, unknown>): void {
  requireKeys(
    payload,
    new Set(["run_id", "error_code", "message", "summary", "disk_bytes"]),
    ["run_id", "error_code"],
  );
  requireUuid(payload.run_id, "run id");
  if (
    typeof payload.error_code !== "string" ||
    !RUN_FAILURE_CODES.has(payload.error_code)
  )
    reject("INVALID_MESSAGE", "Unknown failure code");
  if (payload.message !== undefined) {
    if (typeof payload.message !== "string" || payload.message.length > 512)
      reject("INVALID_MESSAGE", "Invalid message");
  }
}

function validateRunCancelPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["run_id", "reason"]), ["run_id", "reason"]);
  requireUuid(payload.run_id, "run id");
  if (
    typeof payload.reason !== "string" ||
    !RUN_CANCEL_REASONS.has(payload.reason)
  )
    reject("INVALID_MESSAGE", "Unknown cancel reason");
}
