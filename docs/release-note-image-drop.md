# Release note — image drop, and a fix to what counts as text

Two changes ship together (`plan/13`, ADR 0024). One is new, one repairs something that has
been wrong since P3. They are unrelated in code and share only the file subsystem.

---

## 1. New: hand an image to the CLI from the browser

Paste (`Ctrl+V`), drag onto the terminal, or use the **投放圖片** button. The image is stored
on the node inside the session's workspace and its path is typed into the terminal input —
with a trailing space and **no Enter**, so you finish the sentence yourself.

PNG, JPEG, GIF and WebP, up to 4 MiB. Held by Admin and Developer (`file.upload`); **Viewer
cannot upload**. The affordance appears only when your role, your session and the node all
allow it — it is hidden rather than disabled, so a visible button always works.

## 2. The platform now writes into your workspace

This is the part to read before upgrading.

Dropped images land in `<workspace>/.cliora/uploads/<date>/`, named by the daemon. On first
use the daemon also creates `<workspace>/.cliora/.gitignore` containing `*`, so the images
stay out of your commits. It is written once and never overwritten.

**"The workspace is read-only" is no longer true.** That was a product principle, and it has
been withdrawn deliberately — an editable workspace is a stated direction. What replaces it
is four rules every write path must satisfy: confined by the workspace handle, bounded by
quota and retention, audited per write, and refusable by the node. Image drop is the first
path built against them; editing is **not** part of this release.

Files expire after **7 days** and are pruned at session start and every six hours.

### Upgrading acquires this

`filesystem.upload.enabled` defaults to `true`, so an upgraded node accepts image drop
without anyone choosing it. To refuse:

```yaml
filesystem:
  upload:
    enabled: false
```

then restart `agentd`. The node reports the refusal and the console hides the affordance.
See `docs/runbooks/image-drop.md`. The startup log distinguishes "the operator set this"
from "the default did", because those are different facts about a machine.

## 3. Fixed: text files that would not preview

Measured on this repository: **20 of 878** completely valid UTF-8 text files could not be
previewed. Every one had the same cause — the classifier examined only the first 8 KiB, and
when that boundary fell inside a multi-byte character the whole file was reported as binary.
For pure CJK content that happened two times in three. All 20 preview correctly now.

Also fixed: **ANSI-coloured logs are text.** Three colour pairs on a line was enough to
trip the old control-character rule, which meant `npm`, `cargo`, `pytest` and `go test`
output — some of the most useful things to read in a browser — were refused.

**A file that is text but not UTF-8** (Big5, GBK, Shift-JIS, UTF-16) now says so, instead of
claiming to be binary. Those need different actions: convert the encoding, rather than give
up. Automatic transcoding was deliberately not added — guessing an encoding fails by
rendering plausible mojibake, and measurement showed none of the false verdicts came from
encodings in the first place.

### One thing gets stricter

The old 8 KiB window cut both ways: a binary file whose first 8 KiB happened to be printable
ASCII was served as text. Classification now reads the whole file, so **a small number of
files that previewed before will now correctly refuse to.** If a file you used to be able to
open now shows "not text", it contains a NUL byte past the first 8 KiB — that is the fix
working, not a regression.

---

## Compatibility

- Contract **v1.8.0**, compatible. Two new message types and one report-only field; nothing
  existing changed shape. An older daemon simply reports no upload capability and the
  console hides the affordance.
- Migrations **0018** and **0019** (a node column, and the `file.upload` grant for Admin and
  Developer). No backfill: every daemon re-registers on its next connection.
- No change to terminal behaviour, session lifetime, port forwarding, or the sensitive-file
  policy.
