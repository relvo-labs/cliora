# ADR 0014: P3 path security & filesystem relay model

Status: accepted (2026-07-25). Governs Phase 3 (Workspace Files); confirmed defaults per product decision (see `plan/04`).

## Context

P3 opens read-only directory listing, filename search, and file preview over the same Node filesystem P2 launches sessions in. The dominant risk is path escape (traversal, symlink, prefix collision) and TOCTOU (a path validated then swapped before it is opened). P2 delivered `internal/workspace.Guard.Resolve`, but it returns only a *path string*, leaving a resolve→open race. This ADR fixes the security model before any endpoint ships.

## Decisions

### Re-canonicalize every operation

Every `filesystem.list`/`read`/`search` re-runs full validation (tech §11.2: reject empty/null-byte → abs → clean → `EvalSymlinks` of target and root → `filepath.Rel` containment; **never `strings.HasPrefix`**). The daemon never trusts a client breadcrumb or a prior listing. Central passes only a **workspace-relative** path; the daemon joins it onto the session's workspace (itself already inside an enabled root) and validates the result.

### TOCTOU: operate on a validated handle, not a re-opened path

The guard gains handle-returning entry points built on Go 1.24+ `os.Root` (toolchain 1.26.5): `OpenRoot` opens a root as an `*os.Root`; list/read operate through it (`Root.Open`, `Root.Stat`), which refuses any component that escapes the root via `..` or a symlink. File reads `fstat` the **open fd** for regular-file and size checks and read from that **same fd** (`io.LimitReader`), so a post-check replacement or symlink swap cannot redirect the read or bypass the size cap. `Resolve` is retained for display/authorization comparison only, never as the basis for a second open.

### Error taxonomy

Internal, fine-grained (for metrics/audit): `WORKSPACE_INVALID`, `WORKSPACE_OUTSIDE_ALLOWED_ROOT`, `WORKSPACE_NOT_FOUND`, `WORKSPACE_NOT_DIRECTORY`, `WORKSPACE_PERMISSION_DENIED`; file layer `FILE_NOT_FOUND`, `FILE_TOO_LARGE`, `FILE_BINARY`, `FILE_DENIED`, `FILE_PERMISSION_DENIED`. **Externally**, `WORKSPACE_OUTSIDE_ALLOWED_ROOT` and `WORKSPACE_NOT_FOUND` collapse to a single "cannot access" message at the Central boundary so a caller cannot probe for the existence of paths outside their workspace. The daemon still returns the precise code on the wire (trusted link); Central maps to the safe outward message.

### Central is relay-only

Central resolves `session_id → node_id` + workspace, does a **prefix pre-authorization** (relative path must stay within the session workspace), then relays via `NodeConnectionRegistry.request()`. Central never touches the Node filesystem itself. The daemon is the sole authority on the final canonical decision.

### Input types

Central accepts a **workspace-relative path** for list/read (absolute paths, `..` segments, and null bytes are rejected at the HTTP boundary, before any daemon call). Search accepts a **keyword** (filename substring, case-insensitive); no globs, no regex, no `ripgrep`/shell arguments, ever.

### Audit granularity

`file.sensitive_read_denied` records **classification + file extension only** (plus user/node/session/request_id/time). It does **not** record `rel_path`, the filename stem, or any absolute path — a sensitive path can itself leak a confidential project or directory name (SEC-006 requires the event, not the path). File content is never recorded anywhere.

## Consequences

- The guard exposes `OpenRoot`/handle helpers; callers must use them, not re-open resolved paths. A lint/review rule: no `os.Open`/`os.Stat` on a guard-returned path string in `internal/files`.
- Outward existence-probing is closed; operators lose path detail in audit (accepted trade-off; can be revisited via a policy change in P4, still without content).
- If `os.Root` proves insufficient for a case, fall back to `openat`/`O_NOFOLLOW` segment-walking — never relax containment.
