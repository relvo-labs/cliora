# Release note — general file upload

Ships in `agentd` 0.7.0, contract v1.9.0, migration `0020`. ADR 0026, `plan/15`.

## 1. `file.upload` now means more than it did — read this first

The permission has not moved: Admin and Developer hold it, Viewer does not, and
that is unchanged. What it *authorises* has widened.

| Before | After |
|---|---|
| Drop an image into a directory the daemon named (`.cliora/uploads/`), under a name the daemon invented. | That, **plus** placing a file of any type at a directory and filename the user chooses, anywhere in the session workspace the policy allows. |

An organisation that granted `file.upload` for screenshots has, after upgrading,
granted more. **There is no way to keep only the older half from the platform
side** — the only place to draw that line is on the node:

```yaml
filesystem:
  upload:
    files:
      enabled: false     # refuse general file upload; image drop is unaffected
```

Two switches, deliberately: accepting a screenshot into a platform-owned
directory and accepting an arbitrary file anywhere in a source tree are
different-sized grants, and a machine's owner is entitled to answer them
differently. `filesystem.upload.enabled` still controls image drop alone.

For context on the size of the change: both holders of `file.upload` also hold
`terminal.operate` on the same node, so both could already write files there
through a terminal. This is a new interface, not a new capability — but it is one
that is bounded, audited, and cannot destroy anything, which the terminal is not.

## 2. What users get

Drag a file onto a row of the file tree and it lands in that directory. Dropping
on a *file* row targets its parent, and the row shows the destination while you
drag, so there is nothing to guess. A toolbar button with a file picker does the
same thing for keyboard and touch users.

- **Up to 4 MiB per file**, up to 20 files per drop, uploaded one at a time.
- **Any file type.** Unlike image drop there is no sniff and no allow-list.
- **Never overwrites, and never deletes.** A name that is already taken is refused
  and the upload list offers 〔改名重試〕 with a suggested name. To *replace* or
  *remove* a file, use a terminal session on the node — the console has no way to
  do either, on purpose (see §6).
- **Files land `0644`.** Nothing arrives executable; `chmod +x` stays a decision
  you make knowingly.
- **Folders are refused**, with a message pointing at `git clone` / `scp` / `tar`.

Refused because of the policy: `.git` (including the `gitdir:` *file* a worktree
or submodule uses), `.cliora/`, tool-owned trees (`node_modules`, `.venv`, `dist`,
`build`, `__pycache__`), and sensitive names (`.env`, `*.pem`, `id_rsa`, …). The
rule is the one already used for previews: the platform does not write to a
location, or under a name, that it would refuse to show you.

## 3. Upgrade acquires the behaviour

`filesystem.upload.files.enabled` defaults to `true`, so an upgraded node accepts
file upload without anyone choosing that — the same trade as ADR 0023's sandbox
posture and ADR 0024's image drop, and stated here for the same reason. `agentd
doctor` reports whether the value was set or inherited:

```
[info] file-upload=enabled (default) max=4.0 MiB/file quota=256.0 MiB/session min-free=512.0 MiB
[info] file-upload:/srv/work free=134.1 GiB
```

Bounds, all configurable under `filesystem.upload.files`: 256 MiB per session,
200 files per day, and a 512 MiB free-space floor. The per-file 4 MiB ceiling is
shared with image drop and is dictated by the wire frame rather than by taste;
see the runbook before raising it.

**There is no retention sweep on this path, and there will not be one.** Image
drop expires files after 7 days because `.cliora/uploads/` is a directory the
platform named and therefore owns. An uploaded file sits where the *user* put it,
so it is the user's data; deleting it on a timer would be the opposite of what a
quota is for. What bounds the disk instead is the free-space floor.

## 4. Observability: one dashboard change

**`filesystem_upload_bytes` has changed its label from `mime` to `source`**
(`image` | `file`). Any dashboard or alert grouping by `mime` on that series will
break. There is no `mime` to report on the new path — nothing sniffs a content
type — and a label that is always empty is worse than one that is honest.

New: `filesystem_store_refused_total{code}`. It exists for exactly one future
decision — whether the 4 MiB ceiling should become a chunked upload — so that the
argument can be made from data rather than from anecdote.

`filesystem_request_total` gains `op="store"`.

## 5. Two corrections to older behaviour

**`FILE_UPLOAD_QUOTA_EXCEEDED` used to give impossible advice.** It told users to
"delete images you no longer need from `.cliora/uploads/` in the file tree" — and
the file tree has never had a delete affordance. This round adds file upload, not
delete, so the message now points at the terminal, which is where it can actually
be done. Both the API catalogue and the console text are corrected.

**`.git` was not protected against writes.** It appeared only in
`workspace.excluded_directories`, whose own documentation says it is an ignore
rule and not a security control. It is now refused for uploads in both of its
shapes — the directory, and the `gitdir:` file that a worktree or submodule uses.
The *read* direction is unchanged: `.git/config` remains previewable, because
hiding a batch of currently-visible files needs its own release note and belongs
to its own round.

## 6. Deleting is a terminal operation — and that is now a decision, not a gap

**The console has no way to delete, rename or edit a file in a workspace, and will
not grow one.** Removing or replacing something is done on the node, in a terminal
session. That includes the images image drop writes into `.cliora/uploads/`.

This is a product decision taken on 2026-08-03, not an unfinished feature, and the
difference matters to anyone reading the docs: "not built yet" invites a plan, and
a plan for deletion drags version preconditions, a trash can and undo semantics
back in with it. A design for exactly that exists in `plan/14` and was withdrawn as
too large a change; the directory is kept so the reasoning survives.

What you get instead is a property worth more than the feature: **both write paths
only ever *add* a file.** Neither can replace or remove one, so the console cannot
be used to lose work — and a scope guard fails the build if that stops being true.

Every place that used to suggest otherwise has been corrected: the
`FILE_UPLOAD_QUOTA_EXCEEDED` text (§5), ADR 0015's scope line, ADR 0024's
"not decided here" list, the PRD, `research/tech.md` §11.9, and both runbooks. If
you find a page telling a user to delete something from the file tree, it is stale.

Download remains genuinely unbuilt. Chunked upload for larger files, and folder
upload, are open with no committed date.
