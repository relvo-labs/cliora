# Release note — agentd 0.8.0: workspace file download

Ships in `agentd` 0.8.0, contract v1.10.0, migration `0021`. ADR 0028, `plan/30`.

## 1. `file.browse` now means more than it did, and Viewer holds it — read this first

The permission has not moved: Admin, Developer **and Viewer** hold `file.browse`,
exactly as before. What it *authorises* has widened.

| Before | After |
|---|---|
| List a workspace, search it by filename, and preview a file — at most 2 MiB, UTF-8 text only, never a sensitive one. | That, **plus** obtaining the exact bytes of any non-sensitive file up to 4 MiB — including binary files and files the preview refuses to render at all. |

An organisation that granted `file.browse` to a Viewer as "they can look but not
touch" has, after upgrading, granted more. It is not a new *class* of access —
everything downloadable was already listable, and if it was text and small it was
already readable on screen — but **"can read a file on screen" and "has a copy of
it on a laptop" are different facts about an organisation**, and only the second
one outlives every control the platform has.

**There is no way to keep only the older half from the platform side.** No RBAC
change can express "may preview but may not download": with three fixed roles
there is no role to put the difference in, and splitting the action would make
every "who read this workspace" audit query a union of two keys. The only place
to draw that line is on the node:

```yaml
filesystem:
  download:
    enabled: false     # this machine does not hand its workspace files back
```

Three switches now, deliberately separate. `image_upload` and `file_upload` say
what may be written **into** this machine; this one says what may be read **out**
of it. A node that accepts a dropped screenshot has not thereby agreed to send
its source tree to a browser, and an operator who has thought about exfiltration
has thought about exactly this key and not those.

**Default is `true`, so upgrading acquires the behaviour.** That is the same
trade the privileged-terminal, image-drop and file-upload switches made, and it
is why this note exists rather than silence. If your answer is no, set the key
before you upgrade.

## 2. What users get

A **下載** button in the preview toolbar, for whatever file is open.

More usefully, a download offer **in the "cannot preview" pane** — which is the
case it exists for. A PNG, a `.parquet`, a `.tar.gz` or a Big5 `.csv` has never
been reachable from the browser before, because the platform had nowhere to put
it.

Two ceilings now differ, and the pane says so:

| The file | Preview | Download |
|---|---|---|
| a 300 KiB PNG | refused — binary | **allowed** |
| a Big5 `.txt` | refused — not UTF-8 | **allowed** |
| a 3 MiB source file | refused — over the 2 MiB preview cap | **allowed** |
| a 3 MiB `.env` | refused — sensitive | **refused — sensitive** |
| a 30 MiB `.tar.gz` | refused — oversize | refused — oversize |

A file between 2 MiB and 4 MiB cannot be shown and can be taken away. Above
4 MiB the pane withdraws the offer and points at the terminal, rather than
letting a button teach the limit.

## 3. What is refused, and it is the same function as before

**The platform does not hand over a file it would refuse to show you — but it
will hand over one it merely cannot render.**

The first clause is the security rule, and it is unchanged: `.env`, `*.pem`,
`*.key`, `id_rsa`, `.ssh/`, and your configured `denied_patterns` /
`denied_directories` are refused on this path by the *same* classification
function the preview calls, applied twice — once to the requested path, and again
to the name the opened file descriptor actually resolves to, so that an
innocuously-named symlink inside the workspace cannot point at a secret inside
the workspace.

The second clause is the feature. The binary/encoding check is absent here, on
purpose: "we cannot show you this in an editor" is a statement about the editor,
not about the file.

## 4. What the platform does not keep

Nothing. The bytes are decoded, handed to the response, and dropped — no disk, no
database, no log line, no metrics label.

Every **successful** download writes one audit row: `file.download`, with the
user, session, node, workspace-relative path and byte count. Never the content.

That is the inverse of the preview path next door, which audits *refusals*, and
the inversion is deliberate: a preview that succeeded leaves nothing behind, and
a download that succeeded leaves a copy of the file somewhere the platform will
never see again.

## 5. Also changed

- **The "cannot preview" pane's copy was wrong and is corrected.** It told users
  the platform provides no download. From this release that is false.
- **The `file.upload` audit label now reads 上傳檔案 rather than 投放圖片.** The
  action has covered general file upload since ADR 0026; the label had not caught
  up, and it now sits next to 下載檔案 where the error would have been obvious.
  Use the row's `source` metadata (`image` | `file`) to tell the two apart.

## 6. Not in this release

Ranged or chunked download, downloading a directory or an archive of one,
downloading several files in one request, and any relaxation of the sensitive-file
policy. These are not the remainder of one feature — each needs its own mechanism,
and a ranged read in particular needs an answer to "what if the file changed
between ranges", which is a version precondition. See ADR 0028 §9.

## 7. Operating it

[`docs/runbooks/file-download.md`](runbooks/file-download.md).
