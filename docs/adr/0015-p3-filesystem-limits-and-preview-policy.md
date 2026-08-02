# ADR 0015: P3 filesystem limits & preview policy

Status: accepted (2026-07-25). Governs Phase 3 (Workspace Files); confirmed defaults per product decision (see `plan/04`).

Amended 2026-08-01 by ADR 0024 (the read-only premise is withdrawn) and by `plan/13` (the
text/binary classification is rewritten). Both amendments are recorded below; everything not
mentioned in them stands.

## Limits (configurable; measured, not hard-coded)

| Item | Initial | On breach |
|---|---:|---|
| `filesystem.max_preview_size` | 2 MiB (`DefaultMaxPreviewSize`) | `FILE_TOO_LARGE` + size, no content read |
| Text/binary classification (amended 2026-08-01) | whole read buffer (≤ `max_preview_size`) | null byte anywhere → `FILE_BINARY`; not UTF-8 → `FILE_BINARY` + `reason=unsupported_encoding`; control-char ratio > 10% of runes → `FILE_BINARY` |
| `filesystem.upload.max_bytes` (new 2026-08-01) | 4 MiB / image | `FILE_UPLOAD_TOO_LARGE`, nothing written |
| `filesystem.upload.max_session_bytes` | 64 MiB | `FILE_UPLOAD_QUOTA_EXCEEDED` |
| `filesystem.upload.max_files_per_day` | 200 | `FILE_UPLOAD_QUOTA_EXCEEDED` |
| `filesystem.upload.retention_days` | 7 | pruned at session start and every 6 h |
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

### Amendment (2026-08-01): the 8 KiB sniff window was the bug, not the budget

Measured on the repository itself (`plan/13/08-measurements.md`): of 878 files that are
**entirely valid UTF-8**, 20 could not be previewed — 8.7% of those over 8 KiB containing
multi-byte runes. Every one had the same cause: `sample[:8192]` cuts inside a multi-byte
rune, `utf8.Valid` fails on the truncated window, and the file is reported as
`application/octet-stream`. For pure CJK content the cut lands mid-rune 2 times in 3.

The same window failed in the other direction: a binary file whose first 8 KiB are printable
ASCII was served as text, so `FR-FILE-004.AC-02` did not hold either.

Decision: classify over the **whole read buffer** (already bounded by `max_preview_size`),
validate UTF-8 on rune boundaries, treat `ESC`/`FF`/`VT` as text rather than control
characters (an ANSI-coloured build log is a text file — three colour pairs per line tripped
the old rule), and take the control-char ratio as runes over runes rather than runes over
bytes. "The window is for performance" does not survive measurement: a 2 MiB file classifies
in 2.66 ms against this ADR's own 3 s preview budget — 0.09% of it.

A file that is text but not UTF-8 (Big5, GBK, Latin-1, UTF-16) is now reported as
`FILE_BINARY` with `reason=unsupported_encoding` and mime `text/plain; charset=unknown`,
because "we cannot read this encoding" and "this is not text" call for different next steps
from the user. Transcoding is deliberately **not** added: measurement showed none of the
false verdicts came from encodings, and guessing an encoding fails by rendering plausible
mojibake. See `plan/13` D15 for the condition that would reopen it.

Accuracy is pinned by a classification corpus (`daemon/internal/files/testdata/classify/`)
and by `FR-FILE-008`, because the opposite of "too strict" is not "correct" — it is
"too loose", and only a corpus can tell the difference.

### Amendment (2026-08-01, ADR 0024): the read-only premise is withdrawn

This ADR was written on the premise that the workspace is read-only, and its scope line said
`Out of P3: editing/upload/download`. That premise no longer holds — see ADR 0024. Replace
the scope line's reading with: **still not built** are editing, download, delete, rename and
general file upload; the one write path that exists is image drop; and any future path must
satisfy ADR 0024's W1–W4 (confined by `workspace.Root`, bounded by quota and retention,
audited per write, refusable by the node). The wording matters — "not built yet" rather than
"not allowed".

The RBAC section below gains one action: `file.upload`, held by Admin and Developer.
Its sentence "Viewer read-only, consistent with P2's read-only viewer attach" still holds
**for Viewer** — Viewer has no write capability at all — but it no longer describes the
posture of the system.

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
