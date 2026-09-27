# ADR 0028 — Workspace file download: the read path that hands over bytes

- Status: accepted
- Date: 2026-09-16
- Related: ADR 0014 (path security; `workspace.Root` confinement, which §3 rests
  on entirely), ADR 0015 (preview policy and limits — this ADR keeps its
  sensitive rule and drops its binary rule, §3), ADR 0016 (RBAC is one table),
  ADR 0024 (write posture, W1–W4 — the node-switch pattern in §6 and the
  "Central holds no byte" rule in §8 are taken from it unchanged), ADR 0026
  (general file upload — this is the item its Consequences listed first under
  "Not decided here")
- Requirements: `FR-FILE-011`, `NFR-005.AC-109` (closed), `NFR-005.AC-142`
  (one clause extended to the read direction)
- Contract: v1.10.0
- Ships in: `agentd` 0.8.0 (migration `0021`)
- Plan: `plan/30/`

## Context

ADR 0026 ended with a list: *Not decided here: **download**, editing, rename,
delete, folder upload, chunked upload, and overwrite.* Six of those seven were
decided against — the PRD records editing, rename and delete as belonging to the
CLI and the terminal, by product decision rather than by deferral. Download is
the one item on that list that was deferred rather than declined, and
`NFR-005.AC-109` has been tracking it in the open since 2026-08-03:

> 18. Web 端上傳與下載檔案。
>     *（2026-08-03：一般檔案上傳已由 `FR-FILE-010` 交付。仍為未來擴充的是**下載**）*

Asked for on 2026-09-16: add the ability to download files from a node in the
front end.

Two things already in the tree shape this round more than the request does.

**First**, there is already a read path, and it cannot be the one. `filesystem.read`
(ADR 0015) returns a ≤2 MiB UTF-8 *preview*: it refuses binary content by design,
refuses a file that is merely not UTF-8, and returns text in a JSON body. Every
one of those is correct for an editor pane and wrong for a download. The question
this ADR has to answer is therefore not "how do we send bytes" but **which of the
preview path's refusals survive when the destination is a file on a laptop
instead of a Monaco model**.

**Second**, ADR 0026 §4 left behind a sentence that was written about the write
direction and reads like a law: *the platform does not write to a location, or
under a name, that it would refuse to show you.* The tempting move is to mirror
it verbatim — "the platform does not hand over a file it would refuse to show
you" — and that mirror is **half right**, which is worse than either wholly right
or wholly wrong. §3 is where it gets split.

## Decision

### 1. One new type pair, not a flag on the existing one

`filesystem.download` carries `{session_id, path}` — the same two fields as
`filesystem.read` — and `filesystem.downloaded` returns `{path, size,
modified_at, data}`.

A `raw: true` flag on `filesystem.read` was the obvious smaller change and it is
rejected, because it makes one message type carry two policies. The two paths
answer differently for the same file in **both** directions:

| the file | `filesystem.read` | `filesystem.download` |
|---|---|---|
| a 300 KiB PNG | denied — binary | allowed |
| a Big5 `.txt` | denied — unsupported encoding | allowed |
| a 3 MiB source file | denied — over the 2 MiB preview cap | allowed |
| a 3 MiB `.env` | denied — sensitive | **denied — sensitive** |
| a 30 MiB `.tar.gz` | denied — oversize | denied — oversize |

A flag would mean a reader of the handler has to hold both columns in their head
at once to know what any given line applies to, and the line that must never be
skipped — the sensitive check — is the one that looks identical in both columns.
Two types means each policy is written once, in full, next to the other
(`daemon/internal/files/download.go` sits beside `read.go` deliberately).

### 2. The request names a file and nothing else

`filesystem.download` has `additionalProperties: false` and no `offset`,
`length`, `range`, `encoding`, `mime` or `disposition` field. This is the same
rule as 1.4.0's `daemon.update`, 1.6.0's `tunnel.open` and 1.8.0's
`filesystem.upload`, applied to a fourth type, and here it buys two things:

- **No range means no partial-read state machine**, and therefore no assembly,
  no timeout cleanup and no partial-landing story — the same three costs ADR 0026
  refused for chunked upload. See §9.
- **No disposition or mime field means the caller cannot influence how the
  browser treats the bytes.** That is not hypothetical: a `mime` the platform
  echoed would be the field someone eventually points at an HTML file in a
  workspace, served from the console's own origin. §4 closes that off at the
  other end as well, so it is shut twice.

### 3. Which of the preview's refusals survive

The mirror of ADR 0026 §4 is half right, and the useful form is two sentences
rather than one:

> **the platform does not hand over a file it would refuse to show you —
> but it will hand over one it merely cannot render.**

The first clause is the security rule and it is unchanged: the download path
calls **the same** `policy.SensitiveClassification` the preview calls, in the
same default-deny order, twice (on the requested path, then on the fd's resolved
name so the decision binds to the opened inode). `.env`, `*.pem`, `id_rsa`,
`.ssh/`, the configured `denied_patterns` and `denied_directories` are all
refused here exactly as they are refused there, by one implementation.

The second clause is the feature. `FILE_BINARY` — the classification step — is
**absent** from this path, because "we cannot show you this in an editor" is a
statement about the editor and not about the file. A user downloading a `.png`,
a `.parquet`, a `.tar.gz` or a Big5 `.csv` is doing an ordinary thing, and the
only reason the platform has ever refused them is that it had nowhere to put
them.

It is worth being exact about what this does *not* claim. It does not claim that
a `file.browse` holder could not have obtained a secret before: they could ask
the CLI to print one, if they also hold `terminal.operate`. It claims something
narrower and checkable — **the platform itself is not the mechanism**, and the
same function decides that in both directions. That is the property a reviewer
can verify by reading one function, which is why it is worth keeping intact.

### 4. Central answers as `application/octet-stream`, always

Three response headers, and they are a set:

- `Content-Type: application/octet-stream` — never sniffed, never node-supplied.
- `X-Content-Type-Options: nosniff` — which is what stops a browser from
  overruling the line above.
- `Content-Disposition: attachment` — so it is saved, not displayed.

The reason is the console's own origin. A workspace can contain an `.html`, an
`.svg` or a `.xhtml` file, and any of those served inline from the console's
origin with a renderable content type is stored XSS with the platform's cookies
in scope. Serving everything as an opaque attachment removes the question rather
than answering it per file type — and it is why `filesystem.downloaded` has no
`mime` field for Central to be tempted by (§2).

The filename travels in `Content-Disposition` in both RFC 6266 forms
(`filename=` ASCII fallback, `filename*=UTF-8''…`). The browser's `download`
attribute is *not* relied on, because it is honoured for same-origin blobs and
ignored for cross-origin ones, which would make the saved filename depend on
deployment topology.

### 5. Authorisation reuses `file.browse`, and that widens it

No new RBAC action. `file.browse` **widens in meaning**, from "list, search and
preview a workspace" to "…and obtain the exact bytes of a file in it". Its
holders are unchanged: Admin, Developer and **Viewer**.

Reasons, in the order they actually weighed:

1. **The verb is the same.** ADR 0024 §6 refused to fold upload into
   `file.browse` because writing is not reading; that argument does not reach
   here, and inverting it would prove too much.
2. **Three fixed roles cannot express the distinction anyway.** Nobody can say
   "may preview but may not download" with Admin/Developer/Viewer — the same
   fact ADR 0026 §6 recorded about "images but not files". A `file.download`
   action would be a flag nobody could set differently, bought with a seed
   migration and three places of matrix maintenance.
3. **Splitting it would make every "who read this workspace" audit query a
   union of two keys**, and that query is the one an investigation starts from.

**The cost is real and belongs here rather than in a footnote.** An organisation
that granted `file.browse` to a Viewer as "they can look but not touch" has,
after upgrading, granted more: that Viewer can now take a copy of any
non-sensitive file in the workspace, including binary files and files the
preview refused to render at all. It is not a new *class* of access — everything
downloadable was already listable and, if text and small, readable — but "can
read a file on screen" and "has a copy of it on a laptop" are different facts
about an organisation, and only the second one outlives every control the
platform has.

There is no way to keep only the older half except by switching this path off at
the node. **That is why the node-side switch in §6 is a condition of this
decision and not a convenience**, and why the widening is the first paragraph of
the release note rather than a note at the end of it.

### 6. The node may refuse, with its own switch

`filesystem.download.enabled` (default `true`), reported as
`node-register.file_download`. It is **separate from both upload switches**:
`image_upload` and `file_upload` say what may be written *into* this machine,
this one says what may be read *out* of it, and an operator who has thought about
exfiltration has thought about exactly this key and not those.

Report-only, the same shape as contract 1.7.0, 1.8.0 and 1.9.0 before it: the
node states its posture and the platform never selects it. Default `true` carries
the same trade as ADR 0023 D2, ADR 0024 D8 and ADR 0026 §9 — **upgrade acquires
the behaviour** — and therefore the same obligation of a release note and a
runbook, never silence.

### 7. Audit records the success, not the refusal

A new audit action, `file.download`, recording user, session, node, the
workspace-relative path, and the byte count. No content, ever.

This is the **inverse** of the preview path next door, and the inversion is the
decision rather than an inconsistency. `file.sensitive_read_denied` records a
*refusal*, because a preview that succeeded leaves nothing behind — the bytes
were on a screen and then they were not. A download that succeeded leaves a copy
of the file somewhere the platform will never see again, so the successful case
is the one that has to be answerable later.

The path is recorded, on ADR 0026 §6's reasoning: the user chose it out of a tree
they had already been shown, so it reveals nothing they did not have, and
without it W3's question — here "what left this machine" — has only a counter for
an answer.

A new *audit* action and no new *RBAC* action is not a contradiction: the two
vocabularies answer different questions. RBAC asks who may, and the roles cannot
express the distinction (§5); audit asks what happened, and "read a file" and
"took a copy of a file" are plainly different events.

### 8. Central holds no byte

The bytes are decoded, handed to the response and dropped. Nothing is written to
disk, to the database, to a log line or to a metrics label. This is ADR 0024 §5
applied in the other direction, unchanged and for the same reason: a byte stored
here would raise three questions — how long, who can read it, is it in backups —
and not storing it answers all three.

The correlation log gets ids, a byte count and an outcome code. The path goes to
the audit table and nowhere else, because an audit table has access control and a
log does not, and a path can name a confidential project as readily as a search
keyword can (ADR 0015's redaction rule).

### 9. 4 MiB, and the ceiling is a frame-budget fact

One file, up to 4 MiB, in one frame. That number is not taste: 4 MiB of file is
5.33 MiB of base64, which is inside the 8 MiB `MAX_FILE_PAYLOAD` /
`MaxFilePayload` ceiling that ADR 0024 §7 already paid for. It equals the upload
ceiling deliberately, so "what fits through Cliora" has a single answer in both
directions — but it is a **separate config key**, because an operator who wants
to narrow what leaves this machine should not have to narrow what arrives on it.

**4 MiB will be hit**, and more often than on the upload path: workspaces contain
build artifacts and datasets that no one ever uploaded. The refusal says so and
names the alternatives (the terminal; port forwarding for anything served by a
process). `filesystem_download_bytes` exists so that "add ranged download" can be
argued from a distribution rather than from an anecdote.

Chunked or ranged download is **not** done here, for the three reasons ADR 0026
gave for chunked upload — an assembly state machine, timeout cleanup, and a
partial-landing story — plus one more that is specific to this direction: a
ranged read has to decide what happens when the file changes between ranges, and
that is a version-precondition question, which is the machinery `plan/14` was
withdrawn for needing.

### 10. No quota, and that is a decision rather than an omission

The two upload paths have cumulative quotas because a write consumes the node's
disk, which can run out. A read consumes nothing that can run out, so a counter
here would bound nothing real while teaching operators that Cliora's quotas are
decorative.

What is claimed instead, precisely: the exfiltration risk on this path is held by
**RBAC (§5), the sensitive-file policy (§3), the node switch (§6) and an audit
row per download (§7)** — not by a rate limit. A rate limit would be theatre
against the case it appears to address, because a determined `file.browse` holder
can already page the preview endpoint, and a `terminal.operate` holder does not
need the browser at all.

This is the same shape of answer as ADR 0026 §5 ("who cleans this up" had two
correct answers depending on who owned the destination). Here the question is
**what can run out**, and on a read path the answer is nothing — so the next read
path should ask that question rather than copy a counter from a write path.

## Consequences

- **A user can get a file out of a workspace**, which is the last piece of
  `NFR-005.AC-109` and the most common gap left after ADR 0026.
- **`file.browse` means more than it did** (§5), including for Viewer, and an
  organisation cannot keep only the old half except at the node.
- **Binary files are reachable from the browser for the first time.** The
  preview pane's denial for a binary or non-UTF-8 file now offers a download,
  and its copy — which said the platform provides no download — was **wrong from
  this release** and is corrected rather than left standing.
- **Two ceilings now differ, visibly.** Preview caps at 2 MiB and download at
  4 MiB, so a file between them cannot be shown and can be taken. The denial
  pane says exactly that, and withdraws the offer above 4 MiB rather than
  letting the button teach the limit.
- **`filesystem.downloaded` is the sixth type allowed the 8 MiB frame bound**,
  and the bound does not move (§9).
- **The audit trail gains a success-shaped row on the read side** (§7), which is
  the first one it has had.
- **Not decided here:** ranged or chunked download, downloading a directory or
  an archive of one, downloading multiple files in one request, and any
  relaxation of the sensitive-file policy for this path.

## Alternatives rejected

| Option | Why not |
|---|---|
| A `raw: true` flag on `filesystem.read` | One type carrying two policies, where the line that must never be skipped looks identical under both (§1). |
| Let `filesystem.downloaded` carry a `mime`, and echo it | The field someone eventually trusts. Serving a workspace `.html` as `text/html` from the console's origin is stored XSS with the platform's cookies in scope (§4). |
| A new `file.download` RBAC action | A flag nobody could set differently under three fixed roles, bought with a seed migration and three places of matrix maintenance — and it would split every "who read this workspace" audit query in two (§5). |
| Reuse `file.upload`'s node switch | Reading a workspace out and writing into it are opposite directions; an operator's answer to one says nothing about the other (§6). |
| Apply the binary/encoding classification here too | It would refuse exactly the files this path exists for, and it is a statement about the editor rather than about the file (§3). |
| Drop the sensitive-file check because the user "could read it another way" | Only if they hold `terminal.operate`, which Viewer does not — and it would make the platform the mechanism, which is the one property a reviewer can check by reading one function (§3). |
| Stream the response from Central (`StreamingResponse`) | The relay answers in one correlated frame, so the file is already in memory. Streaming the handover would look like backpressure while providing none; the 4 MiB node-side ceiling is what actually bounds memory. |
| Ranged / chunked download now | An assembly state machine, timeout cleanup, a partial-landing story — and, unique to this direction, "what if the file changed between ranges", which is a version precondition (§9). |
| A per-session or per-day download quota | It would bound nothing that can run out, and would read as protection against exfiltration while providing none (§10). |
| Skip the audit row, since preview is not audited on success | A preview that succeeded leaves nothing behind; a download that succeeded leaves a copy the platform will never see again (§7). |
