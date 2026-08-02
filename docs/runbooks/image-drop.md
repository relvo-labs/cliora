# Runbook — image drop into a workspace

Covers the one path by which the platform writes to a node (ADR 0024, `plan/13`).
Everything here is done **on the node**; the platform cannot change any of it.

## What it does

A user hands a PNG/JPEG/GIF/WebP to the CLI from the browser. The daemon stores it at

```text
<workspace>/.cliora/uploads/<UTC date>/<ULID>.<ext>
```

and the console types that relative path into the terminal. The daemon chooses the
directory and the file name; the request carries bytes and a session id, nothing else.

Limits, all in `/etc/agentd/config.yaml` under `filesystem.upload`:

| Key | Default | On breach |
|---|---|---|
| `enabled` | `true` | `FILE_UPLOAD_DISABLED`, and the console hides the affordance |
| `max_bytes` | 4 MiB | `FILE_UPLOAD_TOO_LARGE`, nothing written |
| `max_session_bytes` | 64 MiB | `FILE_UPLOAD_QUOTA_EXCEEDED` |
| `max_files_per_day` | 200 | `FILE_UPLOAD_QUOTA_EXCEEDED` |
| `retention_days` | 7 | pruned at session start and every 6 h |

## Turning it off for a node

```bash
sudo sed -i 's/^\(\s*\)enabled:.*/\1enabled: false/' /etc/agentd/config.yaml  # under filesystem.upload
sudo agentd config validate
sudo systemctl restart agentd
agentd doctor | grep image-upload      # expect: image-upload=disabled
```

Then confirm the platform agrees: the node's detail page must stop offering the drop
affordance. If it still offers it, the node has not re-registered — check the connection
rather than re-editing the config, because `image_upload` travels on `node.register`.

**`enabled` is `true` when the key is absent.** An upgraded node therefore accepts image
drop without anyone choosing that; the startup log says so explicitly when the value came
from the default rather than from the file. That line is the one to look for when someone
asks "who turned this on".

## Clearing a workspace

```bash
du -sh /path/to/workspace/.cliora/uploads
rm -rf /path/to/workspace/.cliora/uploads/2026-07-*     # whole days are safe to remove
```

Safe to delete: anything under `uploads/`. The daemon recreates the tree on the next drop
and removes emptied day directories itself.

**Do not delete `/path/to/workspace/.cliora/.gitignore`.** It contains `*` and is what keeps
dropped images out of the user's commits. The daemon writes it once, on first use, and never
overwrites it — so if you delete it, it comes back only on the next upload, and any images
dropped in between will show up in `git status`.

## "The image did not appear"

1. `agentd doctor | grep image-upload` — disabled, or a `[FAIL]` naming `.cliora`?
   A `[FAIL]` means `.cliora` exists but is not a directory (someone created a file, or a
   symlink, with that name). Remove it; the daemon refuses to write through it by design.
2. Disk: `df -h` on the workspace's filesystem. `FILE_UPLOAD_FAILED` is usually this.
3. Quota: `find <workspace>/.cliora/uploads -type f | wc -l` and `du -sh` against the two
   limits above.
4. The audit trail answers "was it stored": filter on action `file.upload`. The entry has
   the session, the node, the mime, the byte count and the stored path. It never has the
   image, and never the user's original filename — that string is not kept anywhere.

## "The CLI cannot see the image"

The path is relative to the CLI's working directory, which is the workspace the session was
started in. Measured on claude 2.1.220 and codex-cli 0.146.0: both read a bare relative path
with no `@` prefix (`plan/13/08-measurements.md` §4). If a CLI reports "file not found":

```bash
sudo -u <agentd-user> ls -l <workspace>/.cliora/uploads/<date>/
```

Files are `0600` and directories `0700`, owned by the service user — which is also the user
the CLI runs as. If the owner differs, the session was started by a different user than the
one that stored the image, which is not a configuration this release supports.

## "This file will not preview" (unrelated to uploads, same subsystem)

Run the classifier against the file on the node:

```bash
cd /path/to/cliora/daemon && go run ./internal/files/classifyscan <path>
```

It prints one of three verdicts. `unsupported_encoding` means the file is text but not
UTF-8 (Big5, GBK, Shift-JIS, UTF-16) — convert it with `iconv` and it will preview.
`binary` means it contains a NUL byte or too many control characters. A **valid UTF-8 file
reported as binary is a bug**, not a configuration problem: capture the file's size and
the first bytes and open an issue (`FR-FILE-008.AC-01`).
