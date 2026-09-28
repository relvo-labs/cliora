# ADR 0029 — Read-only binary preview: images and PDF, rendered in the console, never handed over

- Status: **accepted** (2026-09-27). The product owner approved, in writing on 2026-09-27,
  the widening of `file.browse` in §7 (Viewer included) and **all** recommended defaults
  OD-1 … OD-11 in `plan/31/01-decisions-and-governance.md` §6, unchanged. No decision in
  this ADR was altered by the approval. `BP-08`'s security review is still required before
  release: a `FAIL` verdict reopens this ADR, and `BP-11` may not start without a non-`FAIL`
  verdict (plan/31/01 §1). Implementation is tracked in `plan/31/09-implementation-status.md`.
- Previously: **proposed** (design only, 2026-09-27).
- Revised a third time: 2026-09-27, after the review of `653ff61` (BLOCKED). Changes:
  expanded-byte budget for compressed PNG metadata and length budgets for other formats'
  metadata (§3, §4, T3).
- Revised again: 2026-09-27, after the re-review of `7458141` (BLOCKED). Changes: flag
  off on any edge that is not proven (§6, OD-11); `preview_close` always sent (§5, §6);
  registration-specific rollback proof (§9); fail-closed open probe (§3); PDF.js floor
  6.2.108 (§12); `StatIn` (§3).
- Revised: 2026-09-27, after the independent design review of `c7b85c5` (BLOCKED). Changes:
  path in a POST body rather than a query string (§6); non-blocking confined open (§3);
  field omitted when disabled, for Central rollback (§9); audit commit and session (§6, §10);
  encryption decided by the renderer only (§4, OD-8).
- Date: 2026-09-27
- Issue: #77 (`[Mobile][Files] 圖片與 PDF 的安全唯讀預覽（含 Viewer）`)
- Depends on: #76 green first (the mobile file list and the existing text preview must
  work before any new preview type is claimed; #77 acceptance item 1)
- Amends (on acceptance): ADR 0015 (its binary default-deny keeps holding for
  `filesystem.read`; this ADR adds a *separate* operation with its own allowlist),
  `research/tech.md` §11.6 last paragraph ("圖片、PDF … 第一階段不直接預覽"),
  `FR-FILE-004` (a binary file in the allowlist is no longer only "不支援預覽")
- Related: ADR 0014 (`workspace.Root` confinement, reused unchanged), ADR 0016 (RBAC is
  one table; resource scope), ADR 0017 (CSP with no external origin), ADR 0024 / 0026
  (report-only node switches; "Central holds no byte"), ADR 0027 (tokens; no literal
  colour), ADR 0028 (merged in PR #71) (download; §16 below keeps the two
  separate)
- Requirements: `FR-FILE-012` (new, registered 2026-09-27), plus the amendments listed in
  `plan/31/01-decisions-and-governance.md` §2 (`FR-FILE-004` note, `FR-AUTH-002.AC-11` note,
  `FR-CONN-006.AC-13`)
- Contract: v1.11.0, compatible. PR #71 merged first with ADR 0028, v1.10.0,
  migration `0021`, `FR-FILE-011`, and `FR-CONN-006.AC-12`. This work keeps ADR 0029,
  v1.11.0, migration `0022` (revising `0021`), `FR-FILE-012`, and `FR-CONN-006.AC-13`.
- Plan: `plan/31/` (not `plan/30/`, which PR #71 occupies)

## Context

### What exists today (base `157efe3178999a8c35b34f55ee183d47842c63ec`)

| Fact | Evidence |
|---|---|
| The only read operation, `filesystem.read`, is default-deny for binary. It runs a fixed order: sensitive name → confined `os.Root` open → regular-file check on the fd → sensitive check on the fd's resolved name → size cap → bounded read → binary / non-UTF-8 deny. It returns only UTF-8 text. | `daemon/internal/files/read.go:16-90` (sensitive `:18-20`, open `:25`, regular `:39-41`, resolved name `:49-55`, cap `:58-60`, bounded read `:64`, binary deny `:74-79`, text success `:82-89`) |
| The read open is **not** `O_NOFOLLOW`, although the comment at `read.go:12` says it is. `Root.OpenFile` calls `os.Root.Open`, which refuses `..` and any symlink that escapes the root but **follows a symlink that stays inside it**. That is exactly why the second sensitive check runs on `RealRel(f)`. Only the write path passes `O_NOFOLLOW`. | `daemon/internal/workspace/root.go:100-118` (read), `:152-159` (write) |
| That open is **blocking**. `os.Root.Open` is a plain `O_RDONLY` open, so on a FIFO it waits for a writer before `f.Stat()` can reject it. Because `handleFsRead` runs on the dispatch loop, the **existing** text preview of a workspace FIFO stalls the whole node's control loop. This is pre-existing and is not fixed by this ADR; §3 must not copy it. | `root.go:109-118`; `read.go:25`, `:35-41`; `connection.go:509` |
| Both edges log the full request line, **query string included**, to disk. | `deploy/nginx/nginx.conf:52-55`, `deploy/railway/nginx.conf.template:64-67` (`"$request"`) |
| Central's own access log also includes the query string. uvicorn 0.35.0 logs `get_path_with_query_string(scope)`, and Central is started without `--no-access-log`. | uvicorn `==0.35.0` pinned at `backend/pyproject.toml:11`; in that release `uvicorn/protocols/utils.py:52-56` and `uvicorn/protocols/http/h11_impl.py:473-477` (same in `httptools_impl.py:476-480`); `deploy/backend.Dockerfile:147`; `deploy/railway/central.railway.json:17` |
| The existing file API already puts workspace paths and search keywords in query strings, so both access logs record them today, even though Central carefully logs only a keyword digest. This is pre-existing and is recorded here, not fixed. | `backend/app/api/http/files.py:44-73`, `:203-207`; `backend/app/services/files.py:300-304` |
| A `node.register` that fails Central's schema is **silently skipped**: `decode_control` raises, the WebSocket route `continue`s, nothing is persisted and no `node.registered` is sent. The connection stays up, and the daemon ignores acks, so neither side reports it. | `backend/app/protocol/codec.py:100-102`; `backend/app/api/ws/nodes.py:199-209`; `daemon/internal/connection/connection.go:472-475` |
| `AuditService.record` only adds a row to the caller's session, and adds `request_id` to the metadata. A route that raises before committing loses the row. The existing preview route commits explicitly, and the RBAC-denial middleware writes on its own short-lived session. | `backend/app/services/audit.py:196-210`; `backend/app/api/http/files.py:212-215`; `backend/app/api/middleware.py:117-129`, `:153-157`, `:171` |
| The preview cap is 2 MiB (`DefaultMaxPreviewSize`). | `docs/adr/0015-p3-filesystem-limits-and-preview-policy.md` limits table; `research/prd.md` `FR-FILE-003` |
| Central only relays `filesystem.read` and returns the daemon's in-band payload. | `backend/app/api/http/files.py:203-215`, `backend/app/services/files.py:323-349` |
| Every filesystem op resolves the session and authorises `file.browse` **plus** view access to the owning session, refuses a shell session, and only then checks that the node is online. | `backend/app/services/files.py:182-198`, `backend/app/services/authz.py:154-165`, `:211-215` |
| Viewer holds `file.browse`. | `backend/app/services/rbac.py:52`; `docs/permission-matrix.md:26` |
| A sensitive-read denial is audited with classification and extension only, never path or content. | `backend/app/services/files.py:41`, `:482-523` |
| `POST /images` is an **upload** (write, `file.upload`), not a preview. Its type allowlist and magic sniff are for writing. | `backend/app/api/http/files.py:76-159`; `daemon/internal/files/upload.go:68-90` (`SniffImage`) |
| The daemon runs `filesystem.read` **inline on its single control-dispatch loop**, with no worker. That loop also handles terminal input frames. | `daemon/internal/connection/connection.go:480-523` (`handleFsRead` called at `:509`); `daemon/internal/connection/files_handlers.go:82-133` |
| An old daemon **silently drops** a control frame whose type it does not know. There is no error reply, so Central would wait for `REQUEST_TIMEOUT`. | `daemon/internal/protocol/codec.go:87` (`allowedTypes` check) → `connection.go:491-494` (`continue` on decode error); the `switch` at `:495-523` has no `default` |
| Filesystem responses may use the 8 MiB `MaxFilePayload`. Every other control frame keeps 64 KiB. | `daemon/internal/protocol/codec.go:18-40`; `backend/app/protocol/codec.py:21`, `:32` |
| `node-register` is `additionalProperties:false`. Capability booleans are optional, and absent means "no". | `contracts/v1/schemas/messages/node-register.schema.json:3`, `:7-9`; `contracts/CHANGELOG.md` 1.8.0 / 1.9.0 |
| Node posture booleans are persisted, `server_default=false`. | `backend/app/db/models.py:92-107` |
| Server-computed capability flags drive the UI. | `backend/app/services/authz.py:315-316`; `frontend/src/views/SessionWorkspaceView.vue:472-499` |
| The browser authenticates with a **Bearer header** injected by the fetch wrapper, not a cookie. | `frontend/src/api/client.ts:1`, `:654` |
| The deployed CSP is `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; … img-src 'self' data:; … object-src 'none'; …`. **`img-src` does not allow `blob:`**. | `deploy/nginx/nginx.conf:134`; `deploy/railway/nginx.conf.template:114` |
| `/api/` is proxied with `proxy_buffering on` and no `proxy_max_temp_file_size`. | `deploy/nginx/nginx.conf:163-175`; `deploy/railway/nginx.conf.template:159` |
| The frontend has no PDF library, the daemon has no image library beyond Go's standard library, and there is no Service Worker, IndexedDB or Cache Storage use in `frontend/src`. | `frontend/package.json` `dependencies`; `daemon/go.mod`; `rg serviceWorker\|indexedDB\|caches.open frontend/src` → no match |
| The text preview pane is Monaco-only, and plan/29 explicitly keeps images as `FILE_BINARY`, "不渲染". | `frontend/src/components/file/PreviewPane.vue:30-34`; `plan/29/06-files-and-preview-mobile.md:61`, `:65` |
| The audit metadata filter drops the key `bytes`. | `backend/app/services/audit.py:151-163` |
| `docs/permission-matrix.md` is generated and checked; it must not be hand-edited. | `docs/permission-matrix.md:1-4`; `scripts/p4/render_permission_matrix.py:29-71`; `backend/tests/test_authz.py:351` |

### What is being asked

The product owner has asked for images and PDFs to be previewable on phones, and has
confirmed that **Viewer**, through `file.browse`, may see them (#77). That widens what
`file.browse` authorises, and #77 requires the widening to be recorded, not inherited
silently. #77 also rules out three shortcuts: a `raw:true` flag on `filesystem.read`,
borrowing PR #71's download API or permission to fake an inline preview, and
"degrading" to sending the binary to the browser as a download when a safe preview is
not possible.

## Decision

### 1. A dedicated operation, not a flag and not a download

Add one operation family, `filesystem.preview_*` (§5), that is **read-only**, **typed** and
**allowlisted**. `filesystem.read` does not change: no field is added to its schema. It
is already `additionalProperties:false` (`contracts/v1/schemas/messages/filesystem-read.schema.json`),
and a new golden invalid fixture, `filesystem-read-with-raw.json`, pins that so a
future `raw:true` fails in all three consumers.

Why a flag is wrong, for the same reason ADR 0028 §1 gives for download: one type would
carry two policies, the binary deny at `read.go:74-79` would become conditional, and
the reader of that handler would have to keep both columns in their head. The opposite
direction matters too. The preview operation's allowlist check is **the** security
control on this path. It must be the default, not an `if`.

Why download is wrong: download (PR #71, ADR 0028 §4) returns an opaque attachment
whose whole purpose is to leave the platform. Preview returns bytes that the console
decodes and paints, and **offers no way to save them** (§11–§12). They are different
grants with different node switches (§9, §16).

### 2. The allowlist is closed and typed

The type is decided by the **daemon, from magic bytes and a structural parse**. The
extension and any client claim never decide it. The browser uses the extension only as
a routing hint, choosing which endpoint to ask; the daemon's verdict overrules it.

| Kind | MIME (wire enum) | Magic (offset 0) | v1 policy |
|---|---|---|---|
| image | `image/png` | `89 50 4E 47 0D 0A 1A 0A` | Static. APNG is accepted as PNG and shows its **default image only** (§11). |
| image | `image/jpeg` | `FF D8 FF` | Static. EXIF orientation is applied at decode. Metadata is not shown. |
| image | `image/webp` | `RIFF????WEBP` | Static. Animated WebP shows its first frame only. |
| image | `image/gif` | `GIF87a` / `GIF89a` | **First frame only**, never animated (OD-1, recommended default, approved 2026-09-27). |
| pdf | `application/pdf` | `%PDF-` | Paged, canvas-rendered, no active content (§12). |

Explicitly **not** in v1, and refused as `FILE_PREVIEW_UNSUPPORTED` / `unsupported_type`:
SVG (a script- and reference-bearing XML document, not a raster), HEIC/HEIF, AVIF, BMP,
TIFF, ICO, JPEG XL, PSD, and every other format. New formats need an amendment to this
ADR. "The browser can decode it" is not a reason to add one.

### 3. Daemon validation order (default-deny, same discipline as `Read`)

`files.PreviewOpen` sits beside `read.go` (and `download.go` if #71 lands) so the files
can be read side by side:

1. Node switch `filesystem.binary_preview.enabled` → else `FILE_PREVIEW_DISABLED`.
2. `SensitiveClassification(relPath)` → `FILE_DENIED` + classification (reuse,
   `read.go:18-20`).
3. **Pre-open type check.** `root.StatIn(relPath)` (`daemon/internal/workspace/root.go:196-212`,
   which calls `os.Root.Stat`), so it resolves in-root symlinks and refuses escaping ones
   like the open does. Anything but a
   regular file → `FILE_DENIED` / `not_regular`, **without opening it**. This spares a
   FIFO, socket or device node the open call and its side effects. It is advisory
   because it races with step 4, and step 5 is the binding check.
4. **Confined non-blocking open.** A new `Root.OpenFileNonBlocking(rel)` calls
   `os.Root.OpenFile(clean, O_RDONLY|O_NONBLOCK|O_NOCTTY, 0)`. Confinement is identical to
   `Root.OpenFile` (`root.go:100-118`): `..` and escaping symlinks are refused, and in-root
   symlinks are **followed**. The open is **not** `O_NOFOLLOW`. A symlink whose target
   stays in the root is caught by step 6, not by the open. `O_NONBLOCK` makes a FIFO
   swapped in after step 3 return immediately instead of waiting for a writer. It has no
   effect on reads from a regular file. Errors map through the existing
   `denyFromWorkspaceErr` (`read.go:95-112`), and outside-root collapses to `FILE_DENIED`.
   The existing blocking `Root.OpenFile` is left unchanged for `Read`. The pre-existing
   FIFO stall on the text path is a separate issue (Context).
   **If `O_NONBLOCK` passthrough cannot be verified on a platform, binary preview fails
   closed there.** On every supported build target (`linux/amd64`, `linux/arm64`), CI runs
   `TestOpenFileNonBlockingOnFifoReturns`. At start-up the daemon also probes a FIFO it
   creates in its own private state directory, never in a workspace. If that open does
   not return within 100 ms, the probe itself opens the write end, which releases the
   blocked open because the daemon owns both ends, so nothing is abandoned. The daemon
   then logs the failure and **omits `binary_preview` from its registration** (§9). There
   is no fallback that leaves a goroutine blocked in `open` on a workspace path. A bounded
   replacement would need its own design and review.
5. `f.Stat()` on the **fd**, then `IsRegular()` → `not_regular`, and `os.SameFile` against
   step 3's result → `FILE_PREVIEW_INVALID` / `changed` if the path was swapped between
   the two.
6. `root.RealRel(f)` → `SensitiveClassification(realRel)`. An unresolved name is
   denied (`read.go:49-55`). This is the check that makes following in-root symlinks
   safe: an innocuous `photo.png → .env` must fail here.
7. Read a 64-byte header from the same fd → sniff kind. Anything else is
   `FILE_PREVIEW_UNSUPPORTED`.
8. Kind-specific size cap on the fd snapshot size (§4) → `FILE_TOO_LARGE` + size. **No
   content beyond the header is read.**
9. Bounded read of the whole file from the same fd into memory (`LimitReader(cap+1)`).
   Reading more than `size` bytes, or a re-`fstat` whose size or mtime differs, gives
   `FILE_PREVIEW_INVALID` / `changed`.
10. Structural validation (§4). Failure gives `FILE_PREVIEW_INVALID` / `malformed`, or
    `FILE_PREVIEW_LIMIT` / `pixels|dimensions|complexity`. The daemon makes **no
    encryption judgement** (§4, OD-8).
11. Register an in-memory snapshot handle (§5) and answer `filesystem.preview_opened`.

Residual on the open: a character or block device node **inside** the workspace that
appears between step 3 and step 4 is still opened, non-blocking, before step 5 rejects it.
Creating one needs `CAP_MKNOD`, which the non-root `agentd` user does not hold (ADR 0023).
A privileged node's sudo-capable user could create one, and that user can already do
anything to the node. The worker is never held hostage either way, because a
non-blocking open does not wait.

File-level denials are **in-band** (`success:false` + `{code, reason}`), the same shape as
`filesystem.content` (`contracts/v1/fixtures/valid/filesystem-content-denied.json`),
because the console renders a denial pane. Node-level refusals, `FILE_PREVIEW_DISABLED`,
`FILE_PREVIEW_EXPIRED` and `NODE_BUSY`, are error frames, because they say nothing about
the file. Neither form ever carries content or an absolute path.

Structural validation is a **bounded header and marker walk, not a decode**. The daemon
never decompresses pixel data and never interprets PDF content streams. The one
exception is compressed **metadata**: PNG `iCCP`, `zTXt` and compressed `iTXt` are
separate deflate streams, so a 1 KiB chunk can expand to hundreds of MiB while every
pixel check passes. The daemon inflates each one with the standard library's
`compress/zlib` into a discard sink behind `LimitReader(budget + 1)`, only to measure
its expanded size. It sends the original bytes unchanged, never transcodes, and never
strips a chunk and forwards the rest. Rejecting every PNG that carries compressed
metadata was the alternative. It was not chosen because `iCCP` is common in ordinary
images: macOS and iOS screenshots usually embed a Display P3 profile, and editor exports
often carry one. That prevalence is **unmeasured** (`BP-OM-13`). JPEG APPn/COM segments,
WebP `ICCP`/`EXIF`/`XMP ` and GIF extensions are uncompressed, so they are bounded by
their length fields. The per-format budgets are in `plan/31/03-daemon.md` §2.1 (decision
D15). They are fixed technical ceilings, not a product option. Go's standard
`image/png`, `image/jpeg` and `image/gif` `DecodeConfig` read only headers. WebP needs a
small hand-written RIFF/VP8/VP8L/VP8X header reader, because `golang.org/x/image` is not a
dependency (`daemon/go.mod`) and this ADR adds none to the daemon.

### 4. Limits

All limits are daemon config with these defaults. The browser re-checks the ones it can
see, as defence in depth.

| Limit | Default (OD-2, recommended default approved 2026-09-27; still subject to `BP-OM-01`) | Enforced by | On breach |
|---|---:|---|---|
| Image file size | 8 MiB | daemon (fd size, before the full read) | `FILE_TOO_LARGE` + size + limit |
| Image pixels (w × h) | 16 777 216 (= 4096²) | daemon from header; browser before decode | `FILE_PREVIEW_LIMIT` / `pixels` |
| Image longest side | 8192 px | daemon; browser | `FILE_PREVIEW_LIMIT` / `dimensions` |
| JPEG scans (SOS markers) | 64 | daemon marker walk | `FILE_PREVIEW_LIMIT` / `complexity` |
| PNG chunks | ≤ 4096 chunks; one `iCCP` ≤ 1 MiB **expanded**; ≤ 64 `zTXt`/compressed `iTXt`, each ≤ 256 KiB compressed and ≤ 256 KiB **expanded**; all compressed ancillary ≤ 2 MiB compressed (checked before any inflate) and ≤ 2 MiB **expanded**; uncompressed text/`eXIf` ≤ 1 MiB; APNG ≤ 1000 frames within the canvas | daemon chunk walk plus bounded streaming inflate of compressed **metadata only** (never IDAT/fdAT) | `FILE_PREVIEW_LIMIT` / `complexity` |
| JPEG / WebP / GIF metadata | JPEG APPn+COM ≤ 2 MiB and assembled ICC ≤ 1 MiB; WebP `ICCP` ≤ 1 MiB and `EXIF`+`XMP ` ≤ 1 MiB, ≤ 1000 `ANMF` frames within the canvas; GIF extensions ≤ 1 MiB, ≤ 1000 frames within the screen | daemon length-field walk (all uncompressed) | `FILE_PREVIEW_LIMIT` / `complexity` |
| GIF | first image descriptor must exist and lie within the logical screen | daemon | `FILE_PREVIEW_INVALID` / `malformed` |
| PDF file size | 16 MiB | daemon | `FILE_TOO_LARGE` |
| PDF structure | `%PDF-` at offset 0; `%%EOF` in the last 1 KiB | daemon | `FILE_PREVIEW_INVALID` / `malformed` |
| PDF that needs a password to open | PDF.js asks for a password (`onPassword` / `PasswordException`) | **browser only**; no prompt is shown, and the load is destroyed | frontend state `pdf_password_required` |
| PDF encrypted with an empty user password (permissions only) | opens without a password | not refused (OD-8 (a), approved 2026-09-27) | renders view-only |
| PDF pages | 200 | **browser** (`numPages` before any page renders) | frontend state `pdf_too_many_pages` |
| PDF page render | canvas ≤ 16 777 216 px (scale clamped); 10 s per page | browser | `render_failed`, page-scoped |
| Transfer budget | 60 s total; 10 s per chunk; 15 s open | Central | `REQUEST_TIMEOUT` (stream aborted) |
| Concurrency | 2 opens and 4 live handles per daemon; 2 streams per user; 4 streams per node in Central | daemon + Central | `NODE_BUSY` / `FILE_PREVIEW_BUSY` (429) |
| Daemon snapshot memory | ≤ 32 MiB total across handles **and in-progress opens**; an open reserves its size before the full read | daemon | `NODE_BUSY` |

Two notes on these limits:

- **Why the page limit sits in the browser.** Counting PDF pages reliably requires
  parsing cross-reference streams and object streams, which means inflating
  FlateDecode data. That would put a PDF parser in the daemon, either a dependency
  (for example pdfcpu) or a hand-written one, running outside any browser sandbox. The
  daemon checks what can be checked from the file's envelope. PDF.js, inside the
  browser's renderer sandbox and a Web Worker, is the authority on pages and encryption.
- **Why the daemon makes no encryption verdict.** An earlier draft had it scan the file's
  tail for `/Encrypt`. That scan cannot tell a password-protected PDF from a
  permissions-only one (encrypted with an empty user password), and a textual scan can be
  fooled either way. It could not enforce either possible rule, so it is removed rather
  than presented as a check. The one rule that is enforceable without a PDF parser in the
  daemon is the renderer's: **a PDF that requires a password is refused and never
  prompted for**. A permissions-only PDF opens in any viewer, because permission bits
  restrict printing, copying and editing, never display. The preview offers none of those
  actions, so rendering it grants nothing its author withheld. Refusing it would instead
  be OD-8's alternative (b), which is enforceable only after the bytes have reached the
  browser. The cost is that a password-protected PDF is transferred to the browser before
  it is refused. The viewer is authorised to read that file, cannot decrypt it, and the
  bytes are disposed immediately (§14).
- **Why 16 777 216 px.** It is the maximum canvas area commonly reported for iOS Safari.
  **This figure is unverified** and must be measured on devices as `BP-OM-01` before the
  default is fixed.

### 5. Transport: an in-memory snapshot, pulled in bounded chunks, never written to disk

The contract (proposed v1.11.0) adds three request/response pairs that fit the existing
request-correlation relay unchanged:

| Request (Central → daemon) | Response (daemon → Central) | Notes |
|---|---|---|
| `filesystem.preview_open {session_id, path}` | `filesystem.preview_opened {success, preview_id, path, kind, mime, size, modified_at, chunk_size, chunk_count, width?, height?}` or `{success:false, path, error:{code, reason}}` | No `mime`, `kind`, `range`, `offset`, `raw` or `encoding` in the request. |
| `filesystem.preview_chunk {session_id, preview_id, index}` | `filesystem.preview_data {preview_id, index, data}` | `data` is canonical base64 of ≤ 512 KiB, so `maxLength` is 699 052. `preview_data` joins `LargeFrameTypes`. Its request stays on the 64 KiB bound. |
| `filesystem.preview_close {session_id, preview_id}` | `filesystem.preview_closed {preview_id}` | Idempotent. |

- **Snapshot, not ranged reads of a live file.** The daemon reads the whole bounded file
  once (§3 step 9), validates that exact buffer, and serves chunks from it. The bytes the
  browser receives are therefore the bytes that were validated. This answers ADR 0028
  §9's objection to ranged download ("what if the file changed between ranges") without
  a version precondition: the file is never re-read.
- **No disk.** The daemon holds the snapshot in memory. With the measured
  `BaseHTTPMiddleware` look-ahead, Central may hold up to two 512 KiB raw chunks
  per stream (1 MiB); size rollout capacity at 1 MiB per active stream, plus
  encoding and frame overhead. Central writes nothing to disk, database, log line
  or metrics label (ADR 0024 §5 applied to this path). The browser holds bytes in
  memory only (§14).
  The edge must not spool either: see §6.
- **Handle lifecycle.** `preview_id` is a ULID generated by the daemon. It is bound to
  `(session_id, this WebSocket connection)` and **never sent to the browser**. It is freed
  on `preview_close`, which Central sends at the end of **every** stream (success, error or
  cancellation, §6). It is also freed after 30 s idle or 120 s absolute, when the
  connection drops (the table is per connection), and when its session stops. Those four
  are backstops for a lost close, not the normal release path. A chunk request whose
  `session_id` does not match the handle's is refused `FILE_PREVIEW_EXPIRED`,
  indistinguishable from a handle that does not exist.
- **Off the dispatch loop.** Unlike `handleFsRead` (`connection.go:509`), preview
  handlers run on a bounded worker pool (§4 concurrency). A 16 MiB read plus validation
  must not stall terminal input and heartbeats on the same loop.
- **Why base64 in JSON control frames and not a new binary frame kind.** Binary kinds are
  an allowlist (1 = input, 2 = output) with a session-id header demuxed by the terminal
  path (`contracts/v1/fixtures/manifest.json` `binary`). A third kind would touch the
  terminal's hot path in all three consumers. Upload and download already chose base64
  JSON, and the ~33 % overhead is bounded by the 512 KiB chunk.
- **Why 512 KiB.** Preview frames share the WebSocket with terminal output. A smaller
  chunk bounds head-of-line delay for the terminal. Terminal latency under preview load
  is measured as `BP-OM-05`.

### 6. Central endpoint: the path travels in a body, never in a URL

```
POST /api/sessions/{session_id}/files/binary-preview
Content-Type: application/json
{"path": "<workspace-relative>"}          (body ≤ 24 KiB, enough for a 4096-code-point
                                          UTF-8 path; unknown keys and any query string rejected)
```

**Why a POST body and not `?path=`.** A URL is written down by every hop that logs
requests. Today that includes both nginx configs (`"$request"`, `nginx.conf:52-55`,
`railway/nginx.conf.template:64-67`), uvicorn's access log, which includes the query
string (Context), Railway's edge, which we do not configure (`BP-OM-10`), and any future
proxy, CDN or WAF. Suppressing logging at each hop would make "no path in any log" depend
on every hop staying configured, including one we cannot configure. A request body is not
logged by nginx's format, by uvicorn, or by the RBAC-denial middleware, which records the
URL path only (`middleware.py:153-157`). With the path in the body, the URL carries
nothing but the session id, which every other session route already logs.

Three options were weighed:

| Option | Path in any URL? | Cost | Verdict |
|---|---|---|---|
| `GET ?path=` + `access_log off` / query-less format at every hop | yes, unless every hop is configured | Correctness depends on configuration we do not fully control (the Railway edge). A query-less format also hides the path from Railway's HTTP logs only if Railway itself logs no query, which is unknown. | rejected as the primary control; kept as defence in depth (below) |
| **`POST` + JSON body** | **no** | A read expressed as POST: not cacheable (wanted: `no-store` anyway) and not retried by proxies (wanted). The RBAC-denial middleware now counts an action-level 403 here as a "mutation" denial (`middleware.py:156`), but all three roles hold `file.browse`, so an action-level refusal cannot happen for a real role. A scope refusal was audited for GET as well. | **chosen** |
| `POST` → opaque handle, then `GET /…/{handle}` | no (the handle is opaque) | Central-side handle state, which may not be shared across processes (`BP-OM-09`); replay and binding rules for the handle; a second round trip. Its only gain is a GET-able URL, which would enable `<img src>`, and §11 does not want that. | rejected |

**CSRF.** Authentication is a Bearer header added by script (`client.ts:654`). A cross-site
form or `fetch` carries no credentials, so it is refused with 401, and a JSON
`Content-Type` would need a CORS preflight that Central does not grant (no
`CORSMiddleware` in `backend/app`). The route also **requires** `Content-Type:
application/json` and refuses other bodies with 415, so a `text/plain` "simple request"
cannot reach the handler either.

**Defence in depth at the edge.** The dedicated nginx location (below) logs with its own
format, `'$remote_addr - $status "$request_method $uri" rt=… nginx_req_id=$request_id'`.
It never uses `$request` or `$args`, so a query parameter added by mistake later is still
not written down.

Processing:

1. `require_action(FILE_BROWSE)`, then `_resolve()`: session exists, `authorize_file_browse`
   (Viewer included; shell sessions refused), node connected (`services/files.py:182-198`).
2. The rollout flag `binary_preview_enabled` must be on, and the **live** connection's
   registration must report `binary_preview: true` (§9). Otherwise
   `FILE_PREVIEW_UNSUPPORTED_NODE` (409), **before** any frame is sent.
3. Parse the body (JSON object with exactly `path`), then `_reject_rel_path(path)`
   (`services/files.py:90-121`).
4. Per-user and per-node stream limit.
5. `preview_open` (15 s). On an in-band denial the service returns a **denial result**
   instead of raising. A sensitive denial is recorded through the existing
   `_maybe_audit_denied` (unchanged). The route then **commits the session** and only
   afterwards raises the `ApiError`, whose code is the daemon's code and whose `details`
   carry `{reason, size?, limit?}`. This mirrors the existing content route, which commits
   the audit entry `read_file` added (`files.py:212-215`). Raising first would discard the
   row, because `AuditService.record` only adds it to the session (`audit.py:204-210`) and
   `get_session` does not commit (`db/engine.py:96-98`).
6. On success, a `StreamingResponse` whose generator requests chunk *i + 1* only after
   chunk *i* has been handed to the ASGI `send`. That is real pull-based backpressure,
   unlike the single-frame case ADR 0028 rejects streaming for. It is **unverified through
   `RequestIdMiddleware`**, a `BaseHTTPMiddleware` (`middleware.py:41`) that sits between
   the route and the server (`BP-OM-11`). The generator's `finally` **always** sends
   `preview_close`: after the last chunk on success, on a node or timeout error, and on
   client cancellation. A completed stream therefore frees its daemon snapshot at once,
   rather than holding one of the four handles and up to 32 MiB (§4) for the 30 s idle TTL.
   The TTL is a backstop for a close that is lost, for example on a Central crash. A
   client disconnect cancels the generator, and `_observe` already records `CANCELLED`
   (`services/files.py:220-224`).
7. The success audit (§10) is written **after the server-facing ASGI `send` returns for the last chunk**, on its
   **own short-lived session** (`get_database().session()`), the same pattern the
   RBAC-denial middleware uses (`middleware.py:126-127`, `:171`). It is not written on the
   request-scoped session, whose lifetime relative to a streamed body depends on
   FastAPI's dependency-exit timing (FastAPI 0.120.1 here) and is not relied on.
   An outer ASGI middleware observes that send beyond `RequestIdMiddleware`'s body buffer.
   The write is shielded from disconnect cancellation and bounded by a short timeout;
   a timeout is counted and logged without a path. The generator can be cancelled
   before resuming after its final `yield`, so it cannot own this audit.

Response headers, as a set:

| Header | Why |
|---|---|
| `Content-Type: application/octet-stream` | The console decodes by the sniffed MIME it received separately, so the body is never given a renderable type. |
| `X-Content-Type-Options: nosniff` | Stops a browser from overruling the line above. |
| `Content-Length: <size>` | A stream cut short (node lost, timeout) becomes a **network error** in `fetch`, never a partially painted image or PDF. |
| `Cache-Control: no-store, private` and `Vary: Authorization` | No shared or browser HTTP cache keeps a user's file (cache poisoning, cross-user leakage). |
| `Cross-Origin-Resource-Policy: same-origin` | No other origin can embed it. |
| `Content-Security-Policy: sandbox; default-src 'none'` | If the response is ever navigated to, nothing in it runs. |
| `X-Cliora-Preview-Mime`, `-Kind`, `-Width`, `-Height` | The daemon's verdict, which the renderer uses to pick a decoder. Values come from the wire enum only. |

There is **no `Content-Disposition`**: this is not a download and must not look like one.
Navigation cannot reach the endpoint anyway: it is a POST, and authentication is a Bearer
header (`client.ts:654`). A RED test pins that a request carrying cookies but no
`Authorization` header gets 401.

**Edge buffering.** `location /api/` has `proxy_buffering on` with no
`proxy_max_temp_file_size` (`nginx.conf:174`). Per nginx's documented defaults (**unverified
in this deployment**), a proxied body larger than the in-memory buffers spills to
`proxy_temp` files, which would break "no disk". A dedicated
`location ~ ^/api/sessions/[^/]+/files/binary-preview$` sets `proxy_buffering off` and
`proxy_max_temp_file_size 0`, the query-less log format above, and
`client_max_body_size 24k` with `client_body_buffer_size 32k`. The request body is where the
path now travels, and nginx writes a body larger than its buffer to `client_body_temp`, so
the buffer must exceed the limit. These go in both
`deploy/nginx/nginx.conf` and `deploy/railway/nginx.conf.template`. The existing
text-preview path has the same spill exposure today; this ADR only records it.

**Release gate: the no-persistence and no-path-in-logs claims.** Neither claim may appear
in the PRD, the release note or the UI until **both** of the following hold for **every**
deployment topology that ships, meaning the compose/nginx deployment and Railway:

1. `BP-OM-06` shows that no preview byte lands in `proxy_temp` (or any other file) at
   the nginx edge, and that the Railway edge in front of it neither spools the body to
   disk nor logs it.
2. `BP-OM-10` shows that no workspace path appears in any access log. A canary request
   whose path contains a distinctive marker (for example
   `bp-canary-<random>/機密-<random>.pdf`) is sent, and that marker is then searched for,
   **both raw and percent-encoded**, in: the nginx access log of each topology,
   uvicorn/Central stdout, Central's JSON correlation log, the audit table, and Railway's
   HTTP and deploy logs. Every search must return zero hits.

**Until both are proven for a topology, the Central flag stays OFF on that topology**
(OD-11 (a), approved 2026-09-27). That includes Railway, whose own edge we do not configure,
and any other edge in front of Central. Turning the flag on with a scoped claim instead is
not a release-time choice. It requires the product owner to **change `FR-FILE-012.AC-09`
explicitly**, recording which component is outside the no-persistence guarantee.

### 7. Authorisation: `file.browse`, per request, and what the widening is and is not

- **Who.** Admin, Developer and **Viewer**: any holder of `file.browse` with view access
  to the owning, non-shell session (`authz.py:154-165`). There is no new RBAC action. The
  reasons are ADR 0028 §5's: three fixed roles cannot express "text but not images", and
  splitting the action would split every "who read this workspace" query.
- **When.** Every HTTP request is authorised from scratch. The browser never holds a
  `preview_id`, so it cannot replay a chunk or continue a transfer after its authority
  changed. Residual: a role revoked *during* a transfer is honoured at the next request,
  at most 60 s (§4) later.
- **The widening, stated plainly.** Before: `file.browse` let a Viewer see UTF-8 text up
  to 2 MiB. After: it also lets a Viewer **see** allowlisted images and PDFs up to the §4
  limits, rendered in the console. It does **not** grant download. The console offers no
  save, share, open-in-new-tab, print or copy-image affordance for these previews (§11,
  §12), and the node switch for preview is separate from #71's `file_download`. It is also
  not DRM: pixels on a screen can be photographed, and devtools can read memory. The
  boundary is "the platform is not the mechanism for taking a copy", the same property
  ADR 0028 §3 uses.
- The sensitive-name policy is **the same function, called twice** (§3 steps 2 and 6).
  No preview-specific exemption exists or may be added.

### 8. Session and node binding

- Central resolves `session → node_id` once per HTTP request and sends every frame of
  that transfer to that node only.
- The daemon binds a handle to `session_id` and to its connection, as §5 describes. A
  reconnect gives a new table, and old ids become `FILE_PREVIEW_EXPIRED`.
- `session.stop` for a session drops its handles.
- The browser request carries the **exact** session id currently shown. The frontend
  drops any response for a session it no longer shows, using the rule that already
  exists at `frontend/src/stores/files.ts:199-202` (§14).

### 9. Capability negotiation: three gates, and an old daemon is never asked

| Gate | Owner | Default | Absent means |
|---|---|---|---|
| `binary_preview_enabled` (Central setting, the rollout flag) | operator | **off** (OD-5) | off |
| `node-register.binary_preview` (optional, **`const: true`**) ← daemon config `filesystem.binary_preview.enabled` | node owner | daemon default `true` (OD-5) | **false**. This is what an old daemon sends, and what a new daemon sends when disabled (below) |
| `may_browse_files(user, session)` | RBAC | — | — |

`SessionCapabilities.can_preview_binary = flag ∧ live_registration.binary_preview ∧ may_browse_files`.
It is computed in `authz.session_capabilities` next to `can_browse_files`
(`authz.py:309-316`), and reaches every session response through
`SessionCapabilities` / `_capabilities` (`backend/app/api/http/schemas.py:90-110`,
`:164-169`), which every `SessionSummary` / `SessionDetail` passes through
(`schemas.py:150`, `:160`; call sites `backend/app/api/http/sessions.py:72`, `:90`, `:101`,
`:118`, `:155`). `_capabilities` reads the live bit from the process registry
(`get_node_registry()`, the accessor `FileRelayService` already uses) and the flag from
settings, so no call site changes signature. The live bit is set where `node.register` is
parsed (`backend/app/api/ws/nodes.py:91-114` `_register_input`, `:203-209`) and cleared
when that connection closes.

**The field is omitted when disabled, never sent as `false`.** A new daemon whose switch is
off sends a `node-register` **byte-identical in shape to 1.10.0's**. The schema makes that a
wire rule rather than a habit: `binary_preview` is `{"const": true}`, so `false` is
**invalid** in all three consumers and a daemon bug that emits it fails the shared
fixtures. The reason is rollback. An old Central's strict schema rejects the *key*
regardless of its value, and it does so silently (Context: the register is skipped, the
connection stays up, nothing is persisted). A disabled daemon therefore has to look like
an old one.

- **The authoritative check uses the live connection's registration.** Today the
  registry tracks connectivity only (`backend/app/services/registry.py:185`,
  `is_connected`), so it must be **extended** to keep the `binary_preview` bit of the
  registration that opened the current connection, and to forget it when that
  connection closes. The persisted column (a proposed migration after #71's `0021`, `server_default=false`,
  following `models.py:98-107`) is for display and fleet queries only. A daemon that
  reconnects downgraded is therefore refused immediately, not after the next DB write.
- **An old daemon never receives `filesystem.preview_*`.** It would drop the frame
  silently (`codec.go:87`, `connection.go:491-494`) and the user would wait for a
  timeout. Central refuses first, with `FILE_PREVIEW_UNSUPPORTED_NODE`.
- **A new browser against an old Central** reads `can_preview_binary` as absent, so
  false, and keeps today's `FILE_BINARY` denial pane (`PreviewDenied.vue`).
- **A new, enabled daemon against an old Central.** `node-register` is
  `additionalProperties:false` (`node-register.schema.json:3`), so the old Central's
  validator rejects the message (`codec.py:100-102`). The WebSocket route skips it with no
  reply (`ws/nodes.py:199-202`), and the daemon ignores acks anyway (`connection.go:474-475`).
  The failure is **silent and partial**: the node shows as connected, but its
  registration, meaning daemon version, runtimes, workspace roots and posture, is not
  updated. This was established by reading code (it resolves the former `BP-OM-08`) and is
  confirmed by a test in `BP-02`. It is why the forward order is fixed as
  **contract → Central (+ frontend) with the flag off → daemons → flag on**, the same
  constraint every additive `node-register` field has carried.
- **Rolling Central back.** The old Central accepts a new daemon **only if that daemon
  omits the field**. The documented rollback is therefore:
  (1) turn the Central flag off, which is instant and needs no daemon change;
  (2) to go further and roll back the Central **version**, first set
  `filesystem.binary_preview.enabled: false` on every node and restart `agentd`, **or**
  roll those daemons back;
  (3) confirm each node's registration was **freshly accepted**. `daemon_version` is not
  proof, because a restart keeps the same version and `persist_registration` simply
  reassigns it (`backend/app/services/nodes.py:252`). `last_seen_at` is not proof either,
  because heartbeats also bump it (`nodes.py:324`, `:353`), and `registered_at` is set once
  at creation (`models.py:79-81`). Two registration-specific signals are used instead.
  **On the new Central**, a new column `nodes.last_registration_at` (timestamptz, nullable,
  migration `0022`, set **only** in `persist_registration`, exposed read-only in the node
  API) must advance past the time recorded before the restart. **On the old Central**,
  which lacks that column, the drill changes the daemon's `node.name`
  (`daemon/internal/config/config.go:30`, sent at `connection.go:407`) to a one-off marker
  together with the switch change. The old Central persists `name` only on an accepted
  registration (`nodes.py:247`), so the marker appearing in the node list proves
  acceptance while `daemon_version` stays unchanged. The name is restored afterwards;
  (4) then roll back Central.
  Rolling back Central with enabled new daemons still connected is the silent-staleness
  failure above, and the runbook says so. Tests that make this rollback checkable:
  `TestRegisterOmitsBinaryPreviewWhenDisabled` (daemon); a compat test in `BP-02` that
  validates a disabled daemon's register payload against the **1.10.0
  `node-register` surface** derived from the frozen 1.9.0 copy plus `file_download`,
  which must be accepted, and an enabled one, which must be rejected; and a staging rollback drill (`plan/31/08-device-matrix-and-rollout.md` `BP-11` §2).

### 10. Audit and observability: no path, no content

- **Sensitive denial**: the existing `file.sensitive_read_denied` with `{classification, extension}`
  (`services/files.py:482-523`), unchanged and shared.
- **Success** (OD-6 (a), approved 2026-09-27: **yes**): a new audit action `file.binary_preview` with
  caller-supplied metadata `{kind, mime, size_bytes}` plus the usual user, session and node
  ids. `AuditService.record` adds the correlation key `request_id`, or `source` when there
  is none (`audit.py:196-201`), and that key is allowed. There is **no path, no filename,
  no extension and no content**. `bytes` must not be the key, because the audit filter
  drops it (`audit.py:159`). The success row is written on its own short-lived session
  after the last chunk's server-facing ASGI send returns (§6 step 7).

  Why record success when text preview does not: this is a deliberate expansion of what
  Viewers can see, and "did Viewers use it, on which sessions" has to be answerable
  without a log that holds paths.
- **Correlation log and metrics**: ids, `kind`, outcome code, reason, chunk count, bytes and
  duration, through the existing `_observe` (`services/files.py:200-251`). Never the path,
  never a digest of the content. Daemon metrics follow the `filesystem_*` naming
  (`files_handlers.go:108-117`), with `op="preview_open|preview_chunk"`.

### 11. Images: decoded to a canvas, never to an `<img>` with an object URL

The renderer decodes with `createImageBitmap(new Blob([bytes], {type: mime}), {imageOrientation: "from-image"})`
and paints to a `<canvas>`, which gets `role="img"` and an `aria-label` naming the file and
its dimensions.

- **The GIF first-frame policy falls out of the platform.** For an animated image,
  `createImageBitmap` takes the format's default image, or else the first frame (HTML
  Standard, "ImageBitmap"). APNG and animated WebP behave the same way. No per-format code
  is needed.
- **No `img-src` change.** Decoding a Blob in script is not a subresource fetch, so the
  current `img-src 'self' data:` (`nginx.conf:134`) stands. **Unverified on iOS Safari**
  (`BP-OM-02`). If a device needs an `<img>` fallback, the only permitted CSP change is
  adding `blob:` to `img-src`, and it needs its own review.
- **No save affordance.** A canvas gives no "save image", drag-out or "open image in new
  tab" menu, where an `<img>` would. On iOS a long-press on `<img>` offers "Save to
  Photos", which is a download under another name, and #77 forbids that. Long-press
  behaviour on a canvas is measured as `BP-OM-03`.
- Fit-to-width by default. Zoom uses buttons (＋ / − / fit) and pinch through pointer
  events on the canvas container, clamped so the backing canvas never exceeds the §4
  pixel limit. Page-level pinch zoom is not disabled (`index.html:10-11` does not set
  `user-scalable=no`, and this ADR does not add it).

### 12. PDF: PDF.js display layer only, in a worker, with no active content

**Choice: `pdfjs-dist` (Mozilla PDF.js), core display API only**, lazy-loaded as its own
chunk when the first PDF opens, the same way Monaco stays out of the initial bundle.
Its evaluation:

| Question | Finding | Status |
|---|---|---|
| Licence | Apache-2.0 | to confirm on the pinned version's `LICENSE` in `BP-07` |
| Version | Pin an exact release that is patched for **every** published PDF.js advisory at implementation time. As of 2026-09-27 that means **≥ 6.2.108**. That covers CVE-2024-4367 / GHSA-wgrm-67xf-hhpq (script through a crafted font when `isEvalSupported` is true; fixed in 4.2.67) and **CVE-2026-16633 / GHSA-hq66-cqwq-w95j** (script execution when scripting is enabled, the default, and no CSP restricts `script-src`; affects `>= 5.6.83, < 6.2.108`, first patched 6.2.108). The second was verified against the GitHub Advisory API on 2026-09-27. | `BP-07` re-checks the advisory database on the day of pinning and again at release (a gate) |
| Third-party service | None. The library, worker, cMaps, standard fonts and any `.wasm` are self-hosted build assets | required |
| Worker | module worker from a same-origin asset, allowed by `worker-src 'self' blob:` | expected to fit the current CSP |
| `eval` / `new Function` | `isEvalSupported: false`. The CSP also has no `'unsafe-eval'`, a second layer | required |
| WebAssembly decoders (JPX, ICC) in recent versions | same-origin `wasmUrl`, allowed by `script-src 'wasm-unsafe-eval'` (already present) and `connect-src 'self'` | **unverified** (`BP-OM-04`) |
| Fonts | embedded fonts through the FontFace API from in-memory data; `font-src 'self' data:` already present | **unverified** (`BP-OM-04`) |
| Browser floor | Recent releases target modern engines. Older iOS Safari may need the legacy build | **unverified**, and a product decision (OD-9) |
| Bundle | not measured. Expect ~1 MB+ for the worker, in a lazy chunk | measured in `BP-07` |

**Configuration (all required):** pass the bytes as `data` (no URL, so no range or stream
fetching), with `isEvalSupported: false`, `enableScripting: false` wherever the pinned
release accepts it (which API layer consumes it is **verified in `BP-07`**; the structural
control stays that no scripting bundle is shipped), `enableXfa: false`,
`annotationMode: AnnotationMode.ENABLE` (appearance streams are painted, forms are not
interactive), `disableAutoFetch: true`, `disableStream: true`, `disableRange: true`,
`stopAtErrors: true` for structural errors (**to verify** that this does not reject
common benign PDFs), and self-hosted `cMapUrl`, `standardFontDataUrl` and `wasmUrl`.
The PDF.js *viewer* application (`web/viewer.html`) is **not** used. It brings download,
print, open-file, the scripting sandbox and an annotation DOM layer.

**Active content.**

- **JavaScript**: not executed. The display API does not run document JavaScript, and
  the scripting bundle (`pdf.scripting` / sandbox) is not shipped.
- **Links** (URI, Launch, GoToR, GoToE): no annotation layer DOM is created, so nothing
  is clickable, and no navigation, `window.open` or fetch can originate from a document.
  Internal GoTo links are also inert in v1 (OD-4).
- **Forms / XFA**: not interactive, XFA disabled, nothing submitted.
- **Embedded files and attachments**: not listed and not extractable.
- **Encrypted documents** (OD-8): a PDF that needs a password to open is refused as
  `pdf_password_required`. The `onPassword` callback destroys the loading task
  instead of prompting, so no password field ever exists. A permissions-only PDF
  (empty user password) renders view-only. No layer claims to detect encryption before
  transfer (§4).
- **Text layer / selection / search**: **not in v1** (OD-3). Pages are canvases with
  `aria-label="第 n／N 頁"`.

  The accessibility cost is real: a screen reader cannot read PDF text in v1. The
  denial copy and the release note must say so.

**Rendering.** A single page at a time plus one neighbour, with at most 3 live canvases,
page-number navigation (prev / next / go-to), fit-to-width and zoom. The scale is clamped
by the pixel limit, each page has a 10 s timeout, and a cancelled or timed-out render calls
`RenderTask.cancel()`. `loadingTask.destroy()` / `pdf.destroy()` terminates the worker on
close, on switch and on auth loss (§14).

### 13. CSP

**No change is expected.** The current policy (`nginx.conf:134`) already has `'self'`
workers, `'wasm-unsafe-eval'`, `data:` fonts, `object-src 'none'` and no external origin,
and this ADR adds no external origin, no `unsafe-eval`, no `blob:` in `img-src` and no
`frame-src`. Every "no change" row is verified in `BP-07` by running the built bundle under
the real header (`frontend/tests/e2e/theme.spec.ts:138` is the precedent for CSP-in-E2E).
Any change it finds needs a separate review, and must never add a third-party origin.

### 14. Memory, cache and cleanup: nothing outlives the session, the user or the file

- **One owner.** A single composable (proposed `useBinaryPreview`) owns the
  `AbortController`, the `Uint8Array`, the `ImageBitmap`, the PDF.js loading task or
  document, and every canvas. A small store exposes `clear()` so that non-component
  owners (auth loss) can dispose it. Large objects are `markRaw` and never reactive.
- **No persistence and no shared cache**: no Service Worker, IndexedDB, Cache Storage,
  `localStorage` or HTTP cache (`no-store`). The in-memory cache holds **only the preview
  on screen**. Reopening fetches again. Monaco's 8-entry LRU does not extend to binaries,
  because phone memory is the constraint.
- **Object URLs: none by design** (§11, §12). If a device fallback ever needs one, the
  same owner creates it and revokes it on every trigger below.
- **Disposal triggers**, each of which clears **before** the next state renders (the
  plan/29 MS-16 "先清再換" rule): preview path change; close; session id change;
  component unmount; `can_preview_binary` becoming false; sign-out; a user-id change;
  and, on identity-pending, aborting in-flight work only. The last three reuse the #76
  auth-loss pattern: synchronous watchers on `isAuthenticated`, `user.id` and
  `identityPending` that call the stores' public reset. That pattern currently exists on
  **unmerged** branch `fix/mobile-file-browser-76` @ `a453bd4`
  (`frontend/src/router/authLoss.ts:80-97`, `:104-123`, `:130-136`). This ADR depends on it
  landing, not on its exact code.
- **Disposal actions**: abort the fetch; `bitmap.close()`; set each canvas to 0 × 0;
  `renderTask.cancel()`; `pdf.destroy()` (which terminates the worker); drop the
  `Uint8Array`; reset the state.

### 15. Cancellation and concurrency

Browser abort (back, switching file or session, auth loss) → `fetch` abort → Starlette
cancels the generator → `preview_close` → the daemon frees the snapshot. If the close is
lost, the idle TTL frees it. An open that the browser abandoned before `preview_opened`
arrived leaves a handle that only the TTL frees, bounded by the 4-handle and 32 MiB caps.
A second open from the same tab aborts the first (supersede). Limits are listed in §4. All
refusals are `NODE_BUSY` or 429, never a hang.

### 16. Relationship to download (PR #71, ADR 0028 as proposed there)

| | Binary preview (this ADR) | Download (PR #71) |
|---|---|---|
| Types | allowlist of 5 | anything non-sensitive |
| Output | decoded and painted, no save affordance | opaque attachment saved to disk |
| Node switch / report | `filesystem.binary_preview.enabled` / `binary_preview` | `filesystem.download.enabled` / `file_download` |
| Audit | `file.binary_preview`, no path | `file.download`, with path |
| Sensitive policy | the same function, twice | the same function, twice |

Neither switch implies the other. A RED test runs both on one node in both combinations:
preview works while download is disabled, and the reverse. The denial pane never
offers download *because* preview failed. If #71 lands, the pane may offer it only under
#71's own `can_download` condition, and never as a fallback for a preview that
was refused as unsafe (`FILE_PREVIEW_LIMIT`, `FILE_PREVIEW_INVALID`), which #77 rules out.
No message name, capability flag, config key, audit action or migration is shared.

## Threat model

Assets: workspace file bytes; the secrecy of sensitive files; the console origin (its
tokens and DOM); Central, daemon and phone availability; the separation between users and
between sessions.

| # | Threat | Vector | Control (section) | Residual | RED test / fixture |
|---|---|---|---|---|---|
| T1 | PDF active content runs as the console | JavaScript, URI/Launch links, forms/XFA submit, embedded files | display API only, no scripting bundle, no annotation DOM, `enableXfa:false`, `isEvalSupported:false`, CSP with no `unsafe-eval` and `form-action 'self'` (§12, §13) | a PDF.js bug that escapes into the page. Mitigated by the pinned floor version, worker isolation and CSP | `pdf-with-js.pdf`, `pdf-with-uri-link.pdf`, `pdf-with-launch.pdf`, `pdf-with-form-submit.pdf`, `pdf-with-attachment.pdf`: nothing navigates, fetches, opens a window or creates an `<a>` |
| T2 | Known PDF.js code-execution bugs (CVE-2024-4367 font class; CVE-2026-16633 scripting class) | crafted FontMatrix; document scripting | pin ≥ 6.2.108 and patched for every published advisory; `isEvalSupported:false`; `enableScripting:false`; no scripting bundle; CSP without inline or eval script | a future bug of the same class | the CVE's public proof-of-concept shape as a fixture: no script executes under the real CSP |
| T3 | Decompression or pixel bomb | PNG 50 000 × 50 000 with a tiny IDAT; a JPEG with huge SOF dimensions or thousands of progressive scans; a GIF whose frame exceeds the logical screen; a ~1 KiB PNG `iCCP`/`zTXt` that inflates to hundreds of MiB; oversized JPEG/WebP/GIF metadata | daemon header and marker walk with pixel, side and scan limits, plus expanded-byte budgets for compressed PNG metadata and length budgets for other metadata, all before transfer; the browser re-checks the headers before decode (§3, §4) | a browser decoder bug on a file inside the limits | `png-bomb-50k.png`, `jpeg-sof-65535.jpg`, `jpeg-1000-scans.jpg`, `gif-frame-outside-screen.gif`, `png-iccp-bomb.png`, `png-ztxt-bomb.png`, `jpeg-icc-over-budget.jpg`, `webp-iccp-over-budget.webp`, `gif-ext-over-budget.gif`: all `FILE_PREVIEW_LIMIT`/`INVALID`, and none reaches the browser |
| T4 | PDF resource exhaustion in the browser | 10 000 pages; huge MediaBox; a pathological content stream | page limit before render; clamped scale; per-page timeout plus cancel; worker terminated on leave (§4, §12) | one tab's worker slows until the timeout | `pdf-10000-pages.pdf`, `pdf-huge-mediabox.pdf`, `pdf-slow-content.pdf` |
| T5 | Parser vulnerability in the daemon | malformed headers | header-only parsing in a memory-safe language, bounded buffers, no new daemon dependency, a fuzz target per sniffer (§3) | a panic, recovered per request | `go test -fuzz` targets for the PNG, JPEG, GIF, WebP and PDF envelope checks; truncated and garbage corpus |
| T6 | Parser vulnerability in the browser | a valid-looking file that exploits the image or PDF decoder | the browser's own sandbox; PDF.js in a worker; allowlist of 5 formats; SVG excluded | an engine zero-day, out of our control | allowlist fixtures only; `.svg` is refused `unsupported_type` |
| T7 | Wrong-magic or polyglot | `evil.png` that is HTML, SVG or PDF; a PDF+ZIP polyglot | the type comes from magic, not the extension; the body is `octet-stream` + `nosniff` + `CSP: sandbox`; decoding is chosen by the daemon's MIME; no `<iframe>`/`<object>`/`<embed>` (§2, §6) | a polyglot that is valid as its sniffed type renders as that type only | `html-named.png`, `svg-named.png`, `pdf-named.jpg`, `zip-pdf-polyglot.pdf` |
| T8 | Sensitive-file exfiltration through the new path | `.env.png`; `id_rsa.pdf`; an in-root symlink `photo.png → .env`; a file under `.ssh/` | the same `SensitiveClassification`, twice, the second time on the fd's resolved name (§3, §7) | none beyond the policy's own coverage | `symlink-to-dotenv.png`, `dotenv-named.png`, `.ssh/diagram.png`, `secrets-report.pdf`: all `FILE_DENIED` and audited |
| T9 | Escape from the workspace, or a special file | `../`, an absolute path, a symlink out of the root, a FIFO, socket or device | wire pattern, `_reject_rel_path`, `os.Root` confinement (escaping symlinks refused, in-root ones followed and then re-checked through `RealRel`), pre-open `Stat` type check, **non-blocking** open, regular-file and `SameFile` check on the fd (§3) | a device node created between `Stat` and open needs `CAP_MKNOD` (§3) | reuse the existing escape fixtures, plus `symlink-outside.pdf`; **two FIFOs opened concurrently, then a third legitimate request, all complete under a 2 s deadline**; a FIFO swapped in between `Stat` and open is still refused without blocking |
| T10 | Cache poisoning / cross-user leakage | shared proxy cache; browser HTTP cache; an in-memory cache keyed by path | `no-store, private` + `Vary: Authorization`; no Service Worker or IndexedDB; the only in-memory item is the current one, wiped on user change (§6, §14) | — | a test that user B, on the same tab after a user switch, sees no bytes from user A; header assertions |
| T11 | Cross-session leakage | a late response for session A painted while B is shown; a `preview_id` reused across sessions | exact-session request and late-drop rule; handle bound to session and connection; the id never reaches the browser (§8, §5) | — | switch sessions mid-transfer: A's bytes are never painted; forged cross-session chunk → `FILE_PREVIEW_EXPIRED` |
| T12 | Viewer privilege expansion beyond the grant | Viewer uses preview as download; Viewer reaches a shell session's files; preview enables download | no save affordance; shell refused (`authz.py:163-164`); separate switches; the widening recorded in PRD, release note and matrix (§7, §16) | screenshots and devtools (not DRM) | a role matrix for Viewer/Developer/Admin × allowed/denied; the cross-switch test from §16 |
| T13 | DoS on node, Central or WebSocket | parallel opens; slowloris clients; huge PDFs; terminal starvation | concurrency limits, snapshot memory cap, TTL, 512 KiB chunks, worker pool off the dispatch loop, transfer budget (§4, §5, §15) | a legitimate user who hits the limits sees `NODE_BUSY` | a concurrency test (N+1 → 429 / `NODE_BUSY`); a slow reader aborted at 60 s; terminal echo latency under load (`BP-OM-05`) |
| T14 | Old daemon or old Central mismatch, including rollback | new Central sends an unknown type; an enabled new daemon registers with an old or rolled-back Central, and its registration is silently skipped | gate on the live registration; deployment order; the field is omitted when disabled (`const: true`), so a disabled daemon registers with an old Central (§9) | an operator rolling Central back without disabling or rolling back daemons first | a new Central with a fake old daemon never sends `preview_*`; the 1.10.0 schema derived from the frozen 1.9.0 copy accepts a disabled daemon's register and rejects an enabled one; `false` is invalid; staging rollback drill |
| T15 | Leaking a path or content through telemetry | logs, metrics labels, audit, error messages | ids, kind and counts only; `ApiError` messages are fixed strings (§10) | — | a log-capture test asserts that no path or filename substring appears for a request on `secret-project/plan.pdf` |
| T16 | Silent degradation to download | a fallback that sends the file when rendering fails | no `Content-Disposition`; no save UI; the denial pane has no "download instead" for unsafe refusals (§6, §16) | — | a frontend test: on a `render_failed`/`LIMIT`/`INVALID` state no `<a download>` exists and no blob URL was created |
| T17 | Workspace path written to an access log | `?path=` in a URL recorded by nginx `$request`, uvicorn's access log, the Railway edge or a future proxy | the path travels in a POST body; the dedicated nginx location logs `$request_method $uri` only; release gate on `BP-OM-06` / `BP-OM-10` (§6) | the Railway edge, until measured; the **pre-existing** GET file routes (`/content`, `/tree`, `/search`) still log paths and keywords (Context) | canary path with a distinctive marker, searched raw and percent-encoded in both nginx logs, uvicorn/Central stdout, the Central JSON log, the audit table and Railway's logs: zero hits |

## Consequences

- Phones and desktops can view the five allowlisted types without leaving the console.
  Desktop is included (OD-7 (a), approved 2026-09-27), through one renderer.
- **What `file.browse` authorises widens, including for Viewer.** This must be the first
  paragraph of the release note and must appear in the generated permission matrix. It
  cannot be a footnote.
- Three new moving parts that text preview never had: a daemon snapshot table with TTLs, a
  streaming Central endpoint, and a PDF.js dependency with its own supply chain and
  CVE-watch obligation. All three have explicit owners in `plan/31`.
- The existing `FILE_BINARY` pane stays for everything outside the allowlist, and for
  nodes, Centrals or browsers that do not report the capability.
- A PDF is not accessible to screen readers in v1 (OD-3).
- Deployment order becomes a documented constraint, and rolling Central's version back
  requires disabling or rolling back the daemons first (§9).
- The preview endpoint is a POST for a read. That is deliberate (§6), and it differs from
  every other file route.
- Three **pre-existing** defects are recorded and left for separate issues: the text
  preview's blocking FIFO open on the dispatch loop, workspace paths and search keywords
  in GET query strings reaching both access logs, and the edge's `proxy_temp` spill
  exposure. This ADR does not fix them and does not repeat them.
- **Not decided here:** thumbnails in the file list, SVG, HEIC/AVIF, animated GIF,
  PDF text selection and search, password-protected PDFs, printing, video and audio,
  Office documents, and any relaxation of the sensitive policy.

## Alternatives considered and rejected

| Option | Why not |
|---|---|
| `raw:true` (or `mode`, `encoding:"base64"`) on `filesystem.read` | One type with two policies; the binary deny becomes conditional (§1). #77 forbids it. |
| Reuse PR #71's download endpoint and render its bytes inline | That is a different grant (take a copy) with a different switch and audit; it would make preview depend on download being enabled, and `octet-stream` + `attachment` is designed *not* to render (§16). #77 forbids it. |
| Single frame, ≤ 4 MiB, no chunking (the #71 shape) | It caps PDFs at 4 MiB, holds a whole file per request in Central, and gives no backpressure. Chunking from a validated snapshot costs one handle table and removes all three problems (§5). |
| Ranged reads of the live file (`offset`, `length`) | Bytes served could differ from bytes validated; it needs a version precondition (ADR 0028 §9, `plan/14`). The snapshot avoids that. |
| New binary WebSocket frame kind for preview data | It touches the terminal's binary header demux in three consumers for a ~33 % saving (§5). |
| Browser-side JSON with base64 body | +33 % over the air and a large string decode on a phone; a streamed binary body with `Content-Length` is smaller and fails closed. |
| `<img src="blob:…">` / `data:` URLs | `blob:` needs a CSP change; both expose "save image" / "open in new tab" (download by another name), and object URLs need lifecycle management. Canvas avoids all three (§11). A device fallback only. |
| Native browser PDF viewer (`<iframe>` / `<embed>` / `<object>` of a blob) | Android Chrome has no inline PDF viewer and would **download** instead (#77 forbids it); iOS behaviour differs by version; the native viewer runs document JS and makes links clickable; it needs `object-src`/`frame-src` relaxations. |
| PDF.js full viewer app (`web/viewer.html`) | It ships download, print, open-file, the scripting sandbox and an annotation DOM (§12). |
| Server-side rasterisation (daemon or Central renders PNG pages with MuPDF/Poppler/PDFium) | A native C parser outside any sandbox on the node or on Central, CGO or a sidecar binary, licences (MuPDF AGPL, Poppler GPL), node CPU, and still a PDF parser. It moves the parser-exploit risk from the browser sandbox to our servers. |
| PDFium compiled to WebAssembly | Viable, but packaging is less mature and larger, and no smaller in attack surface than PDF.js. Revisit only if PDF.js fails `BP-OM-04`. |
| Third-party viewer (Google Docs viewer, a SaaS) | It sends workspace content off-platform. Forbidden by #77 and ADR 0017's no-external-origin CSP. |
| Daemon transcodes images to a sanitized PNG | It needs full decoders (WebP means a new `x/image` dependency), costs node CPU, changes the bytes, and moves decode risk out of the browser sandbox. It is a possible later hardening for exotic formats, not v1. |
| A full PDF parser in the daemon to count pages | A dependency (pdfcpu) or a hand-written parser outside the browser sandbox, only to enforce a limit the renderer enforces authoritatively (§4). |
| A new `file.preview` RBAC action (Viewer excluded) | The product owner explicitly wants Viewer included (#77). Fixed roles cannot express the difference, and it would split audit queries (§7). |
| Serve any `image/*` the browser can decode | Pulls SVG (active content) and a long tail of decoders into the attack surface; the allowlist is the control (§2). |
| `GET ?path=` with access logging suppressed or query-less at every hop | Keeps the path out of logs only as long as every hop stays configured, including the Railway edge, which Cliora does not configure (§6). Kept as defence in depth, not as the control. |
| `POST` → opaque short-lived handle → `GET /…/{handle}` | Central handle state across processes (`BP-OM-09`), replay and binding rules, a second round trip; its only gain is a GET-able URL, which §11 does not want (§6). |
| Daemon `/Encrypt` scan to refuse encrypted PDFs before transfer | It cannot tell password-protected from permissions-only, and a textual scan is fooled both ways, so it would present a heuristic as a guarantee (§4). |
| Send `binary_preview: false` when disabled | An old Central rejects the key regardless of value, silently, so a disabled daemon could not register after a Central rollback (§9). |
| Cache decoded previews (LRU, IndexedDB, Service Worker) | Cross-user and cross-session leakage, and poisoning on a shared phone; memory pressure on iOS (§14). |

## Open decisions and unverified assumptions

Product decisions, each with a recommended default, are in
`plan/31/01-decisions-and-governance.md` §6 (OD-1 … OD-11). Technical unknowns that must be
measured before a default is final are `BP-OM-01 … BP-OM-11` in
`plan/31/09-implementation-status.md`. The product owner signed off on §7 (the widening)
and on every OD's recommended default on 2026-09-27, which is what moved this ADR to
`accepted`. `BP-08`'s security review remains a release gate; its verdict is recorded in
`plan/31/09-implementation-status.md`, and a `FAIL` reopens this ADR.
