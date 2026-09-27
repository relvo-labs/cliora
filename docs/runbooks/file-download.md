# Runbook — workspace file download

Covers `GET /api/sessions/{id}/files/download`, the preview toolbar's 下載 button
and the download offer in the "cannot preview" pane (ADR 0028, `plan/30`). For
the two write paths see [`file-upload.md`](file-upload.md) and
[`image-drop.md`](image-drop.md) — **all three are separate switches** and turning
one off does nothing to the others.

## What this path does, in one paragraph

A user opens a file in the console and takes a copy of it. The bytes are read on
the node, relayed through Central without being stored anywhere, and delivered to
the browser as an opaque attachment. Up to 4 MiB per file, one file per request,
no ranges. Sensitive files are refused by the same policy that refuses to preview
them; binary files are not refused, because that is what this path is for.

## Viewer can download — read this before answering a ticket

Download is authorised by `file.browse`, which **all three roles hold**, Viewer
included. That is a decision (ADR 0028 §5), not an oversight, and it is not
changeable from the platform: with three fixed roles there is no way to express
"may preview but may not download".

Two consequences worth having ready:

- **"Why can our read-only users take files?"** — because download is a read, and
  the role that can read a file on screen is the role that can read it. If that
  is not the posture you want for a machine, the answer is the node switch below,
  not a role change.
- **"Was this always true?"** — no. Before agentd 0.8.0 a `file.browse` holder
  could see at most 2 MiB of UTF-8 text per file and no binary at all. See the
  release note's first section.

## Turning it off

On the node:

```yaml
filesystem:
  download:
    enabled: false
```

Restart the daemon. It re-registers, reports `file_download: false`, and the
console stops showing any download control for that node. A direct API call
returns `403 FILE_DOWNLOAD_DISABLED`.

**Absent means on.** A config with no `download:` block downloads, and the daemon
says so in its startup log (`DownloadFromDefault`) precisely so that "the operator
chose this" and "an upgrade did this" stay distinguishable.

## Checking a node's current posture

The node is the authority; Central holds a cache from the last `node.register`.

```sql
SELECT name, hostname, image_upload, file_upload, file_download
FROM nodes WHERE deleted_at IS NULL ORDER BY name;
```

The column is indexed for exactly this question — "which of my machines will send
files to a browser" — asked across a fleet.

On the node itself, `agentd doctor` reports the effective value, which is the one
that will actually be applied; the database row can be stale if the daemon has not
reconnected since the config changed.

## Answering "what left this machine"

Every successful download writes one `file.download` audit row.

```sql
SELECT created_at, user_id, session_id, metadata->>'path' AS path,
       metadata->>'size_bytes' AS bytes
FROM audit_logs
WHERE action = 'file.download' AND node_id = :node
ORDER BY created_at DESC;
```

Or in the console: **稽核 → 工作區 / Workspace → 下載檔案**.

Two things this trail does and does not give you:

- It records **successes**, not attempts. A refused download writes no row — the
  refusal happened before any byte was read, and the file was never touched.
- It records the **path and the byte count, never the content**. There is no way
  to reconstruct what was in the file from the audit table, and that is deliberate:
  a table every `audit.view` holder can read is not a place to put file contents.

## Common refusals

| Code | HTTP | What happened | What to tell the user |
|---|---|---|---|
| `FILE_DENIED` | 403 | The file matches the sensitive-file policy — the same one that refuses to preview it. | Nothing to retry. If the file genuinely needs to be on that machine and readable, that is a `denied_patterns` decision for the node's owner. |
| `FILE_TOO_LARGE` | 413 | Over 4 MiB. | Use a terminal session on that node, or port forwarding if a process serves it. |
| `FILE_NOT_FOUND` | 404 | Gone, or never accessible. | Refresh the file tree. |
| `FILE_DOWNLOAD_DISABLED` | 403 | The node's switch is off. | Nothing from the browser; the node's owner controls this. |
| `NODE_OFFLINE` | 409 | The daemon is not connected. | Wait for reconnect; check the node's status. |
| `REQUEST_TIMEOUT` | 504 | The node did not answer within 20 seconds. | Retry. If it repeats, the node is wedged — check it. |

## Things that are not incidents

- **A 4 MiB refusal.** The ceiling is a frame-budget fact, not a policy that was
  set low by accident: 4 MiB of file is 5.33 MiB of base64, which is what fits the
  existing 8 MiB frame bound. Raising it means changing the frame bound too, which
  is a contract change.
- **No rate limit and no quota.** There is none, deliberately (ADR 0028 §10): a
  read consumes nothing that can run out, so a counter here would bound nothing
  while implying it bounded something. What bounds this path is RBAC, the
  sensitive-file policy, the node switch, and the audit row.
- **A file that previews but a colleague cannot download.** Check the node's
  `file_download`, not the user's role — the two conditions are separate and the
  console hides the control when either is false.

## If you need to see how much is leaving

`filesystem_download_bytes` on the node (`agentd metrics`), and
`filesystem_request_total{op="download"}` for outcomes by code. These exist
*because* there is no quota: the number an operator actually wants is how much
left, not how much was refused by a counter.
