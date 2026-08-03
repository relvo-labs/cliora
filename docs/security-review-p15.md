# Security review — P15 general file upload (ADR 0026)

- Reviewed: 2026-08-03
- Release: `agentd` 0.7.0, contract v1.9.0, migration `0020`
- Scope: the second workspace write path — `filesystem.store`,
  `POST /api/sessions/{id}/files/upload`, `files.Store`, the upload policy, the
  file tree's drop target. Contract v1.9.0, migration `0020`.
- Plan: `plan/15/` (which supersedes the withdrawn `plan/14/`)
- Open findings: **none**
- Deliberate, recorded gaps: three (§4, §7, §8)

Seven questions, in the order their weight demands. The first two carry more than
the rest because this is the first path where the *caller* names a location inside
a workspace.

---

## 1. Can a client write to somewhere it is not allowed to?

**No, and the boundary is the read path's own function rather than a copy of it.**

`files.StorableClassification` (`daemon/internal/files/store_policy.go`) runs
before any syscall and refuses, in order: a filename that is not a single segment,
a destination that escapes, `.git` in any position, anything under `.cliora/`,
anything `policy.SensitiveClassification` refuses, and any segment in
`workspace.excluded_directories`. The middle one is the load-bearing part: it is
**the same function the preview calls**, so the two directions cannot drift apart.

> the platform does not write to a location, or under a name, that it would
> refuse to show you.

Evidence:

- `TestStorePolicyClassification` — 38 cases covering every rule, including the
  workspace root as a destination (allowed — it is an ordinary place to put a
  file) and as a target path (refused).
- `TestStorePolicyRefusalsWriteNothing` — nine refusals, each asserted to leave
  the tree fingerprint (every path, size and mode) unchanged.
- `TestStoreRefusesSymlinkDestination` — an in-root `link -> real` destination is
  refused. This one matters more than it looks: `os.Root` *follows* symlinks that
  stay inside the root, so `Stat` alone would report a symlink-to-directory as a
  directory and the file would land somewhere the user did not choose. The code
  therefore `Lstat`s before it `Stat`s — the write-side counterpart of the read
  path's `RealRel` check.
- `TestStoreRefusesEscapingDestination` — `..`, `../elsewhere`, `/etc`, `~/x`, and
  the workspace is asserted empty afterwards.
- `GATE-FU-WRITE-POLICY` (`security`-tagged) runs the policy table in CI.
- `scripts/fu/write-policy-scan.sh` reports the classification of every existing
  path in a tree, which is what the runbook uses to answer "why can't I upload
  here".

`.git` deserves a note of its own, because it **was not protected before this
round**: it appears only in `workspace.excluded_directories`, whose own config
comment says it is an ignore rule and *not* a security control, and the default
`denied_directories` are `.ssh`, `.aws`, `.gnupg`. Naming the path directly still
reads `.git/config` today. Both of its shapes are now refused for writes — the
directory, and the `gitdir:` **file** that a worktree or submodule uses, which a
leading-segment rule would have missed.

The read direction is deliberately unchanged; see §7.

## 2. Can a refused upload have already changed something?

**No. Every refusal is asserted against the filesystem, not just against a code.**

This is the question a status code cannot answer. `TestStoreNeverOverwrites` is
the shape all the others follow: it asserts `FILE_EXISTS`, and then asserts the
target's SHA-256, mtime **and mode** are unchanged.

The order in `files.Store` is default-deny and nothing touches the filesystem
until the request has been accepted: enabled → size → policy → quota → free space
→ destination → name → write. The two filesystem-touching steps are the last two.

- `CreateExclusive(finalRel, …)` uses `O_EXCL|O_NOFOLLOW` on the **final** name.
  This is the guarantee; the preceding `Lstat` exists only to give a better error
  (`file_exists` vs `directory_exists`).
- On any write error the file we just created is removed — we know nothing was
  there before, because `O_EXCL` succeeded.
- Quota is released on failure (`TestStoreQuotaReleasedOnWriteFailure`), so a node
  that cannot write does not also lose its allowance.

**One design decision belongs in this answer.** The plan called for temp-file +
rename, mirroring image drop. That is *wrong here* and a test caught it:
`renameat` **replaces** its destination and `os.Root` exposes no
`RENAME_NOREPLACE`, so temp-plus-rename would silently clobber a file that
appeared after the check —
`TestStoreConcurrentSameNameHasOneWinner` failed with two winners. Image drop can
afford rename because it invents a ULID that cannot already exist; here the name
comes from the client. The accepted cost of creating the final name directly is
that it becomes visible before the bytes are complete (§8).

`GATE-FU-NO-OVERWRITE` (`security`-tagged) greps for the ways this could regress:
an `overwrite`/`mode`/`precondition` field on the wire, `O_TRUNC`, a rename into
place, a bare `os.WriteFile`, a `DELETE`/`PUT` under `/files`, or an overwrite
affordance in the front end.

## 3. Can a filename become a path?

**No, and the ordering of decode-then-validate is the part worth stating.**

Measured (`plan/15/07-open-measurements.md` §2): a query parameter of
`filename=..%2F..%2Fetc%2Fpasswd` arrives at the handler as the string
`../../etc/passwd`. Percent-encoding is the **only** way a separator could reach
this field, so validation must run on the decoded value — which it does, because
Starlette decodes in `QueryParams` before the handler sees it.

Three layers, and each has a reason to exist rather than being belt-and-braces:

| Layer | What it does | Why it is not redundant |
|---|---|---|
| Wire schema (`filesystem-store.schema.json`) | `filename` pattern excludes `/`; `directory` and `filename` are **separate fields** | Makes "a filename containing a separator" unrepresentable rather than merely rejected, in all three consumers |
| Central (`_reject_filename`) | one segment, ≤255 bytes, no control characters | Refuses without occupying a node connection |
| Daemon (`classifyFilename`) | the same rules | Central is not the only conceivable caller |

The byte-vs-character distinction is a real trap and is handled: JSON Schema's
`maxLength` counts code points, so 84 CJK characters plus an extension is 88
characters and **256 bytes**. The schema bound is a loose outer fence; the
255-byte limit is enforced where the unit is known (daemon, Central, and the
browser via `TextEncoder`). `test_bad_filenames_are_refused_before_relay` covers
both.

`test_a_percent_encoded_separator_cannot_become_a_path` asserts the refusal *and*
that no frame reached the node.

## 4. Can an uploaded file be executed, or be treated as something else?

**Not by the platform. On a sandbox-disabled node, the CLI's own reach is
unchanged — and that is worth stating plainly rather than implying.**

- Mode is a fixed `0644`, set through the file's own descriptor (`f.Chmod`, i.e.
  `fchmod`) rather than by path: Go's own documentation records that
  `os.Root.Chmod` races if the target is swapped for a symlink mid-call, and
  `fchmod` also escapes the process umask so the result is exactly `0644`.
  `TestStoreWritesFileWithFixedMode` asserts it.
- No content type is judged and none is stored. `filesystem.store` has no `mime`
  field and `filesystem.stored` returns none — a field nobody can fill honestly is
  a field that will one day be filled dishonestly.
- The destination is inside a session workspace, which is on no `PATH`.

**Recorded gap, unchanged from ADR 0024's review:** on a node running under ADR
0023's posture, the CLI has full filesystem permissions and its sandbox is
disabled. A file placed in the workspace is therefore readable — and executable if
the user chmods it — by that CLI. This round does not change that posture; it adds
a way to put a file there that is bounded, audited and non-destructive, which
`scp` into the same directory is not.

**Second recorded gap:** the name policy stops a user from uploading `.env` or
`id_rsa`, but a user can rename a secret to `notes.txt` on their own machine and
upload that. The policy is aimed at mistakes and at the platform's own complicity
— it keeps secrets off the relay path by rule rather than by luck — not at a
user's intent. A user who genuinely needs a key on that node has a terminal, which
is the division of labour this round was asked to respect.

## 5. Does Central keep any bytes?

**No, and the four "nots" from ADR 0024 §5 hold unchanged on this path.**

`FileRelayService.store_file` reads the body under a 4 MiB cap, base64-encodes it,
forwards it and drops it. No temp file, no database row, no log line, no metrics
label. `_read_bounded_body` is two-stage — the declared `Content-Length` first so
an oversize body is refused before transfer, then the running total, because
Content-Length is a claim by the sender. `test_a_lying_content_length_does_not_
get_past_the_cap` asserts a lying length still produces 413 with no frame sent.

One thing does reach durable storage, and it is deliberate: **the filename and the
relative path go into the audit record and nowhere else.** An audit table has
access control; a correlation log does not, and a filename can name a confidential
project as readily as a search keyword can — which is why the read path already
hashes keywords rather than logging them. The observation log for this operation
carries ids, byte counts and the outcome code only.

## 6. Did Viewer gain anything?

**No — and after three rounds of widening, not one statement about Viewer has had
to change.**

`file.upload` is required; Viewer does not hold it. The check is
`authz.authorize_file_upload`, reused unmodified, so this path cannot diverge from
image drop's scoping: same session-ownership rule, and a shell session is still
never a route to a workspace.

- `test_viewer_may_browse_but_not_upload` — 403 on upload, no frame sent, and the
  same user's `GET /files/tree` still works. A different permission, not a
  different session.
- `test_every_mounted_route_is_in_the_matrix` caught the new route before it was
  authorised and required it to be declared.
- `ROLE_ACTIONS`' three automated cross-checks (code, seed migrations, frontend
  constants) cover it unchanged.

## 7. What did `file.upload`'s widening actually expose?

`file.upload` now authorises more than it did: from "drop an image into a
platform-named directory" to "place a file at a path you choose". Held by Admin
and Developer, as before.

The honest accounting:

- **Both holders already hold `terminal.operate`** on the same node and can write
  files there directly. This is a new interface, not a new capability — and the
  new interface is bounded (4 MiB, 256 MiB/session, 200/day, free-space floor),
  audited per write, refusable by the node, and **incapable of destroying
  anything**. The terminal is none of those.
- **An organisation cannot keep only the older half.** The only place to draw that
  line is the node's own `filesystem.upload.files.enabled`. That switch is
  therefore a condition of the decision rather than a convenience, and it is
  separate from image drop's switch on purpose.
- **Default `true` means upgrade acquires the behaviour**, the same trade as ADR
  0023 D2 and ADR 0024 D8, carrying the same obligation: release note (§1 of it)
  and runbook, never silence.
- **Recorded gap:** the read direction of `.git` is unchanged, so `.git/config`
  remains previewable by anyone with `file.browse`. Closing it would hide a batch
  of currently-visible files, which needs its own release note. Filed, not
  forgotten.

## 8. Two properties an attacker cannot use but an operator should know

Not questions so much as facts that belong in a review rather than only in a
comment:

**A file is visible before it is complete.** Because the final name is created
first (§2), a tool watching the directory can briefly observe a short file. The
window is one write of ≤4 MiB to a local disk. The alternative would silently
replace an existing file, and losing a user's file is a worse outcome than a
transient partial one. Recorded in the runbook.

**The free-space check fails open.** If `statfs` errors, the upload proceeds and
`filesystem.store_freespace_unknown` is logged at warn.
`TestStoreFreeSpaceUnknownIsFailOpen` pins this. It is deliberate: the check
guards against filling a disk, not against an actor, and letting a `statfs`
failure refuse every upload would be treating an auxiliary guard as a boundary.
The quota counters, being in memory, reset on daemon restart for the same class of
reason — they bound a broken client, and the durable risk (disk exhaustion) is
held by the free-space floor.

## 9. Can W1–W4 carry a third write path?

Yes, with one refinement already made and one question now framed better.

| Rule | Held by this path | Notes for the next one |
|---|---|---|
| **W1** confined by `workspace.Root` | Every syscall; new `StatIn`, and `ErrExists` so a collision is not reported as "invalid path" | The `Lstat`-before-`Stat` pattern is the write-side `RealRel`. A path that accepts a client-chosen destination needs it. |
| **W2** bounded | 4 MiB/file, 256 MiB/session, 200/day, free-space floor. **No retention** | This is the refinement: retention applies to a **platform-owned** destination; where the **user** chooses it, the requirement is **visibility**. ADR 0024's W2 now says so. Ask "who cleans this up", not "what is its retention". |
| **W3** audited per write | `file.upload` with `source` distinguishing the two paths; path and bytes, never content | Recording the path was justified differently here (the user chose it and can see it) than in ADR 0024 (the platform chose it). Both reasons hold; neither generalises without being stated. |
| **W4** refusable by the node | `filesystem.upload.files.enabled` → `node-register.file_upload`, separate from image drop | Two grants of different size deserve two switches. Do not fold a third into either. |

`NFR-005.AC-109`'s remaining片 is **download**, and it is the interesting one to
frame now: it is not a write path at all, so W1–W4 barely apply. What it needs
instead is the mirror of §1 — a rule that the platform does not *read out* what it
would refuse to display — and the sensitive-file policy is already that rule. A
future review should start there rather than at W1.

## Verification summary

| Check | Result |
|---|---|
| `make check` | green |
| `scripts/fu/evidence.sh` | 15 passed, 0 failed, 1 skip (§below) |
| `go test ./... -count 1` (daemon) | green |
| `go test -race` (files, workspace, protocol) | green |
| `pytest backend/tests` with Postgres | 1075 passed |
| `make contract` — 95 fixtures × 3 consumers | green |
| `vitest` (frontend) | 456 passed |
| `GATE-FU-NO-OVERWRITE`, `GATE-FU-WRITE-POLICY` | green |
| `scripts/trace validate --level static`, `render --check` | green |

**The one skip:** the `DataTransfer` browser probe behind FU-01 #1 cannot run
here (bundled Chromium is missing `libatk-1.0.so.0`, and there is no passwordless
sudo to install it). Rather than leave a gap, the front end was built
**fail-closed** — it uploads only items it can positively confirm to be files, and
refuses the whole batch otherwise — so its correctness does not depend on the
unmeasured answer. The probe is committed at `scripts/fu/datatransfer-probe.mjs`
and should be run on a machine with browser dependencies; a positive result means
the rule stays as it is.
