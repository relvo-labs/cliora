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

const RUNTIME_START_IDS = new Set(["claude", "codex", "fake"]);

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
const RUNTIME_IDS = new Set(["claude", "codex"]);

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
    new Set(["runtime", "available", "version", "binary_path", "checked_at"]),
    ["runtime", "available"],
  );
  if (!RUNTIME_IDS.has(obj.runtime as string))
    reject("INVALID_MESSAGE", "Unknown runtime");
  if (typeof obj.available !== "boolean")
    reject("INVALID_MESSAGE", "runtime.available must be boolean");
}

function validateRegisterPayload(payload: Record<string, unknown>): void {
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
    new Set(["daemon_version", "active_sessions", "resources"]),
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
}

function validateRuntimeStatusPayload(payload: Record<string, unknown>): void {
  requireKeys(payload, new Set(["runtimes"]), ["runtimes"]);
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
  if (data.type === "node.register") validateRegisterPayload(data.payload);
  if (data.type === "node.heartbeat") validateHeartbeatPayload(data.payload);
  if (data.type === "node.runtime_status")
    validateRuntimeStatusPayload(data.payload);
  if (data.type === "node.system_info") validateSystemInfoPayload(data.payload);
  if (data.type === "daemon.update") validateDaemonUpdatePayload(data.payload);
  if (data.type === "daemon.update_result")
    validateDaemonUpdateResultPayload(data.payload);
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
