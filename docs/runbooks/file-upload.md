# Runbook — general file upload

Covers `POST /api/sessions/{id}/files/upload` and the file tree's drop target
(ADR 0026, `plan/15`). For the screenshot path see
[`image-drop.md`](image-drop.md) — the two are **separate switches** and turning
one off does nothing to the other.

## What this path does, in one paragraph

A user drags a file onto a row of the file tree (or uses 〔上傳檔案〕) and it
lands in the workspace under the name they gave it. It **never replaces
anything**: a name that is already taken is refused with `FILE_EXISTS` and not one
existing byte is touched. Files land `0644`, so nothing arrives executable.

## The console cannot delete anything — read this before answering a ticket

**There is no delete, rename or edit affordance anywhere in the console, and there
will not be one.** It is a product decision (2026-08-03), not an unfinished
feature: removing or replacing a file in a workspace is done **on the node, in a
terminal session**. That includes the images image drop writes into
`.cliora/uploads/`.

Two consequences worth having ready:

- **"How do I delete the file I just uploaded?"** — open a terminal on that
  session and `rm` it. There is nothing to click, and suggesting otherwise sends
  the user looking for a button that does not exist.
- **Nothing the console does can lose a user's work.** Both write paths only ever
  *add* a file. If a user reports that a file disappeared or changed, the console
  did not do it — look at what the CLI in that session was doing.

An older version of `FILE_UPLOAD_QUOTA_EXCEEDED` told users to "delete images from
`.cliora/uploads/` in the file tree". That was never possible and the text is
corrected; if you see it anywhere else, it is stale.

## Turning it off

```yaml
# /etc/agentd/config.yaml
filesystem:
  upload:
    files:
      enabled: false
```

Then restart `agentd` and check three things in order:

1. `agentd doctor` prints `file-upload=disabled (filesystem.upload.files.enabled: false)`.
2. The node's `node.register` reports `file_upload: false` — visible on the node
   detail page in the console.
3. The file tree in a session on that node offers no drop target and no
   〔上傳檔案〕 button.

**This does not disable image drop.** That is `filesystem.upload.enabled`, and the
two are deliberately separate: accepting a screenshot into `.cliora/` and accepting
an arbitrary file anywhere in the workspace are different-sized grants.

Note that the default is `true`, so **a node acquires this on upgrade** without
anyone choosing it. The permission side is unchanged (`file.upload`, held by Admin
and Developer) — but that action now means more than it did, and both of its
holders could already write files on the node through a terminal.

## "I can't upload this file"

Read the error code first; four of the five are working as designed.

| The user sees | What it means | What to do |
|---|---|---|
| 已經有同名的項目 (`FILE_EXISTS`) | Working as designed: upload never replaces. | Use 〔改名重試〕, or replace the file from a terminal. |
| 這個位置或檔名不開放上傳 (`FILE_DENIED`) | Policy: `.git`, `.cliora/`, an excluded directory (`node_modules`, `.venv`, `dist`, `build`, `__pycache__`), or a sensitive name (`.env`, `*.pem`, `id_rsa`…). | `scripts/fu/write-policy-scan.sh <dir>` lists every refusal in a tree with its classification. The error names only the first one it hit. |
| 超過 4 MiB 上限 (`FILE_UPLOAD_TOO_LARGE`) | Per-file ceiling, shared with image drop. It comes from the control-frame budget, not from taste. | Use the terminal (below). Raising it is not a config-only change — see "Raising the size limit". |
| 磁碟空間不足 (`FILE_UPLOAD_NO_SPACE`) | Free space is below `min_free_bytes`, or below twice the file's size. | Free space on the node. `agentd doctor` prints the figure it compared against. |
| 用量已達上限 (`FILE_UPLOAD_QUOTA_EXCEEDED`) | Per-session bytes (256 MiB) or per-day files (200). Counters are in memory and reset when `agentd` restarts. | Wait, restart the daemon, or raise the keys under `filesystem.upload.files`. |
| 檔名不可包含 / (`FILE_INVALID_NAME`) | A filename must be one path segment, ≤255 **bytes**. | Rename. Note the limit is bytes: 84 CJK characters plus an extension is 256 bytes. |

## "Which files were uploaded, and by whom?"

The audit trail, action `file.upload`:

```sql
SELECT created_at, user_id, session_id, metadata
FROM audit_logs
WHERE action = 'file.upload' AND metadata->>'source' = 'file'
ORDER BY created_at DESC LIMIT 50;
```

`source` separates the two upload paths — `file` here, `image` for screenshots.
The metadata carries the workspace-relative path the user chose and the byte
count. It never carries the content.

Nothing in the audit distinguishes an upload from a file the CLI wrote, on the
node itself: an uploaded file is an ordinary file in an ordinary place. That is
deliberate (see the next section) but it does mean the audit trail is the only
record that the platform put it there.

## Disk: there is no cleanup, and that is the design

Image drop writes into `.cliora/uploads/`, which the platform named and therefore
owns, so it sweeps files older than 7 days. **This path has no sweep and must not
grow one.** The file landed where the *user* chose, so it is the user's data from
the moment it arrives; deleting it on a timer would be the opposite of what a
quota is for (ADR 0024's W2 as refined by ADR 0026 §5).

What bounds the disk instead:

- `min_free_bytes` (default 512 MiB) — refuses an upload that would leave less
  than that, or less than twice the file's size.
- `max_session_bytes` (256 MiB) and `max_files_per_day` (200), counted in memory.

If someone asks where the cleanup job is: there isn't one, and that is the answer.

```
$ agentd doctor
[info] file-upload=enabled (default) max=4.0 MiB/file quota=256.0 MiB/session min-free=512.0 MiB
[info] file-upload:/srv/work free=134.1 GiB
```

A root whose free space is under the floor is reported as a **fault**, not an
info line, because it is the one condition that starts refusing uploads silently
and nothing will eventually free space on its own.

`min_free_bytes: 0` turns the check off. Worth doing on a node whose filesystem
reports meaningless figures — some container overlays do. The daemon also fails
*open* if `statfs` itself errors: this is a guard against filling a disk, not a
security boundary, and it logs `filesystem.store_freespace_unknown` when it
skips.

## Larger files: what to tell the user

The 4 MiB ceiling exists because the file crosses the node's control connection
inside one frame. The alternative is the terminal, and the runbook should give
them the command rather than the disappointment:

```bash
# from the user's own machine, into the session workspace
scp big.tar.gz user@node:/srv/work/api/

# or on the node, in the session's terminal
curl -LO https://example.com/dataset.parquet
git clone https://github.com/org/repo.git vendor/repo
tar xzf big.tar.gz
```

Folders are the same answer: dropping one is refused outright, deliberately, and
`git clone`/`scp -r`/`tar` are what to reach for.

### Raising the size limit

`filesystem.upload.max_bytes` is shared by both upload paths and is bounded by the
wire frame: 4 MiB of file is 5.33 MiB of base64, inside the 8 MiB
`MAX_FILE_PAYLOAD`. Raising the key past roughly 5.5 MiB means the node will
silently drop the frame and the request will **time out** rather than fail
cleanly. `TestUploadCapFitsFrameBound` fails first if you try, which is the
intended tripwire. Genuinely larger uploads need chunking, which needs its own
ADR.

## Two smaller things worth knowing

**The same-looking name can be two files.** Uploads are passed through
byte-for-byte with no Unicode normalisation, so `café.txt` composed (NFC, 9 bytes)
and decomposed (NFD, 10 bytes) are two distinct files on ext4 — verified. A user
reporting "there are two identical files" is seeing this, and it is not a bug in
the upload path.

**An uploaded file is visible before it is complete.** The file is created under
its final name and then written, so a tool watching the directory can briefly see
a short file. The window is one write of at most 4 MiB to a local disk. The
alternative — write to a temp name and rename into place — would silently replace
an existing file, which is the one thing this path must never do.
