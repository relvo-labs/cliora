# ADR 0015: P3 filesystem limits & preview policy

Status: accepted (2026-07-25). Governs Phase 3 (Workspace Files); confirmed defaults per product decision (see `plan/04`).

## Limits (configurable; measured, not hard-coded)

| Item | Initial | On breach |
|---|---:|---|
| `filesystem.max_preview_size` | 2 MiB (`DefaultMaxPreviewSize`) | `FILE_TOO_LARGE` + size, no content read |
| Binary sniff window | first 8 KiB | null byte / invalid UTF-8 / high control-char ratio → `FILE_BINARY` + mime |
| Directory entries per response | 2000 | `truncated=true` + `next_cursor` (offset cursor) |
| `filesystem.search.max_depth` | 10 | stop descending, `partial=true`, `stopped_reason="depth"` |
| `filesystem.search.max_results` | 200 | stop, `partial`, `stopped_reason="results"` |
| `filesystem.search.max_scanned` | 50000 | stop, `partial`, `stopped_reason="scanned"` |
| `filesystem.search.timeout_seconds` | 10 (monotonic) | stop, `partial`, `stopped_reason="timeout"` |
| Central relay request timeout | list 15 s / read 15 s / search 12 s | `REQUEST_TIMEOUT`, clear correlation |
| Per-node pending requests | 128 (shared with P2 sessions) | `NODE_BUSY` |
| Filesystem response frame | 8 MiB (`MAX_FILE_PAYLOAD` / `MaxFilePayload`) | daemon refuses to build it → `FRAME_TOO_LARGE` reply |
| Directory list latency (rep.) | < 2 s | measured; shortfall → release decision |
| ≤2 MB preview latency (rep.) | < 3 s | measured; shortfall → release decision |

### Amendment (2026-07-25): filesystem response frames need their own bound

Found by the P3-10 latency harness, not by any unit test: the protocol's 64 KiB
control-frame limit (ADR 0003) cannot carry the payloads this ADR mandates — a
2 MiB preview is ~32× over it, and a 2000-entry listing ~5×. Central's
`decode_control` dropped such a frame as `FRAME_TOO_LARGE` and the ws loop
`continue`d, so the parked Future was never resolved and the user saw a 15 s
`REQUEST_TIMEOUT` instead of their file. Every existing test missed it because
the daemon tests call the file service directly and the Central tests fake the
registry — nothing crossed the real codec.

Decision: the three filesystem *response* types (`filesystem.entries`,
`filesystem.content`, `filesystem.search_result`) decode against a separate
8 MiB bound; all other control frames keep 64 KiB, so the wider ceiling cannot
be used to smuggle an oversize session frame. 8 MiB leaves headroom for JSON
escaping of a 2 MiB preview and stays under uvicorn's 16 MiB `ws_max_size`. The
daemon also refuses to *build* an over-bound frame (`ErrFrameTooLarge`) and
answers `FRAME_TOO_LARGE`, so the failure mode is an explicit error rather than a
hang. Rejected alternatives: raising the global control bound (weakens the DoS
limit for every frame type), chunking content across frames (P3 explicitly
returns a bounded body, not a stream), and shrinking the preview cap
(contradicts FR-FILE-003). See `contracts/CHANGELOG.md` 1.3.1.

## Sensitive file policy — **balanced** (confirmed)

Four categories via `filesystem.denied_patterns`; admins may extend for environment-specific secrets:

- **Exact name** (primary): `.env`, `id_rsa`, `id_ed25519`.
- **Extension** (primary): `*.pem`, `*.key`, `*.p12`, `*.pfx`.
- **Glob** (narrowed): `.env.*` only. The broad `*secret*` / `*credentials*` globs from tech §11.7 are **deliberately dropped** to avoid denying source code (`secret_handler.py`, `credentials_test.ts`). Trade-off: a few oddly-named secret files may slip through; admins add exact names when needed.
- **Directory**: a path segment matching a sensitive directory pattern (e.g. `.ssh/`, `.aws/`) denies everything beneath it.

Unknown/undetermined file types default to **deny preview**. A denied sensitive read returns only a classification and reason — never a content fragment or absolute path.

## Ignore rule

`workspace.excluded_directories` (`.git/objects`, `node_modules`, `.venv`, `dist`, `build`, `__pycache__`, extendable) are **shown but not loaded**: entries carry `excluded=true, expandable=false`, the UI labels them "excluded", and search does not descend into them. Hidden entries (`.`-prefixed) are shown by default, de-emphasized.

## Monaco lifecycle

Read-only preview only. Each `(node, session, rel_path)` maps to one model owned by `useMonacoModel`; a **bounded LRU cache of 8 models** is kept, evicted models are `dispose()`d immediately, and switching session / leaving the view disposes all models, the editor, and the worker. Workers are self-bundled via Vite (no CDN). When a previously previewable file becomes denied on refresh (replaced with a sensitive file, grown oversized, permission changed, deleted), the editor content is cleared before showing the denial screen — no stale content remains.

## RBAC

List, search, and preview share the single action `file.browse` (no separate preview action). **All three roles — Admin, Developer, Viewer — hold `file.browse`** (Viewer read-only), consistent with P2's read-only viewer attach. Sensitive/binary/oversize denial still applies to every role.

## Scope

Out of P3: editing/upload/download, Git, full-text (content) search or any `ripgrep` args, live file watching (manual refresh only), image/PDF/archive/binary content preview (metadata only), `workspace_favorites` / recent-workspace (FR-WORKSPACE-004/005, deferred to P4).
