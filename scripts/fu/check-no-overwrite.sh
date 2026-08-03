#!/usr/bin/env bash
# GATE-FU-NO-OVERWRITE (plan/15 FU-07, ADR 0026 §3).
#
# One property, checked everywhere it could be broken: **file upload never
# replaces anything.** A collision is refused; not one existing byte is touched.
#
# This gate defends the round's *size* as much as its safety. Every mechanism the
# withdrawn plan/14 needed — version preconditions, If-Match, 412, a trash can,
# undo, a dirty-buffer state machine — existed only because that design could
# overwrite. The day an `overwrite` field or an `O_TRUNC` slips in, all of it
# becomes necessary again, and nothing else in the test suite would notice.
#
# A grep gate for the same reason GATE-PV-ARGV-CHANNEL and
# GATE-WF-NO-NAMING-CHANNEL are: the property is an *absence*, and an absence is
# not something a unit test notices being removed.
set -euo pipefail
cd "$(dirname "$0")/../.."

fail=0
bad() { printf '[FAIL] %s\n' "$1"; fail=1; }
ok() { printf '[ OK ] %s\n' "$1"; }

# 1. The wire schema: four properties, closed, and nothing that could ask to
#    replace, chmod or retype the target.
python3 - <<'PY' || fail=1
import json
import sys

SCHEMA = "contracts/v1/schemas/messages/filesystem-store.schema.json"
FORBIDDEN = {
    "overwrite", "replace", "force", "if_exists",
    "mode", "chmod", "mime", "precondition", "revision", "etag", "if_match",
}
d = json.load(open(SCHEMA))
props = set(d["properties"])
rc = 0
if props != {"session_id", "directory", "filename", "data"}:
    print(f"[FAIL] filesystem.store properties changed: {sorted(props)}")
    rc = 1
else:
    print("[ OK ] filesystem.store carries exactly {session_id, directory, filename, data}")
if d.get("additionalProperties") is not False:
    print("[FAIL] filesystem.store is not closed (additionalProperties)")
    rc = 1
else:
    print("[ OK ] filesystem.store is closed")
leaked = sorted(FORBIDDEN & props)
if leaked:
    print(f"[FAIL] filesystem.store gained a replace/mode field: {leaked}")
    rc = 1
else:
    print("[ OK ] no replace/mode/mime/precondition field on filesystem.store")
# A filename must not be able to hold a path. The pattern is the enforcement; a
# schema that lost it would still validate every well-formed request, so the gate
# checks for it rather than trusting a comment.
if "/" not in d["properties"]["filename"].get("pattern", ""):
    print("[FAIL] filesystem.store.filename no longer excludes a path separator")
    rc = 1
else:
    print("[ OK ] filesystem.store.filename excludes a path separator")
sys.exit(rc)
PY

# 2. The daemon's write must be O_EXCL under the final name. Two ways to break it:
#    add O_TRUNC, or go back to temp-plus-rename — `renameat` REPLACES its
#    destination and os.Root exposes no RENAME_NOREPLACE, so a rename here would
#    silently clobber a file that appeared after the Lstat.
python3 - <<'PY' || fail=1
import re
import sys

src = open("daemon/internal/files/store.go").read()
rc = 0
if "CreateExclusive(finalRel" not in src:
    print("[FAIL] store.go no longer creates the final name with O_EXCL")
    rc = 1
else:
    print("[ OK ] store.go creates the final name with CreateExclusive (O_EXCL)")
for bad_call in ("O_TRUNC", "RenameIn(", "WriteFile("):
    if bad_call in src:
        print(f"[FAIL] store.go uses {bad_call}, which can replace an existing file")
        rc = 1
if rc == 0:
    print("[ OK ] store.go has no O_TRUNC, no rename-into-place, no WriteFile")
# The mode is fixed, and fixed in one place.
if not re.search(r"storeMode\s+os\.FileMode\s*=\s*0o644", src):
    print("[FAIL] the stored mode is no longer a fixed 0644")
    rc = 1
else:
    print("[ OK ] uploaded files land 0644, fixed")
sys.exit(rc)
PY

# 3. No workspace write outside the confined handle (ADR 0024 W1). Same check the
#    image-drop gate makes, extended to the new file.
if grep -nE '\bos\.(WriteFile|Create|Remove|Rename|OpenFile)\(' \
    daemon/internal/files/store.go daemon/internal/files/upload.go >/dev/null 2>&1; then
  bad "a bare os.* filesystem call appeared on a workspace write path"
else
  ok "every workspace write still goes through workspace.Root"
fi

# 4. Central must not have grown a mutating file route beyond the two that exist.
#    A DELETE or PUT under /files would contradict ADR 0026 §3 rather than extend
#    it, and the scope guard that checks this in pytest only runs with a database.
if grep -nE '@router\.(delete|put|patch)\(' backend/app/api/http/files.py >/dev/null 2>&1; then
  bad "a delete/put/patch route appeared under /files"
else
  ok "no delete/put/patch route under /files"
fi

# 5. The front end must not offer to replace. `useFileUpload` answers a collision
#    with a rename; a "force" or "overwrite" affordance would mean the server
#    grew one too.
if grep -nEi '\b(overwrite|force_?upload|replaceExisting)\b' \
    frontend/src/composables/useFileUpload.ts \
    frontend/src/components/file/FileTree.vue >/dev/null 2>&1; then
  bad "the front end gained an overwrite affordance"
else
  ok "the front end answers a collision with a rename, not a replace"
fi

if [ "$fail" -ne 0 ]; then
  printf '\nGATE-FU-NO-OVERWRITE failed. Read ADR 0026 §3 before relaxing any of this:\n'
  printf '  never overwriting is what lets this path exist without version tokens,\n'
  printf '  a trash can or an undo. Restoring the ability to replace a file means\n'
  printf '  restoring all three (plan/15/01-decisions-and-governance.md §6.2).\n'
  exit 1
fi
printf '\nGATE-FU-NO-OVERWRITE passed.\n'
