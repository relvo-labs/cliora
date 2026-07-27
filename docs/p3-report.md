# P3 — Workspace & Files: Go / No-Go report

**Phase:** P3 (Workspace Files) · **Status:** ⏳ Conditional — the whole vertical is implemented and verified locally, including a full-stack browser E2E against a real daemon node. **The one remaining step for Go is running `.github/workflows/p3.yml` on an actual GitHub runner (a push; this working copy is not a git repository).**

## Outcome

A user in a Session Workspace can expand the node's workspace tree lazily, search by filename and jump back into the tree, and preview legal source files in a read-only Monaco editor (highlighting, line numbers, find, word wrap, copy, goto line, refresh). `.env` / `*.pem` / `id_rsa` / `.ssh/**`, binaries, oversize files, unreadable files and undetermined types are each refused with a specific "cannot preview" screen that names the reason and the next step and carries **no content and no server absolute path**. Every list/read/search re-canonicalizes through the confined `os.Root` handle, so no `..`, absolute path, prefix collision, symlink chain/swap or NUL byte escapes the workspace. Central only authorizes and relays — it never reads the node filesystem.

## Tickets

| Ticket | Result |
|---|---|
| P3-01 decision ADRs | ✅ ADR 0014 (path security & relay) + 0015 (limits & preview policy); 0015 amended with the frame-bound finding below |
| P3-02 protocol v1.3 | ✅ 6 types + 3 request schemas + `FILE_*` codes; fixtures + manifest; 3-language codec. Amended to 1.3.1 (split frame bound) |
| P3-03 path security (Gate) | ✅ `internal/workspace/root.go` (`os.Root` handle); TOCTOU symlink-swap + bounded-read tests; `FuzzOpenFile` 7.2M execs, 0 containment violations |
| P3-04 daemon list/search | ✅ `internal/files/{list,search}.go` + dispatch; ordering/exclusion/pagination/bounds/cancel; integration-verified over the real link |
| P3-05 daemon read policy | ✅ `internal/files/read.go`; sensitive → confined open → fstat → size cap → bounded read → binary; resolved-name recheck closes the symlink bypass |
| P3-06 Central relay + API | ✅ `services/files.py` + `api/http/files.py`; RBAC, boundary rejection, safe error collapse, `0007` file.browse seed |
| P3-07 file tree UI | ✅ `stores/files.ts`, `composables/useFileTree.ts`, `components/file/FileTree*`; lazy expand, full state matrix, `aria-activedescendant` keyboard tree, search→tree reveal, session-switch cache clear + abort |
| P3-08 Monaco preview | ✅ `monaco-editor` 0.56.0 pinned, curated build, self-bundled worker; `useMonacoModel.ts` (LRU 8 + dispose), `PreviewPane`/`PreviewDenied`; allowed→denied clearing; leak gate |
| P3-09 audit + observability | ✅ sensitive-read audit (classification + extension only); filesystem metrics (backend + daemon); redacted correlation log (keyword hashed) |
| P3-10 verification | ◐ full local matrix green incl. full-stack E2E and both latency harnesses; `p3.yml` awaits a real runner |

## Two defects found by the exit gate

Both were invisible to every unit test and only appeared once real components were wired together. They are the reason this phase's verification step earned its keep.

### 1. A 2 MiB preview could never be delivered (protocol frame bound)

Found by `backend/perf/files_bench.py`. The control-frame limit was 64 KiB on both sides, but ADR 0015 mandates a ≤2 MiB preview and 2000-entry listings — 32× and ~5× over it. Central's `decode_control` raised `FRAME_TOO_LARGE`, the node WS loop `continue`d, the parked Future was never resolved, and the user got a 15 s `REQUEST_TIMEOUT` instead of their file. Unit tests missed it because the daemon tests call the file service directly and the Central tests fake the registry — nothing crossed the real codec.

Fixed by giving the three filesystem *response* types their own 8 MiB bound (`MAX_FILE_PAYLOAD` / `MaxFilePayload`) while every other control type keeps 64 KiB, and by making the daemon refuse to *build* an over-bound frame (`ErrFrameTooLarge` → `FRAME_TOO_LARGE` reply) so the failure is an explicit error rather than a hang. Recorded in `contracts/CHANGELOG.md` 1.3.1 and an ADR 0015 amendment; covered by tests in both languages.

### 2. An enrolled node had no sensitive-file policy at all (config defaulting)

Found by the full-stack Playwright run: `.env` previewed its contents and `node_modules` was expandable. `internal/install/plan.go` built the generated `config.yaml` without the policy lists; `yaml.Marshal` renders a nil slice as `[]`, which decodes back as an *empty but non-nil* slice, so load-time defaulting (a `== nil` check) skipped it. Every freshly enrolled node therefore denied **nothing** and excluded **nothing** — a live SEC-004 / FR-FILE-005 hole in the real deployment path, while the daemon unit tests passed because they construct the config in Go with the defaults already set.

Fixed on both sides: the installer now writes the documented defaults explicitly (also giving operators a visible place to extend them), and the two *security* lists default on **empty**, not just nil, so default-deny cannot be disabled by omission. `excluded_directories` keeps the nil-only check because it is an ignore rule, not a security control, and an explicit `[]` legitimately means "load everything". Regression tests: `internal/config` (empty→defaults, explicit list wins, explicit empty excluded honoured) and `internal/install` (generated config carries the policy and survives a marshal→Load round trip).

## Measured performance

Both P3 NFRs are met with three orders of magnitude of headroom. The two legs are measured separately and summed; artifacts in `artifacts/p3/local/`.

| NFR | Daemon leg (p95) | Central leg (p95) | Sum | Target | Result |
|---|---:|---:|---:|---:|---|
| Directory list (5000 entries, paged at 2000) | 9.1 ms | 2.8 ms | ~12 ms | < 2000 ms | ✅ |
| ≤2 MB preview (2 MiB text, full policy) | 2.4 ms | 6.2 ms | ~9 ms | < 3000 ms | ✅ |
| Filename search (8-level tree, excluded dir skipped) | 6.2 ms | 0.3 ms | ~7 ms | bounded | ✅ |

Daemon leg: `go test ./internal/files -run TestFilesystemLatencyBudget` (real `os.Root` confinement + policy + bounded read; budgets enforced, test fails on regression). Central leg: `backend/perf/files_bench.py` (real correlation table + production codec + response serialization). Neither includes network transit between Central and the node.

Relay bounds, all asserted by the same harness: `REQUEST_TIMEOUT` with no pending leak, caller cancel with no pending leak, `NODE_BUSY` at the 128 per-node cap, and disconnect mid-flight failing all 128 waiters and clearing the table.

## What was verified locally

| Area | Evidence |
|---|---|
| Format / lint / typecheck | `ruff format --check` + `ruff check` + `mypy` clean (61 files); `gofmt` + `go vet` clean; prettier + eslint + `vue-tsc` clean |
| Path security (Gate) | `go test -race ./internal/workspace`: traversal, absolute escape, prefix collision, symlink chain, broken link, NUL byte, non-regular, symlink-swap TOCTOU, bounded-read TOCTOU. `go test -fuzz=FuzzOpenFile -fuzztime=8s`: 7.2M execs, 0 containment violations |
| Daemon | `go test -race ./...` green; `-tags integration -race ./internal/{session,connection,files,workspace}` green (tmux 3.4) |
| Daemon filesystem over the real link | `internal/connection/files_integration_test.go`: real session → `filesystem.list` (ordering, hidden/symlink/excluded flags), `filesystem.read` (source ok; dotenv / symlink→dotenv / binary / oversize / traversal / missing all refused), `filesystem.search` (hit, excluded dir not descended, `max_results` → partial + `stopped_reason`). Every frame asserted free of the workspace absolute path and of file content |
| Backend | `pytest` **193 passed** (hermetic + PostgreSQL 16); contract **58**; migrations up/down/up incl. `0007` |
| Central relay | `tests/db/test_files_api.py` (12): RBAC on all three roles, absolute/`..`/`~` rejected at the boundary and never relayed, existence-probe collapse, `NODE_OFFLINE`, sensitive-read audit with no path/content, per-op metrics + duration, timeout/disconnect counters, denial counters by reason, correlation log with no path/content/keyword, audit-failure resilience |
| Frontend | **136 unit tests**: `useFileTree` (17 — lazy, cache hit, refresh, state matrix, partial paging, search reveal, session-switch clear + abort, keyboard), `useMonacoModel` (16 — LRU eviction, **leak gate** over 40 switches, session-switch disposal, allowed→denied clearing, denial codes, superseded response), `FileTree` (5 — rendering, excluded badge, keydown binding, RBAC, dead session), `PreviewDenied` (8 — each denial screen, next step, no absolute path) |
| Monaco bundle | Production build succeeds offline; `editor.worker` emitted as a local asset; no CDN/unpkg/jsdelivr reference in `dist`. Monaco is code-split behind the preview pane (workspace chunk 332 kB, editor 2.96 MB loaded on first preview) |
| Browser E2E (full stack) | `frontend/tests/e2e/files.spec.ts` — **5/5 green** against Central + a real rootless-enrolled daemon node: lazy tree + excluded dir not loadable, filename search → ancestors expanded + hit selected, Monaco preview (marker text, line numbers, read-only under typing, wrap toggle, find widget, copy, refresh), `.env` → sensitive denial with the secret absent from the DOM and the editor hidden, `*.pem` → private-key denial, binary → mime + size, oversize → 3.00 MB vs cap, keyboard-only walk that opens nothing until Enter, terminated session → tree replaced by an explicit affordance. Whole suite (auth + nodes + session + files) **12/12 on Chromium and 12/12 on Firefox**; WebKit cannot launch in this sandbox (missing system libs, needs root) and is covered by the CI matrix |
| Evidence pack | `scripts/p3/evidence.sh` → `artifacts/p3/local/`: `versions.txt`, `commands.txt` (18 gates, all exit=0), `contract{,-go,-ts}`, `unit-backend.xml`, `unit-frontend.xml`, `race.txt`, `integration.txt`, `pathsec-gate.txt` (+ fuzz summary), `fuzz.txt`, `latency.json` (both legs + NFR verdict), `denial-matrix.md`, `relay-bounds.md`, `security-report.md`, `e2e.xml`, and 8 `screenshots/` (tree, search→reveal, code preview, each denial, keyboard focus, session ended). The script exits non-zero if any recorded gate fails, so the pack cannot describe a green run that did not happen |

## Exit gate checklist

### Functional

- [x] Lazy expand from the allowed root, excluded/hidden entries explicit, filename search returns into tree context.
- [x] Monaco read-only preview: highlighting, line numbers, find, word wrap, copy, goto line, refresh.
- [x] Sensitive / binary / oversize / permission / undetermined each have a specific screen with a next step and no content leak.
- [x] Session switch clears the tree, the selection and every Monaco model; allowed→denied clears the editor before the denial renders; no model or worker accumulation (leak gate).

### Security (release blocking)

- [x] Path-security gate green: `..`, absolute escape, prefix collision, symlink chain, broken link, NUL byte, non-regular, TOCTOU replacement/symlink-swap all refused; fuzz found no counter-example.
- [x] Every list/read/search re-canonicalizes; no handler trusts a prior listing or a client breadcrumb.
- [x] Central relays and authorizes only; absolute paths, `..`, `~` and control characters are refused at the HTTP boundary and never reach the daemon (asserted: `fake.calls == []`).
- [x] Sensitive files denied by default in all four categories — **including on a freshly enrolled node** (defect 2); binary/oversize/undetermined return metadata only; no denial carries content or a server absolute path.
- [x] Failed sensitive reads are audited with classification + extension only; log/audit scans show no file content, no keyword in the clear, no unnecessary absolute path.

### Performance and engineering baseline

- [x] Directory list and ≤2 MB preview measured with large headroom; budgets enforced in CI and fail on regression.
- [x] Search bounds (depth/results/scanned/timeout) and cancel proven bounded; relay timeout/cancel/`NODE_BUSY`/disconnect leave no pending entry (`-race` clean).
- [x] Clean checkout can bootstrap, migrate, build (Monaco bundles offline), test and run the tree→preview vertical.
- [ ] **CI gates green on a real runner** — `p3.yml` (8 jobs, now including an `evidence` job) is authored and every job's core command was run locally, but it has never executed on GitHub. This remains the only release-blocking open item.
- [ ] **WebKit E2E** — Chromium and Firefox are 12/12 locally; WebKit needs system libraries this sandbox cannot install (no root). The `browser-e2e` job installs all three, so CI closes it.
- [x] `research/01/06-requirement-traceability.md` updated with the P3 evidence section.

## Recommendation

**Conditional Go.** Every functional and security gate is met and both defects the gate uncovered are fixed with regression tests in the language where they occurred. Flip to Go once `p3.yml` runs green on a GitHub runner — which also closes the WebKit leg. No open high-risk item remains: no path escape, no TOCTOU bypass, no sensitive-content leak, no Central-side filesystem access, no relay or Monaco leak.

### Known, accepted display (not a P3 gap)

The session header still shows the node's absolute workspace path — P2 behaviour for the path the user themselves chose when creating the session, accepted at the P2 gate. P3's no-absolute-path rule covers the tree, the preview and every denial: the tree root renders the folder name only, and no filesystem response or denial carries a server path (asserted in the relay and integration tests).

## Deferred to P4 (unchanged scope)

`workspace_favorites` / recent workspaces (FR-WORKSPACE-004/005); file access history for successful reads; full-text search (ripgrep integration); RBAC operations and audit-viewing UI; dashboard aggregation; structured metrics export (a Prometheus endpoint — the in-process registries added here are the collection point, per tech §18.2); live filesystem watching (P3 ships manual refresh only).
