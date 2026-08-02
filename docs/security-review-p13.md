# Security review — plan/13: workspace write posture and text classification

- Date: 2026-08-01
- Scope: `agentd` 0.6.0, contract v1.8.0, migrations `0018` and `0019`
- Change under review: the workspace read-only posture is withdrawn and one write path
  (image drop) is built against its replacement rules; text/binary classification is
  rewritten

Reviewed against `plan/13/06-verification-and-exit.md` §5. Eight questions, each
answered with evidence that can be re-run rather than with an assurance.

**What changed, in one sentence:** the workspace stopped being read-only, and exactly one
write path was built (ADR 0024).

---

## 1. Is the write path entirely inside `os.Root`?

**This question carries more weight than the other seven.** While the workspace was
read-only, defeating the confinement meant reading a file that should not have been read.
It now means *writing* one, so W1 is not the first of four rules — it is the precondition of
the other three.

Evidence:

- Every write goes through `workspace.Root` (`MkdirAllIn`, `CreateExclusive`, `RenameIn`,
  `RemoveIn`), each of which runs `relClean` and then an `os.Root` call, so the kernel
  refuses a `..` segment or an escaping symlink (`openat2 RESOLVE_BENEATH`).
- `TestUploadWriteMethodsStayInsideRoot` drives an escaping symlink, `../escape.txt`,
  `/etc/passwd` and `a/../../b` through the write methods and asserts the target directory
  outside the root stays empty.
- `TestSaveImageRefusesHijackedClioraPath` covers the case `os.Root` does **not** cover on
  its own: an in-root symlink. `os.Root` follows symlinks that stay inside the root, so
  `.cliora -> victim/` would silently redirect every write. The service `Lstat`s `.cliora`
  before using it — the write-side counterpart of the read path's `RealRel` check — and the
  test asserts nothing was written into `victim/`.
- `scripts/wf/check-no-naming-channel.sh` and grep confirm no `os.WriteFile` / `os.Create` /
  `os.MkdirAll` takes a workspace path anywhere in `daemon/`.

**Residual:** `os.Root` does not prohibit crossing a bind mount or reaching `/proc` special
files *inside* the root (documented in the Go stdlib). Unchanged from the read path, and out
of scope here, but worth stating rather than discovering later.

## 2. Can the caller influence the file name or its location?

No, and this is the property the whole design rests on. Path traversal, double extensions
(`x.png.sh`) and overwriting an existing file are three problems with one shared entry point;
removing the entry point removes all three and leaves no validation code to get wrong.

- `filesystem.upload` is `{session_id, data}` with `additionalProperties:false`. No
  `filename`, `path`, `directory`, `extension`, `mime` or `overwrite`.
- Five golden invalid fixtures (`with-filename`, `with-path`, `with-mime`, `non-base64`,
  `oversize`) are rejected identically by Python, Go and TypeScript (`make contract`).
- `test_scope_guards.py::test_scope_007b_the_upload_request_cannot_name_the_file` asserts the
  schema's property set directly.
- `GATE-WF-NO-NAMING-CHANNEL` re-checks the schema, the four consumer code paths, that the
  daemon generates the ULID itself, and that the extension comes from the content sniff.
  It was **negative-tested**: adding a `filename` property to the schema makes it exit 1.
- The name is `<ULID>.<sniffed ext>`; `TestSaveImageNamesAreDaemonGenerated` asserts 26
  Crockford base32 characters, no separators, no duplicates across 20 drops.
- `O_EXCL` on create: a collision is an error, never a silent overwrite
  (`TestCreateExclusiveRefusesExistingFile`).

**Recorded for the next reviewer:** this property does **not** generalise. Editing must let a
client name a file, and will need its own protections (path normalisation, inode binding via
`RealRel`, the sensitive-file policy applied in the write direction, refusing symlink
creation, protecting `.git/`). ADR 0024 §4 says so explicitly so that neither mistake —
citing this to block editing, or citing editing to add a `filename` here — is available.

## 3. What is the real exposure of the 8 MiB request frame?

`filesystem.upload` is the first **request** type allowed the larger bound, and the first in
the Central→daemon direction; the node's decode limit widens from 64 KiB to 8 MiB for this
one type.

Who can reach it, in order:

1. An authenticated user holding `file.upload` (Admin/Developer; Viewer is refused before
   the node is contacted — `test_viewer_may_browse_but_not_upload` asserts `fake.calls == []`).
2. Central's 4 MiB cap: `Content-Length` first, then enforced again while streaming, because
   the declared length is the sender's claim
   (`test_a_lying_content_length_does_not_get_past_the_cap`).
3. The wire schema's `maxLength` of 5592408 — the base64 length of 4 MiB — so an over-limit
   frame is refused *before* it is decoded.
4. The daemon's own 4 MiB check after decode, because Central is not the only conceivable
   caller.
5. The cumulative quota (64 MiB per session, 200 files per day).

The peer on that link is an authenticated Central. The response type,
`filesystem.uploaded`, is a path and three scalars and deliberately keeps the tight bound —
only the direction carrying an image needed the room. `TestClassifyCorpus`-adjacent codec
tests assert `filesystem.upload` is in the large set and `filesystem.uploaded` is not.

## 4. Could stored content be executed as something else?

- Files are `0600` inside `0700` directories (`TestSaveImagePermissions`).
- The extension is derived from the content sniff, so a name can never disagree with the
  bytes; `TestSaveImageRejectsNonImages` covers ELF, PDF, SVG, plain text, a truncated PNG
  and a RIFF container that is not WebP.
- The upload directory is not on any `PATH`, and nothing in the platform executes it.
- SVG is refused deliberately: it is executable XML, and the CLIs do not treat it as an image.

**Stated plainly rather than left implicit:** on a node in the ADR 0023 posture the CLI runs
without a sandbox, so it already has full filesystem access as the service user — which on a
privileged node is one `sudo` from root. Image drop does not widen that; it does mean a user
who can drop a file can put arbitrary bytes where such a CLI might read them. That is the
existing posture, and the reason ADR 0024 refuses to inherit ADR 0023's "disposable VM"
premise: a rebuilt VM does not restore a damaged workspace.

## 5. Does Central retain any bytes?

No temp file, no database row, no log line, no metrics label. The body is read under a cap,
base64'd, forwarded, and dropped when the function returns. The audit entry records the
session, node, mime, byte count and the stored path — the path is the platform's own
invention, so it leaks nothing about the node's existing tree — and
`test_a_successful_drop_is_audited_with_the_path_but_not_the_bytes` asserts the image is not
in the metadata. The client's original filename never enters the system at all: it is not on
the wire, not in the name, not in the audit.

The `mime` metrics label is content-derived, which normally warrants suspicion; it is safe
here only because the wire contract closes the set at four values, so it cannot grow with
user input. That reasoning is in the label allowlist beside the entry.

## 6. Can the audit answer "who put what on this machine"?

Yes for successes, and for the two refusals worth counting:

- `file.upload` on success, with actor, session, node, mime, bytes, path.
- `FILE_UPLOAD_QUOTA_EXCEEDED` is marked audited, so repeated probing is visible.
- `authz.denied` covers a caller without the action.

An audit-write failure is counted (`filesystem_audit_error_total{action=upload}`) and logged
rather than failing the request — the file is already on the node, so failing the response
would not un-write it, and the gap stays visible.

## 7. Did relaxing the classifier let anything through?

The change is **stricter in one direction and looser in the other**, and both were measured:

- Looser: valid UTF-8 is no longer misjudged. 20 real files on this repository, 0 after.
  `scripts/wf/classify-scan.sh` asserts 0 across every tree and is a runnable gate.
- Stricter: the old 8 KiB window never examined what followed it, so a binary file with a
  printable prefix was served as text — `FR-FILE-004.AC-02` did not hold.
  `TestClassifyNulAnywhere` pins NUL detection at seven offsets including 8191/8192/8193.
- The 35-fixture corpus (`GATE-WF-CLASSIFY-CORPUS`) is committed data with a fixed
  expectation table, deliberately independent of the code, and the test fails if a fixture
  exists without an expectation. Relaxing the rules without noticing is the failure it exists
  to catch.
- `unsupported_encoding` denies preview exactly as before; it only changes what the user is
  told. No content is rendered for it.

## 8. Will W1–W4 carry the next write path?

Walking "file editing" through the four rules, as the plan asks, so the next author starts
from a real answer:

| Rule | Holds for editing? |
|---|---|
| **W1** confined by `workspace.Root` | **Yes, unchanged.** The write methods added here are the ones editing would use. |
| **W2** bounded | **Partly.** Per-write size transfers; a cumulative quota does not obviously apply to editing a user's own files, and retention certainly does not. Editing needs its own answer to "what stops this filling the disk" — probably per-write size plus the existing preview cap, but that is a decision, not an inheritance. |
| **W3** audited per write | **Yes**, and the shape is reusable: actor, session, node, path, byte count, never content. |
| **W4** refusable by the node | **Yes**, and it should be a *separate* switch from `filesystem.upload.enabled`. A node that accepts a screenshot has not agreed to let the browser rewrite its source. |

What editing needs beyond W1–W4, none of which exists today:

1. The client names the file, so path normalisation and inode binding (`RealRel`) move from
   the read path to the write path.
2. The **sensitive-file policy must apply in the write direction**. Today it only blocks
   reads; nothing stops a write to `.env` because nothing can write at all.
3. `.git/` needs explicit protection: a write there is not editing a file, it is rewriting
   history.
4. Concurrency — two writers, or a write against a file changed on disk since it was read.

**Conclusion:** ADR 0024's rules are sound as a floor and were worth writing down, but they
are not sufficient for editing. Editing needs its own ADR, and items 2 and 3 above are the
ones most likely to be forgotten, because neither has any present-day analogue to copy.

---

## Findings

No open findings. Two items recorded as accepted rather than fixed:

1. **`enabled` defaults to true**, so upgrading acquires the behaviour without anyone
   choosing it. Accepted per ADR 0024, mitigated by the release note, the runbook, and a
   startup log line that distinguishes the default from an operator's choice. The same trade
   as ADR 0023 D2.
2. **WebP was not measured end to end.** No WebP encoder exists on the machine that ran
   `WF-01`, so three of the four accepted formats were verified against real CLIs. The
   sniffer's WebP branch is unit-tested against a correct RIFF/WEBP container. If a real
   WebP turns out to be rejected downstream, removing it is a one-constant change.
