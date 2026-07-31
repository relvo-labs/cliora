# Contract changelog

## 1.5.0 — 2026-07-31 (compatible)

- **`runtime` gains `shell`** in `session-start.schema.json` (`claude|codex|shell|fake`) and `runtime-item.schema.json` (`claude|codex|shell`). The system terminal (FR-SHELL-001, ADR 0021) is an ordinary session with a different runtime id, so it reuses the whole session/terminal pipeline: ws-ticket, relay, single-writer, reattach snapshot, two-stage stop and audit.
- **No payload shape changed. No field was added anywhere.** That is the point of doing it this way: `session.start` stays closed over its five fields with `additionalProperties:false`, so the front end still cannot name a command, binary, argv, environment or entrypoint (SEC-002). `SCOPE-011` is narrowed rather than withdrawn, and this is the half that survives. Golden fixture `invalid/session-start-shell-with-binary.json` asserts that `runtime:"shell"` plus a `binary` field is rejected identically by Python, Go and TypeScript — without it, the property would be defended only by a comment.
- `runtime-item` accepts `shell` so a node can report whether a usable shell exists (and at which path) the same way it reports `claude`/`codex`. A node that disables it, or has no shell binary, reports `available:false`, which Central turns into `RUNTIME_NOT_FOUND`.
- New error code (Central, not on the wire): `SHELL_ALREADY_OPEN` — one live system terminal per CLI session.

## 1.4.0 — 2026-07-25 (compatible)

- Additive Phase 4 daemon self-update frames (version integer stays `1`). New control types: `daemon.update` (Central → daemon) and `daemon.update_result` (daemon → Central). Requests are relayed through the existing `/ws/nodes/{node_id}` link with the usual `request_id` correlation; the browser never sees them (updates are triggered over HTTP).
- **`daemon.update` carries a version and nothing else** — `{target_version, allow_downgrade?}` with `additionalProperties:false`. There is deliberately no field for a URL, filename, path, checksum or binary: the daemon derives the download location and expected SHA256 solely from its local `config.yaml` server URL plus `GET /api/releases/manifest`, so a spoofed or malicious control frame cannot make a node fetch or execute a sender-chosen artifact (SEC-002 extended to the release path, ADR 0017). `target_version` is pinned to strict semver, so a traversal-shaped (`../../etc/passwd`) or floating (`latest`) value is refused at the wire. Golden fixtures assert rejection of frames carrying `url`, `binary_path` and `sha256`, and all three consumers (Python schema, Go, TypeScript) enforce it identically.
- `daemon.update_result` reports `{from_version, to_version, status, stage, error_code?}` where `status ∈ {succeeded, failed, rolled_back}` and `stage ∈ {manifest, download, checksum, swap, restart, healthcheck}`, so a runbook can see which step failed without reading daemon logs. It carries no path, URL or log text.
- New error codes: `UPDATE_NOT_ALLOWED`, `UPDATE_DOWNLOAD_FAILED`, `UPDATE_CHECKSUM_MISMATCH`, `UPDATE_HEALTHCHECK_FAILED`, `UPDATE_ROLLED_BACK`, `UPDATE_IN_PROGRESS`.
- Both new types are small control messages and keep the tight 64 KiB frame bound (the 8 MiB ceiling from 1.3.1 remains limited to the three filesystem response types). See ADR 0017.

## 1.3.1 — 2026-07-25 (compatible)

- **Frame bound for filesystem responses.** The 64 KiB control-frame limit cannot carry a ≤2 MiB preview (FR-FILE-003) or a 2000-entry listing (ADR 0015): such a frame was silently dropped on decode, so the request timed out instead of answering. `filesystem.entries`, `filesystem.content` and `filesystem.search_result` now decode against a separate `MAX_FILE_PAYLOAD` / `MaxFilePayload` bound of **8 MiB** (well under uvicorn's 16 MiB `ws_max_size`); every other control type keeps the tight 64 KiB limit, so the larger ceiling cannot be used to smuggle an oversize session frame. The daemon additionally refuses to *build* a frame above its type's bound (`ErrFrameTooLarge` → `FRAME_TOO_LARGE` reply), so an over-limit response is an explicit error rather than a hang. Terminal binary frames are unchanged (64 KiB). Python + Go enforce and test the split bound; the browser never receives filesystem frames (they arrive over HTTP), so the TypeScript control decoder keeps 64 KiB.

## 1.3.0 — 2026-07-25 (compatible)

- Additive Phase 3 read-only filesystem frames (version integer stays `1`). New control types: `filesystem.list`/`filesystem.entries`, `filesystem.read`/`filesystem.content`, `filesystem.search`/`filesystem.search_result`. Requests flow browser→Central (HTTP) → daemon (relayed control frames); responses flow back. Central never reads the node filesystem itself (ADR 0014).
- Strict typed payload schemas for the three daemon request frames: `filesystem.list` (`{session_id, path, cursor?, entry_limit?}`), `filesystem.read` (`{session_id, path}`), `filesystem.search` (`{session_id, keyword, root?, max_results?}`). `path`/`root` must be **workspace-relative**: a shared pattern rejects absolute paths, `~`, any `..` segment, and control characters; `additionalProperties:false` forbids injecting shell/`ripgrep` arguments (SEC-002). Enforced identically by Python (schema), Go, and TypeScript consumers against new golden fixtures.
- New error codes: `WORKSPACE_INVALID`, `WORKSPACE_NOT_DIRECTORY`, `FILE_NOT_FOUND`, `FILE_TOO_LARGE`, `FILE_BINARY`, `FILE_DENIED`, `FILE_PERMISSION_DENIED`, `NODE_BUSY`. See ADR 0014/0015.

## 1.2.0 — 2026-07-24 (compatible)

- Additive Phase 2 session/terminal frames (version integer stays `1`). New control types: `session.start_failed`, `session.list`, `session.list_result`, `session.recover`, `session.status_changed`, `terminal.detach`, `terminal.error`, `terminal.control_acquire`, `terminal.control_release`.
- `session.start` payload evolved from the P0 dev shape (`runtime_id:"fake"`, `workspace_id` const) to the production shape: `runtime` enum (`claude|codex|fake`, `fake` retained for the Fake CLI test path) and a real `workspace` path string (1..4096). Central still never sends a command/argv/shell string (SEC-002); `additionalProperties:false` continues to forbid injecting one.
- Strict typed payload schemas for the session request frames the daemon receives: `session.start`, `session.stop`/`session.recover`/`terminal.detach`/`terminal.control_acquire`/`terminal.control_release` (shared `{session_id}` shape), and `session.list` (empty object). Enforced identically by Python, Go, and TypeScript consumers against new golden fixtures.
- New error codes: `SESSION_INVALID_STATE`, `SESSION_LIMIT_REACHED`, `SESSION_START_FAILED`, `WORKSPACE_OUTSIDE_ALLOWED_ROOT`, `WORKSPACE_NOT_FOUND`, `WORKSPACE_PERMISSION_DENIED`. See ADR 0013.

## 1.1.0 — 2026-07-24 (compatible)

- Additive Phase 1 node control-plane frames (version integer stays `1`). New control types: `node.challenge`, `node.auth`, `node.authenticated`, `node.register`, `node.registered`, `node.system_info`, `node.runtime_status`, `node.shutdown`, `daemon.version`, `daemon.doctor`, `daemon.doctor_result`. `node.challenge` carries a single-use nonce; `node.auth` carries `{challenge_id, signature}`. The daemon private key never leaves the node (ADR 0008).
- New error codes: `NODE_DISABLED`, `NODE_AUTH_FAILED`, `RUNTIME_NOT_FOUND`, `RUNTIME_DISABLED`, `RUNTIME_NOT_EXECUTABLE`, `ENROLLMENT_TOKEN_INVALID`.
- Strict typed payload schemas for the security-bearing daemon→central data frames (`node.register`, `node.heartbeat`, `node.runtime_status`, `node.system_info`) with `additionalProperties:false`, `architecture` enum (`amd64|arm64`) and `runtime` enum (`claude|codex`). Enforced identically by the Python, Go, and TypeScript consumers against new golden fixtures. See ADR 0008.

## 1.0.0 — 2026-07-22

- Initial P0 contract (breaking baseline): typed control envelope, stable errors, terminal binary header, size limits, and golden fixtures.
