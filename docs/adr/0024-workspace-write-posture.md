# ADR 0024 — Workspace write posture: read-only withdrawn, and one path built

- Status: accepted
- Date: 2026-08-01
- Amends: ADR 0015 (its read-only premise and its `Out of P3: editing/upload/download`
  scope line). ADR 0015 is not superseded — its limits, sensitive-file policy, ignore rule
  and Monaco lifecycle stand unchanged.
- Related: ADR 0014 (path security; `workspace.Root` / `os.Root` confinement, unchanged and
  now load-bearing in a way it was not before), ADR 0016 (RBAC is one table), ADR 0021 §1
  (the half of `SCOPE-011` that survives: the console names no command), ADR 0023
  (privileged node posture — deliberately **not** extended here, see Context)
- Requirements: `NFR-005.AC-142` (withdrawn by this ADR), `NFR-005.AC-109` (partially
  delivered), `FR-FILE-008`, `FR-FILE-009`, `FR-FILE-004`
- Contract: v1.8.0
- Ships in: `agentd` 0.6.0 (migrations `0018`, `0019`)
- Plan: `plan/13/`
- Followed by: ADR 0026 (general file upload) — the design of the "general file
  upload" row in Alternatives rejected, and the ADR that §4 anticipated for a
  path where the client necessarily names the file. It refines W2's third leg
  (see W2) and leaves W1, W3, W4, §3 and §4 unchanged.

## Context

Two things were asked for on 2026-08-01. The first was a feature:

> CLI 要加入可以直接透過網頁把圖片放入的功能

There is no second way to do this. `claude` and `codex` read images from the **node's**
filesystem; the bytes are in a browser. So the bytes have to cross a boundary that, until
today, only carried reads.

When that was pointed out, the second answer settled the shape of this ADR:

> 已經可以撤銷唯讀工作區了，日後會朝向可編輯，平台可以寫進使用者工作區

So this is **not** an ADR that opens an exception in a read-only boundary. It withdraws the
read-only posture and lays down the rules every write path must follow. Image drop is the
first instance of that posture, not the whole of it. The distinction is not cosmetic: an
exception gets treated as a one-off dispensation and the next write path re-argues
everything from scratch; a posture gets treated as the new default and the next path is
built against the rules. The second is what was asked for.

### What was actually read-only

Read-only was not merely the state of the implementation. It was written into the product's
core principles — `research/prd.md` §23, "檔案總覽第一階段採唯讀模式" (`NFR-005.AC-142`) —
with ADR 0015's scope line and the §21 future-work item (`NFR-005.AC-109`) downstream of it.
Withdrawing it therefore costs one PRD revision, and refusing to pay that cost would leave
the implementation contradicting a written core principle. The contradiction never resolves
in the document's favour.

### ADR 0023's premise does not extend here

ADR 0023 records that a node is a disposable VM, and uses it to move damage *inside* a node
from the risk list to the accepted-cost list. **That premise is not available to this ADR.**
Rebuilding a VM does not restore the contents of a workspace — that is the user's source
tree, not the node's state — and it does not undo anything that happened on Central, which
is shared. The two new risks here are precisely the two the VM boundary does not cover.

## Decision

### 1. Read-only is withdrawn, and replaced by four rules

"The workspace is read-only" is no longer a product invariant. In its place: **every write
path — image drop today, file editing later — must satisfy all four of the following.**

| # | Rule | Why it must hold for *every* path, not just this one |
|---|---|---|
| **W1** | **Confined by `workspace.Root`** (`os.Root`, `openat2 RESOLVE_BENEATH`). No write may take an absolute path or bypass the handle. | This is the one thing ADR 0014 / `SEC-001` still guards. While the workspace was read-only, defeating it meant reading a file that should not have been read. Now it means *writing* one. W1 is not the first of four rules; it is the precondition of the other three. |
| **W2** | **Bounded**: per-operation size, cumulative quota, and — for a **platform-owned** destination — a retention period. Where the **user** chooses the destination, retention is replaced by **visibility**: every byte must land at a path the user picked and can see, so the user is the one who removes it. *(Third leg refined by ADR 0026; the first two are unchanged and apply to every path.)* | A write path without a ceiling is a disk-exhaustion entry point. This cannot be deferred: retrofitting a quota means changing the data model, so it is cheaper to require it up front than to add it after the first incident. Retention was written as unconditional because the only path that existed wrote into a directory the platform had named and therefore owned; nobody else was going to clean it. A retention period on a path the *user* named would mean the platform deleting the user's data on a timer, which is the opposite of what W2 exists to prevent. The question to ask of a new write path is not "what is its retention" but **"who cleans this up"** — and free-space refusal covers the exhaustion risk that retention covered. |
| **W3** | **Audited per write**: who, which session, which node, what shape. Never the content. | "Who changed this file" was not a question the platform had to answer while it could not write. It is now. |
| **W4** | **Refusable by the node**, with the refusal reported to Central. | Not every machine's workspace may be written by the platform. Same report-only shape as contract 1.7.0: the node states its posture, the platform never selects it. |

W1–W4 are the durable output of this ADR. A future editing feature inherits them and will
need **its own** ADR for everything else it must decide — conflict handling, concurrent
writes, whether the sensitive-file policy applies in the write direction, protection of
`.git/`, undo. This ADR does not authorise editing and does not pre-approve its shape.

### 2. The path built today: image drop

Five limits, fixed:

1. **Images only** — `image/png`, `image/jpeg`, `image/gif`, `image/webp`, decided by magic
   number. The declared `Content-Type` is a hint for cheap pre-screening, never the verdict.
2. **One directory** — `.cliora/uploads/<UTC date>/` inside the session workspace.
3. **The daemon names the file** — `<ULID>.<sniffed extension>`. See §3.
4. **Bounded** (W2) — 4 MiB per image, 64 MiB per session, 200 files per day, 7-day retention.
5. **Refusable** (W4) — `filesystem.upload.enabled`, reported as `node-register.image_upload`.

The path reaches the CLI because the **front end types it into the terminal** as the writer,
over the WebSocket that already exists for keystrokes. Central does not inject terminal
input; no new terminal write authority is created by this ADR.

Measured before deciding (`plan/13/08-measurements.md` §4): `claude` 2.1.220 and
`codex-cli` 0.146.0 both read a **bare workspace-relative path** — no `@` prefix, no
runtime-specific dialect — for PNG, JPEG and GIF. codex did so under its default
`sandbox: read-only`, so image drop does **not** depend on ADR 0023's sandbox-bypass posture.
WebP could not be encoded on the measuring machine and remains untested (`plan/13` `WF-04`).

### 3. The request may not name the file

`filesystem.upload` carries `{session_id, data}` and nothing else. There is no `filename`,
`path`, `directory`, `extension`, `mime` or `overwrite` field, and `additionalProperties`
is `false`.

This is the same rule as 1.4.0 (`daemon.update` carries a version and nothing else), 1.6.0
(`tunnel.open` has no host field) and 1.7.0 (posture is reported, never selected), applied
to file names instead of arguments: **the sender does not name the thing.** It is worth
stating what it buys, because it is unusually cheap. Path traversal, double extensions
(`x.png.sh`), and overwriting an existing file are three separate problems with three
separate validation routines — and one shared entry point. Removing the entry point removes
all three, and there is no validation code left to get wrong.

`mime` is excluded even though it looks like a harmless hint. Once the field exists, someone
will ask whether it can be trusted to skip the sniff. The question should not be available.

### 4. …and that is not a general law

**Editing cannot inherit §3, and must not be judged against it.** Editing means changing
*this particular file*; the client necessarily names it. The rule that generalises is W1–W4,
not "the sender does not name the thing".

Written down because two opposite mistakes are both easy from here:

- Citing this ADR to argue that a future editing API must not let the front end name a file.
  That does not produce a safer editor; it produces no editor.
- Citing editing to add a `filename` to `filesystem.upload`, reintroducing traversal and
  overwrite **in exchange for nothing** — the user never needed the uploaded screenshot to
  keep its original name.

An editing path will need its own protections: path normalisation, binding the decision to
the opened inode (`RealRel`, as the read path already does), applying the sensitive-file
policy in the write direction, refusing symlink creation, and protecting `.git/`.

### 5. Where the bytes may and may not rest

Central relays and does not store: the request body is read under a 4 MiB cap, base64'd,
forwarded, and dropped. No temp file, no database row, no log line, no metrics label. A
byte stored on Central would raise three questions — retention, who can read it, whether it
is in backups — and not storing it answers all three.

The node writes `0600` files into `0700` directories, via a `.part` temp file renamed into
place, so a failed write leaves nothing behind. On first use the daemon also creates
`.cliora/.gitignore` containing `*`, and only if that file does not already exist. That is
the one write outside `uploads/`, it is hard-coded, and it exists because without it every
user's `git status` grows a pile of screenshots that `git add .` will commit.

### 6. Authorisation

A new RBAC action, `file.upload`, held by Admin and Developer. Viewer does not hold it and
retains no write capability of any kind.

It is deliberately not `file.browse` (all three roles hold that, which would hand Viewer a
write) and not `terminal.operate` (that action means driving a terminal; reusing it would
make "typed something" and "wrote a file" indistinguishable in the audit log).

Holding the action and holding the terminal write lock are different questions —
*may you* versus *is it your turn* — so the UI additionally requires the writer role, and
the HTTP layer does not check it. Checking the live single-writer state in an HTTP request
would mean copying WebSocket state into a place where it goes stale.

### 7. The frame bound, and what it costs

`filesystem.upload` joins `LargeFrameTypes` / `LARGE_FRAME_TYPES`. It is the first
**request** type to do so — 1.3.1 added the 8 MiB bound for three filesystem *responses*
specifically so the wider ceiling could not be used to smuggle an oversize session frame —
and the direction is Central→daemon, so the node's control-frame decode limit widens from
64 KiB to 8 MiB for this one type.

Accepted because the peer on that link is an authenticated Central, the daemon re-checks
type and size immediately after decode, and three independent ceilings sit in front of the
write (RBAC → Central's 4 MiB → the daemon's 4 MiB → quota). Rejected: a new binary frame
kind (touches the terminal data plane and needs chunking, reassembly and out-of-order
handling), and chunked control frames (needs an assembly state machine with timeout
cleanup) — both for one 4 MiB image.

## Consequences

- **Positive.** Users can hand a screenshot to a CLI, which is the most common gap in CLI
  collaboration. The path reuses ADR 0014's confinement rather than inventing a second path
  security model. And the next write path has W1–W4 already written, so it argues about its
  own problems instead of re-arguing these.
- **"The workspace is read-only" is now false**, and more broadly false than the
  implementation is wide: the *posture* is withdrawn, while only *one path* is built. Every
  statement that depends on it must be re-read and classified — `NFR-005.AC-142`, ADR 0015's
  scope and RBAC sections, `docs/p3-report.md`, the front end's 唯讀 badge,
  `.agent/skills/cliora-project-context`. After that pass, the platform's default answer
  changes from "cannot write" to "that path is not built yet".
- **Preview is still read-only.** `FR-FILE-002.AC-01` is untouched, and the badge on the
  preview pane stays. Only the claim about the *workspace* was wrong.
- **`SEC-001` changes weight, not wording.** See W1.
- **The platform writes into a user's source tree**, including one `.gitignore`. This is the
  first time it writes to a file tree it does not own.
- **Upgrade acquires the behaviour.** `filesystem.upload.enabled` defaults to `true`, so an
  upgraded node can be written to without anyone choosing that. Same trade as ADR 0023 D2,
  and it carries the same obligation: a release note and a runbook, never silence.
- **Not decided here:** editing, download, delete, rename, general file upload, image
  preview in the browser, and text transcoding for non-UTF-8 files.
  *(2026-08-03: general file upload was decided, in ADR 0026. Editing, rename and delete
  were decided **against** — they belong to the CLI and the terminal, so the console has no
  way to replace or remove a workspace file, and this ADR's own
  `FILE_UPLOAD_QUOTA_EXCEEDED` guidance was corrected to say so. Download is the only item
  here still genuinely undecided.)*

## Alternatives rejected

| Option | Why not |
|---|---|
| Deliver editing in the same round | The user stated a direction, not this round's scope. Editing must settle conflict handling, concurrency, `.git/` protection and the sensitive-file policy in the write direction — each larger than image drop. W1–W4 first; editing then has ground to stand on. |
| Keep read-only and call image drop an exception | The implementation would contradict `NFR-005.AC-142`, and that contradiction is always resolved by quietly ignoring the document. The user has already withdrawn the principle; writing it down costs one PRD revision. |
| Open general file upload, since writes are allowed now | Withdrawing read-only did not remove the boundary. W2/W3/W4 must hold for general upload too, and they are not designed for it — starting with what a quota means for arbitrary file sizes. *(2026-08-03: designed, in ADR 0026. The quota question resolved into three ceilings plus a free-space refusal, and it is what forced W2's third leg to be stated conditionally.)* |
| Store the image on Central and hand the CLI a URL | The CLI would need outbound network access and a platform credential to fetch it, turning the node into an API client of the platform — a far larger authorisation change than writing a file. |
| Ship the bytes through the terminal (`base64 -d > file`) | That is "run an arbitrary shell command from the front end", which is exactly the half of `SCOPE-011` that ADR 0021 §1 kept. |
| Let Central inject the path into the terminal | Creates a channel by which the platform can type into any session, and it bypasses single-writer. |
| Write outside the workspace (`/var/lib/agentd/uploads`, `/tmp`) | Leaves ADR 0014's confined region, so W1 would need a second implementation; `/tmp` is world-readable and does not survive reboot; and a CLI on a still-sandboxed node may not be able to read outside its workspace. |
| SFTP / SSH from Central | Excluded by ADR 0021 and by the product's non-goals. |
