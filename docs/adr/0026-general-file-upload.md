# ADR 0026 — General file upload: the client names the destination

- Status: accepted
- Date: 2026-08-03
- Amends: ADR 0024's **W2**, third leg only — retention applies to a
  platform-owned destination; where the user chooses the destination, the
  corresponding requirement is visibility. W1, W3, W4, §3 and §4 are unchanged.
- Related: ADR 0014 (path security; `workspace.Root` confinement, which W1 rests
  on entirely), ADR 0015 (preview policy and limits), ADR 0016 (RBAC is one
  table), ADR 0024 (write posture, W1–W4, image drop — this ADR is the design of
  the "general file upload" row in its Alternatives rejected, and the second of
  the two cases its §4 anticipated)
- Requirements: `FR-FILE-010`, `NFR-005.AC-109` (narrowed again),
  `NFR-005.AC-142` (one clause), `FR-FILE-005` (extended to the write direction)
- Contract: v1.9.0
- Ships in: `agentd` 0.7.0 (migration `0020`)
- Plan: `plan/15/` (which supersedes the withdrawn `plan/14/`)

## Context

Asked for on 2026-08-03:

> 實際上使用者只需要將檔案上傳到 workspace 底下的目錄，要可以將檔案拖拉進檔案瀏覽器中，
> 其餘就用 cli 或是 terminal 處理

The same instruction withdrew a larger plan (`plan/14`, workspace file editing)
as too big a change. **That is part of the context, not trivia**, because the
last clause — *everything else goes through the CLI or the terminal* — is a scope
directive, and it is what makes this ADR small. Editing, rename and delete are
the only reasons the withdrawn design needed version preconditions, a trash can,
undo and a dirty-buffer state machine. Removing those verbs removed all of it.

ADR 0024 left two things pointing here.

**First**, its Alternatives rejected table:

> Open general file upload, since writes are allowed now | …W2/W3/W4 must hold
> for general upload too, and they are not designed for it — starting with what a
> quota means for arbitrary file sizes.

That was "not designed yet", not "never". This ADR designs those three (§4, §5, §6).

**Second**, its §4, which recorded that the rule "the sender does not name the
thing" is a property of image drop and not a general law, and warned about two
opposite mistakes. This is the second case that section anticipated, and both
warnings are obeyed here (§2).

## Decision

### 1. One new path, and it may name its destination

`filesystem.store` carries `{session_id, directory, filename, data}`. This is
the first time the platform lets a caller choose where in a workspace something
lands and what it is called.

Five limits, fixed:

1. **Never overwrite** — `O_EXCL`. If anything already exists under that name
   (file, directory or symlink) the request is refused with `FILE_EXISTS` and
   nothing is written. See §3.
2. **Never create a directory** — the destination must already exist and be a
   real directory, checked with `Lstat` before `Stat` so an in-root symlink
   cannot redirect the write.
3. **Never executable** — mode is `0644`, whatever the source was.
4. **Position and name pass the read path's policy** — the same
   `SensitiveClassification` the preview uses, plus `.git` (both shapes, §7),
   `.cliora/`, and the excluded-directory list. See §4.
5. **Bounded** — 4 MiB per file, 256 MiB per session, 200 files per day, and a
   free-space floor. No retention; see §5.

There is deliberately **no restriction on file type**. Image drop sniffs magic
numbers because it must guarantee the CLI can read the result; a general upload
carries no such promise, and a user putting a `.tar.gz` or a `.parquet` into
their own workspace is not the platform's business. What replaces a type check is
limit 3 (never executable) and limit 4 (the name must pass policy).

### 2. …without weakening the path that must not name anything

ADR 0024 §4 warned about two opposite mistakes. Both are avoided:

| The mistake | What was done instead |
|---|---|
| Cite "the sender does not name the thing" to argue that no path may name its destination | This is the path §4 said would exist. A screenshot does not need a name; `requirements.txt`'s name *is* its meaning. |
| Cite this path to add a `filename` to `filesystem.upload` | A **separate type** was added. `filesystem.upload` keeps its two fields, its `additionalProperties: false`, and all five of its golden invalid fixtures, unmodified. |

Two upload types now exist and their rules differ, because what they carry
differs. That is the outcome §4 asked for, not a compromise.

The protections §4 listed for a path where the client names the file are
delivered as follows:

| ADR 0024 §4 | Here |
|---|---|
| path normalisation | `relClean` on `directory`; `filename` cannot contain a separator **on the wire** (§8) |
| binding the decision to the opened inode | `Lstat` on the destination directory (refusing a symlink), `O_EXCL｜O_NOFOLLOW` on the create |
| the sensitive-file policy in the write direction | the same function, §4 |
| refusing symlink creation | no symlink is ever created, and none is followed |
| protecting `.git/` | refused, both shapes — §7 |

What is **not** needed is a version precondition. §4 listed it for editing
because editing replaces existing content. This path never replaces anything
(§3), so "what do you believe is there" is not a question it has to ask.

### 3. Never overwrite, and what that buys

`O_EXCL` is the whole of the concurrency design. Because no existing byte is ever
touched, this ADR needs no revision token, no `If-Match`, no 412, no trash can,
no undo and no conflict UI. Refusing is also the honest answer: a user replacing
a file wants the version they have in mind to win, and the terminal is where that
intent can be expressed precisely.

Rejected: auto-suffixing (`data (1).csv`). Renaming silently means the CLI reads
the old copy while the user believes it read the new one, and the symptom — "the
model is looking at stale data" — is very hard to trace back to the upload.

The front end offers a pre-filled rename box and one sentence: *to replace an
existing file, use the terminal.*

### 4. Writable position and name = readable position and name

The destination path (`directory` joined with `filename`) must pass
`policy.SensitiveClassification` — the same function the preview calls — plus
four refusals of its own: `.git` in either shape, anything under `.cliora/`, any
segment in `workspace.excluded_directories`, and the workspace root as a
*filename*.

One sentence: **the platform does not write to a location, or under a name, that
it would refuse to show you.**

This answers the question ADR 0024 §4 left open for client-named paths, keeps the
sensitive-file policy to a single implementation, and makes it impossible for the
platform to create a file it will then refuse to display. It also keeps a secret
off the relay path by policy rather than by luck.

It is worth being exact about what it does *not* do: a user can rename `.env` to
`notes.txt` on their own machine and upload that. The policy is aimed at mistakes
and at the platform's own complicity, not at a user's intent — and a user who
genuinely needs a key on that node has the terminal, which is the division of
labour this round was asked to respect.

### 5. W2's third leg: retention does not apply here

Per-file, per-session and per-day ceilings apply, plus a **free-space floor**
(refuse if the write would leave less than the configured minimum, or less than
twice the file size). There is **no retention period, and there should not be.**

Retention exists in ADR 0024 because `.cliora/uploads/` is named and therefore
owned by the platform: nobody else was going to clean it. A file the user placed
at `datasets/input.csv` is the user's data from the moment it lands. Deleting it
on a seven-day timer would be a catastrophe dressed as discipline.

So for a user-chosen destination the third leg of W2 is **visibility**: every
byte lands at a path the user picked, appears in the tree, and is removed by the
user — exactly like a file their CLI wrote. The disk-exhaustion risk that
retention covered is covered more directly by the free-space floor.

This is a refinement of W2, not a waiver. A waiver would mean the rule does not
hold here and the risk is accepted. What actually happens is that the rule's
purpose has two correct shapes depending on who owns the destination. Written
this way, the next write path asks the right question — **who cleans this up** —
instead of copying a seven.

The per-session and per-day counters are held **in memory** and reset when
`agentd` restarts. Image drop can recount from its own directory; this path
cannot, because its files are scattered across locations the platform does not
track — which is the same fact as the paragraph above, seen from the other side.
The ceiling therefore bounds a broken client, not a determined user; a
determined user holds `terminal.operate` and can write files directly. The
exhaustion risk is held by the free-space floor, which needs no memory.

### 6. Authorisation and audit reuse `file.upload`

No new RBAC action and no new audit action. `file.upload` **widens in meaning**,
from "drop an image into a platform-owned directory" to "place a file somewhere
in the workspace". Its holders are unchanged (Admin, Developer; Viewer holds
neither, and gains nothing here).

Reasons: the verb is the same, so splitting it would make every audit query a
union of two keys; with three fixed roles nobody can express "may upload images
but not files"; and `ROLE_ACTIONS` has three automated cross-checks, so each
action costs maintenance in three places. Substantively, both holders already
hold `terminal.operate` on the same node and can write files there today — this
is a new interface, not a new capability.

**The cost is real and belongs here rather than in a footnote:** an organisation
that granted `file.upload` for screenshots has, after upgrading, granted more.
There is no way to keep only the older half except by switching the new path off
at the node (§9). That is why the node-side switch is a condition of this
decision and not a convenience.

The audit entry keeps its action and gains a `source` field (`image` | `file`) so
the two paths stay distinguishable. Its `path` is still recorded, but the reason
has changed: ADR 0024 D11 could record the relative path because *the platform
chose it*. Here the **user** chose it — and it is still recordable, because the
user already sees that path (they picked it in the tree), and without it W3's
question, "who put what here", has only a counter for an answer.

### 7. `.git` was not protected at all

Worth stating plainly, because it is a pre-existing gap this ADR must close:
`.git` appears only in `workspace.excluded_directories`, whose own comment says
it is an ignore rule and **not a security control**; the default
`filesystem.denied_directories` is `.ssh`, `.aws`, `.gnupg`. Naming the path
directly reads `.git/config` today.

On top of that, a git worktree's or submodule's `.git` is a **file** containing
`gitdir: …`, so a segment match does not catch it, and rewriting it repoints the
whole worktree.

Both shapes are refused for this write path. **The read direction is left as it
is**: making `.git/config` unpreviewable would take a batch of files that are
visible today and hide them, which needs its own release note and belongs to its
own round.

### 8. `directory` and `filename` are two fields

A single `path` field would need a validator to confirm that its last segment is
the name the user typed, and path traversal is what grows out of the holes in
that validator. Two fields make **"a filename containing a separator"
unrepresentable on the wire** — the schema pattern excludes `/` outright, in all
three consumers.

This matters more than it looks, because URL encoding *can* smuggle a separator
into a query parameter: `%2F` decodes to `/` and `..%2F` to `../`
(`plan/15/07-open-measurements.md` §2). Validation therefore runs after decoding,
and the field split means the wire contract states the rule rather than relying
on that ordering alone.

### 9. The node may refuse

`filesystem.upload.files.enabled` (default `true`), reported as
`node-register.file_upload`. It is **separate from image drop's switch**: "may
the platform put screenshots in `.cliora/`" and "may it put arbitrary files
anywhere in my workspace" are different-sized grants, and a node owner is
entitled to answer them differently.

Report-only, the same shape as contract 1.7.0: the node states its posture and
the platform never selects it. Default `true` carries the same trade as ADR 0023
D2 and ADR 0024 D8 — **upgrade acquires the behaviour** — and therefore the same
obligation of a release note and a runbook, never silence.

## Consequences

- **Positive.** Users can put a file where it needs to be, which is the second
  most common gap in CLI collaboration after handing over a screenshot. The path
  reuses ADR 0014's confinement and ADR 0015's sensitive-file policy rather than
  inventing either again, and it needs none of the machinery the withdrawn
  editing design required.
- **`file.upload` means more than it did** (§6), and an organisation cannot keep
  only the old half except at the node.
- **The platform writes into locations the user chooses.** Image drop only ever
  wrote inside `.cliora/`. This path writes into a source tree — but never
  replaces anything in it.
- **`filesystem.store` is the second request type allowed the 8 MiB frame
  bound.** The bound itself does not move: 4 MiB raw is 5.33 MiB of base64,
  inside the existing ceiling. ADR 0024 §7 already paid for that widening.
- **4 MiB will be hit.** The alternative path is the terminal, and the refusal
  says so. It is a decision to be observed rather than a settled one:
  `filesystem_store_refused_total` exists so that "add chunked upload" can be
  argued from data (`plan/15` `00-…md` D3).
- **Counters reset on daemon restart** (§5).
- **Preview is still read-only**, and the workspace still has no editing, rename
  or delete path from the browser. Those were decided against for this product,
  not deferred: they belong to the CLI and the terminal.
- **`FILE_UPLOAD_QUOTA_EXCEEDED`'s message was wrong and is fixed.** It told
  users to delete images from `.cliora/uploads/` in the file tree, which has
  never been possible. It now points at the terminal. This round adds no delete.
- **Not decided here:** download, editing, rename, delete, folder upload, chunked
  upload, and overwrite.

## Alternatives rejected

| Option | Why not |
|---|---|
| Add `filename`/`directory` to `filesystem.upload` | One of the two mistakes ADR 0024 §4 pre-empted: it would trade a path that has no traversal entry point at all for one needing three validation routines, **and buy nothing** — nobody needs a pasted screenshot to keep its name. |
| Allow overwrite (`overwrite: true`) | The first step of the withdrawn design. Safe overwriting needs a version precondition, 412, a trash can and undo; a user replacing a file has the terminal. |
| Auto-suffix on collision | Silent renaming makes the CLI read the old copy while the user believes otherwise (§3). |
| `multipart/form-data` to carry the name | Adds `python-multipart` and a parser to a request carrying exactly one thing. ADR 0024's `/images` already set the raw-body precedent. |
| Chunked upload now | Needs an assembly state machine, timeout cleanup and a partial-landing story. That is its own ADR; this round was explicitly asked to be small. |
| Folder upload | Needs directory creation, an unbounded item count and a partial-failure story — and folders are exactly what "everything else goes through the CLI" covers. |
| Reuse image drop's `image_upload` switch | Two different-sized grants (§9). |
| A new `file.write` action | The withdrawn design's approach: a seed migration plus three places of matrix maintenance, in exchange for a flag nobody would set differently (§6). |
| Preserve the source file's mode | A file dragged in from a browser should not arrive executable. `chmod +x` is a decision a user should make knowingly. |
| Recount the per-session quota by scanning the workspace | Impossible by construction: the platform does not know which files it put there. That is the same fact as §5. |
