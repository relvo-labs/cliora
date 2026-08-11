# Contract changelog

## 1.11.0 — 2026-08-11 (compatible)

**Added — the agent runner (ADR 0029/0030/0031, `plan/18`).**

Twelve new types, all in the `runner.*` / `run.*` family: `runner.register`,
`runner.registered`, `runner.poll`, `run.offer`, `run.accept`, `run.decline`,
`run.lease_renew`, `run.progress`, `run.log_chunk`, `run.complete`, `run.failed` and
`run.cancel`. Thirty-eight new fixtures (15 valid, 23 invalid).

**Nothing existing changed on the wire**, and every fixture that predates this release
is byte-for-byte identical (`scripts/tk/contract_snapshot.py`, asserted per file).

Three properties are worth reading here rather than in the schemas, because each is a
decision the shape enforces rather than a rule someone has to remember:

- **The queue is pull-only, and backpressure is structural.** A runner at capacity
  simply stops sending `runner.poll` — there is no `capacity: 0` frame, and so there is
  no scheduler on the platform. The claim happens when the poll *arrives*, which is why
  `run.offer` is a one-way statement of fact ("this is yours, the lease has started")
  rather than a request. `run_id: null` is the "nothing for you" answer, present as a
  shape so the daemon's switch has exactly one branch to write.
- **`run.lease_renew` is unconditional, on purpose.** The lease answers "is the runner
  alive" and nothing else. Making renewal depend on the child having produced output
  would collapse it with the idle timer, and those two must end differently: a lost
  runner re-queues the card, a hung child does not.
- **`run.log_chunk` is capped at 32 KiB and is deliberately not in the large-frame
  set.** That socket also carries interactive terminal bytes, and promoting an agent's
  debug output to the 8 MiB tier would buy it with the terminal's responsiveness. The
  content is a JSONL event stream, so the chunker may not split a line.

**One existing message gains one optional field:** `node.heartbeat` may carry a
`runner` object (`blocked_reason`, `disk_used_bytes`, `disk_quota_bytes`). It exists
because of the first property above: a runner with no capacity goes quiet, so from
Central a full runner, a runner with nowhere to put a checkout and a machine somebody
unplugged are the same silence. Without this the console would show a healthy machine as
offline. Absent means "not a runner", and an absent `blocked_reason` inside a present
object means "polling normally" — there is no empty-string member, because a runner that
is fine says nothing rather than saying it is fine. Every daemon before 0.9.0 omits the
object entirely and is unaffected.

Requires `agentd` 0.9.0 on the node for the runner types; the heartbeat field is
optional in both directions.

## 1.10.0 — 2026-08-09 (compatible)

**Added — the platform's context projection (ADR 0028, `plan/17`).**

- `context.project` (Central → daemon) and `context.projected` (the reply). One
  message carries the task context pack, the session credential and the process notes
  into `.cliora/{context,process,reference}/`.
- `node.register` gains an optional `context_projection` boolean, the same shape
  `image_upload` and `file_upload` already use. **Absent means incapable**, which is
  the correct reading of every daemon before 0.8.0: sessions there start and run
  unchanged, and Central simply does not send the new message.

**Nothing existing changed.** Every message, field and fixture that predates this
release is byte-for-byte identical; `scripts/tk/contract_snapshot.py` asserts it per
file.

Two constraints are worth reading in the schema rather than here, because they are
what make this a *narrow* addition rather than a general write path: the destination
pattern admits only the three platform-owned subtrees (so `.cliora/uploads/`, a
`.gitignore` the user may own, and anything outside `.cliora/` are unrepresentable),
and `mode` has exactly one legal value.

Requires `agentd` 0.8.0 on the node.

## 1.9.0 — 2026-08-03 (compatible)

- **One new type pair and one additive report field** (`version` stays `1`): `filesystem.store` (Central → daemon), `filesystem.stored` (daemon → Central), and `node-register.file_upload`. Together they place one file, under a name the user chose, into a directory the user chose. See ADR 0026 and `plan/15`.
- **Two upload types now exist, and their rules differ because what they carry differs.** `filesystem.upload` (1.8.0) carries `{session_id, data}` and nothing else, because a pasted screenshot does not need a name — which is why it has no path-traversal entry point to defend. `filesystem.store` *must* let the caller name the destination, because `requirements.txt`'s name is its entire meaning. ADR 0024 §4 wrote down both mistakes this avoids: citing 1.8.0 to argue that no path may name anything (that produces no feature), and citing this one to add a `filename` to `filesystem.upload` (that breaks a path which is currently correct, in exchange for nothing). **`filesystem.upload` is unchanged — same two fields, same five golden invalid fixtures, unmodified.**
- **`directory` and `filename` are separate fields, and that is a security control rather than tidiness.** A single `path` would need a validator to confirm that its last segment is the name the user typed, and traversal grows out of the holes in that validator. Two fields make *a filename containing a separator* unrepresentable: the `filename` pattern excludes `/` outright, in all three consumers. This matters concretely because URL encoding can smuggle a separator into a query parameter — `%2F` decodes to `/`, `..%2F` to `../` (measured, `plan/15/07-open-measurements.md` §2) — so validation runs after decoding and the wire states the rule instead of relying on that ordering alone.
- **Nothing in `filesystem.store` can ask to replace something.** There is no `overwrite`, `mode`, `mime`, `precondition` or `revision`, and `additionalProperties` is `false`. The daemon creates the file with `O_EXCL` under its final name, so a collision is refused with `FILE_EXISTS` and not one existing byte is touched. That single property is why this contract change needs no version token, no `If-Match`, no 412 and no undo semantics. `invalid/filesystem-store-with-overwrite.json` pins it.
- **`mode` is excluded even though it looks harmless.** Uploaded files land `0644`, always: a file dragged in from a browser should not arrive executable. A field that could raise that would be a field someone eventually sets.
- **`filesystem.store` is the second *request* type allowed the 8 MiB bound, and the bound does not move.** 4 MiB of raw file is 5.33 MiB of base64, inside the `MAX_FILE_PAYLOAD` / `MaxFilePayload` ceiling that ADR 0024 §7 already paid for; both upload paths share one per-file config key so they cannot drift apart on what fits. `TestUploadCapFitsFrameBound` asserts the arithmetic, because raising the key without raising the frame would not fail loudly — the node would drop the oversize frame and the request would time out.
- **`filename`'s `maxLength` is a loose outer bound, not the real limit.** JSON Schema counts code points, so 84 CJK characters plus an extension is 88 code points and **256 bytes**. The 255-**byte** limit is enforced by the daemon and by the browser. Schema bounds the shape; the implementations bound the unit.
- **`data` accepts the empty string**, so an empty file (a placeholder, an empty `__init__.py`) can be uploaded. Measured across all three consumers: Go's `StdEncoding.Strict()`, Python's `b64decode(validate=True)` and `Buffer.from(…, "base64")` all decode `""` to zero bytes without error, and the pattern is an optional group. Everything else stays canonical standard-alphabet base64 — `"QQ"` without padding is refused by Go and Python alike, so the same bytes still have exactly one representation.
- **`filesystem.stored.size` has `minimum: 0` where `filesystem.uploaded.size` has `minimum: 1`.** Deliberate, not a typo: an empty file is uploadable and a zero-byte image is not.
- **`file_upload` is optional and absent means "no"**, the same rule as `image_upload` and `privileged_terminal`. It is a **separate** switch rather than a widening of `image_upload`, because "may the platform put screenshots in `.cliora/`" and "may it put arbitrary files anywhere in my workspace" are different-sized grants and a node owner is entitled to answer them differently.
- **No new error codes on the wire.** `FILE_UPLOAD_TOO_LARGE`, `FILE_UPLOAD_QUOTA_EXCEEDED`, `FILE_UPLOAD_FAILED`, `FILE_UPLOAD_DISABLED` and `FILE_DENIED` are reused as-is; `FILE_EXISTS` and `FILE_UPLOAD_NO_SPACE` are added to the daemon's vocabulary. Reusing the four says something true: these are the same class of refusal, arriving from a second path.
- **The browser is neither producer nor consumer** — uploads travel over HTTP — but the TypeScript decoder validates both new types anyway, the same call made for the tunnel frames in 1.6.0 and image drop in 1.8.0: a type accepted without checking is a type that forwards malformed data.

## 1.8.0 — 2026-08-01 (compatible)

- **Two new types and one additive report field** (`version` stays `1`): `filesystem.upload` (Central → daemon), `filesystem.uploaded` (daemon → Central), and `node-register.image_upload`. Together they carry one image from a browser into a session workspace so a CLI can read it. See ADR 0024 and `plan/13`.
- **The request may not name the file, and that is the whole design.** `filesystem.upload` is `{session_id, data}` with `additionalProperties:false`. There is no `filename`, `path`, `directory`, `extension`, `mime` or `overwrite`. The daemon picks the directory (`.cliora/uploads/<UTC date>/`) and the name (`<ULID>.<sniffed extension>`). This is the same rule as 1.4.0 (`daemon.update` carries a version and nothing else), 1.6.0 (`tunnel.open` has no host field) and 1.7.0 (posture is reported, never selected), moved from arguments to file names — and it is unusually cheap here, because path traversal, double extensions (`x.png.sh`) and overwriting an existing file are three problems with one shared entry point. Remove the entry point and there is no validation code left to get wrong. Five golden invalid fixtures pin it: `filesystem-upload-with-filename`, `-with-path`, `-with-mime`, `-non-base64`, `-oversize`.
- **`mime` is excluded even as a hint.** Once the field exists, someone asks whether it can be trusted to skip the sniff. `filesystem.uploaded` reports the mime the daemon actually detected.
- **`filesystem.upload` is the first *request* type allowed the 8 MiB bound**, and the first in the Central → daemon direction. 1.3.1 gave three filesystem *responses* the larger ceiling specifically so it could not be used to smuggle an oversize session frame; this widens the node's decode limit from 64 KiB to 8 MiB for exactly one type. Accepted because the peer is an authenticated Central, the daemon re-checks type and size immediately after decode, and the schema caps `data` at 5592408 characters — the base64 length of 4 MiB — so a bigger frame is refused *before* it is decoded. The response, `filesystem.uploaded`, is a path and three scalars and keeps the tight bound.
- **`data` is canonical standard-alphabet base64** (`^[A-Za-z0-9+/]+={0,2}$`). Newlines and the URL-safe alphabet are rejected in all three consumers, and the daemon decodes with `StdEncoding.Strict()`, so the same bytes have exactly one representation on the wire.
- **`filesystem.uploaded.path` is pattern-checked against the shape the daemon produces.** The browser does not receive this frame, but a path that does not match means the frame did not come from where it claims.
- **`image_upload` is optional and absent means "no".** An older daemon sends nothing and the console reads that as "this node does not accept image drop" — never as "unknown". Report-only for the same reason as 1.7.0's posture fields: whether a machine's workspace may be written to is the machine's answer.
- **New error codes:** `FILE_UPLOAD_TOO_LARGE`, `FILE_UPLOAD_UNSUPPORTED_TYPE`, `FILE_UPLOAD_QUOTA_EXCEEDED`, `FILE_UPLOAD_FAILED`. `FILE_UPLOAD_DISABLED` is on the wire too, because a node that has switched image drop off must be able to say so to a Central whose cached registration is stale.
- **The browser is neither producer nor consumer** — uploads travel over HTTP — but the TypeScript decoder validates both types anyway, the same call made for the tunnel frames in 1.6.0: a type accepted without checking is a type that forwards malformed data. Its control-frame bound deliberately stays at 64 KiB, since the browser has no reason to receive a frame this large.

## 1.7.0 — 2026-08-01 (compatible)

- **Two additive report-only fields** (`version` stays `1`): `runtime-item.sandbox_bypass` and `node-register.privileged_terminal`. Both describe the *posture of a node* — a CLI launched with its sandbox and approval prompts disabled, and a system terminal that can reach root through sudo. See ADR 0023 and `plan/12`.
- **The design rule is report-only, and it is the whole point.** A node tells Central what posture it is in; there is no field, in either direction, that lets Central *choose* one. That is the same shape as 1.4.0 (`daemon.update` carries a version and nothing else) and 1.6.0 (`tunnel.open` has no host field), for the same reason: a message that could set the posture would be a message that could grant root on a node.
- **Deliberately absent, and now pinned by fixtures:** `args`, `argv`, `flags`, `command`, `sandbox`, `sudo`, `env`, `tmux_options`. `session.start` keeps its five fields and `additionalProperties: false`, so the console still cannot name a command, argument, environment variable or entrypoint (SEC-002; the half of `SCOPE-011` that ADR 0021 §1 kept). `invalid/session-start-with-args.json` and `invalid/session-start-with-sandbox-request.json` assert that both a launch flag *and* a request for a posture are rejected identically by Python, Go and TypeScript. Without them, the boundary would be defended only by a comment — the same gap ADR 0021 §Context records from last time.
- **`sandbox_bypass` is a measurement, not a setting.** It reports what the runtime will actually be launched with. A node whose config asks for the bypass but whose installed CLI does not accept the flag reports `false`, because that is what will happen when a session starts (ADR 0023 D3). Reporting the request instead would make the console claim a posture the machine is not in.
- **Both fields are optional and absent means "no".** An older daemon sends neither; `privileged_terminal` absent reads as unprivileged and `sandbox_bypass` absent as enforced. Absent is never "unknown" — a posture nobody has reported is not one the console may imply.
- `sandbox_bypass` is only ever sent for a runtime the daemon has flags for (`codex` today). The schema does not encode that restriction — an `if/then` would triple the size of a very small file — so the daemon owns it and `TestOnlyCodexHasLaunchFlags` keeps it true.
- **No new error codes.** A CLI that does not accept the flag is not an error (the session starts), and a node that cannot sudo is not an error (that is a posture). Both are expressed by the report fields. Adding a code would force callers to treat a posture as a failure.

## 1.6.0 — 2026-08-01 (compatible)

- **Additive port-forwarding control frames** (`version` stays `1`). New types: `tunnel.open`, `tunnel.opened`, `tunnel.close`, `tunnel.closed`, `tunnel.status`. Port forwarding is delivered by integrating a third-party tunnel provider (Pinggy) rather than by a Central-side reverse proxy — see ADR 0022 and `plan/11` (the self-hosted design is `plan/10`, rejected on cost).
- **No new binary frame kind, and no new WebSocket endpoint.** The forwarded traffic never passes through Central: the daemon supervises an `ssh -R` child process and the provider carries the bytes. So `MAX_PAYLOAD`, `LARGE_FRAME_TYPES` and the binary kind allowlist (1 = input, 2 = output) are all unchanged — unlike 1.3.1, which had to widen the frame bound for filesystem responses.
- **`tunnel.open` is the first message type that carries a secret** (`credential`, the provider token, delivered per open because the platform holds it and the node never writes it to disk). Two consequences are part of the contract: the frame must never be logged, and the golden fixtures use obviously fake values (`AAAAAAAAAAAA`) so that no test data resembles a real token.
- **`credential` is `^[A-Za-z0-9]{8,128}$`, and that is a security control rather than tidiness.** The value is concatenated into `ssh`'s `<token>@<host>` argument, where the provider separates modifiers with `+` and the host with `@`; a credential containing `+tcp` would change the tunnel type and one containing `@evil.host` would change the destination. `invalid/tunnel-open-credential-with-plus.json` pins this in all three consumers. For the same reason `basic_auth` forbids `:` (the provider option's own separator, `invalid/tunnel-open-colon-in-password.json`), `port` is bounded to 1024–65535 on the wire (`invalid/tunnel-open-privileged-port.json`), `additionalProperties:false` rejects a `host` field (`invalid/tunnel-open-with-host-field.json`), and `url` is https-only (`invalid/tunnel-opened-http-url.json`).
- **There is no host, url or ssh-option field anywhere in these payloads.** The provider host is a daemon-side constant and the target is always the node's own loopback, so the protocol cannot be used to make a node connect to somewhere of Central's choosing (SEC-002 extended to the tunnel path).
- **`tunnel.status` is unsolicited**, like `terminal.gap`/`terminal.exited`: it carries a fresh ULID and must be dispatched before the request-correlation lookup or it is discarded as unmatched. It exists because the provider's URL changes on every reconnect on the free tier, and `tunnel.opened.authenticated: false` while a credential was sent is how Central learns the provider silently downgraded the tunnel to anonymous — measured behaviour (`PG-01`), not documented behaviour.
- New error codes: `TUNNEL_PROVIDER_NOT_CONFIGURED`, `TUNNEL_PROVIDER_UNAVAILABLE`, `TUNNEL_PROVIDER_UNAUTHORIZED`, `TUNNEL_PROVIDER_UNTRUSTED`, `TUNNEL_PORT_NOT_ALLOWED`, `TUNNEL_LIMIT_REACHED`. Three further codes are Central-only and deliberately not on the wire: `TUNNEL_INTEGRATION_DISABLED`, `TUNNEL_NODE_DISABLED`, `SECRET_KEY_MISSING`.
- All three consumers enforce the new types and payloads against the shared manifest. The browser is neither producer nor consumer of these frames — port forwarding is driven over HTTP — but the TypeScript decoder validates them anyway, because a type accepted without checking is a type that would forward malformed data.

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
