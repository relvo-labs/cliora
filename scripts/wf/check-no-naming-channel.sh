#!/usr/bin/env bash
# GATE-WF-NO-NAMING-CHANNEL (plan/13 WF-10, ADR 0024 §3).
#
# One property, checked everywhere it could be broken: the sender of an image
# cannot name the file it creates. The daemon picks the directory and the name,
# which removes path traversal, double extensions and overwrite together — and
# removes the validation code that would otherwise have to get all three right.
#
# A grep gate for the same reason GATE-PV-ARGV-CHANNEL is one: the property is
# an *absence*, and an absence is not something a unit test notices being
# removed.
set -euo pipefail
cd "$(dirname "$0")/../.."

fail=0
bad() { printf '[FAIL] %s\n' "$1"; fail=1; }
ok() { printf '[ OK ] %s\n' "$1"; }

# 1. The wire schema: two properties, closed.
props=$(python3 -c '
import json
d = json.load(open("contracts/v1/schemas/messages/filesystem-upload.schema.json"))
print(",".join(sorted(d["properties"])), d.get("additionalProperties"))
')
if [ "$props" = "data,session_id False" ]; then
  ok "filesystem.upload carries exactly {session_id, data}, closed"
else
  bad "filesystem.upload properties changed: $props"
fi

# 2. No naming field on the upload path itself. Scoped to the upload functions
#    rather than whole files: `extension` legitimately appears in the
#    sensitive-read audit, and a gate that cries wolf gets disabled.
python3 - <<'PY' || fail=1
import re
import sys

FORBIDDEN = re.compile(r"\b(filename|file_name|directory|target_path|overwrite)\b")
# (path, regex selecting the upload-related region)
REGIONS = [
    ("daemon/internal/connection/files_handlers.go", r"func \(m \*Manager\) handleFsUpload.*?\n}\n"),
    ("daemon/internal/files/upload.go", r"func \(s \*Service\) SaveImage.*?\n}\n"),
    ("backend/app/services/files.py", r"    async def upload_image.*?(?=\n    async def |\n    def )"),
    ("backend/app/api/http/files.py", r"async def upload_image.*?(?=\n@router|\Z)"),
]
problems = []
for path, pattern in REGIONS:
    body = open(path, encoding="utf-8").read()
    match = re.search(pattern, body, re.S)
    if not match:
        problems.append(f"{path}: upload region not found — did it get renamed?")
        continue
    region = match.group(0)
    # Prose may name the thing it forbids — the docstring on the endpoint says
    # "no filename field", which is the point. Only code is checked.
    region = re.sub(r'"""(?:.|\n)*?"""', "", region)
    region = re.sub(r"//[^\n]*", "", region)
    region = re.sub(r"#[^\n]*", "", region)
    for line in region.splitlines():
        if FORBIDDEN.search(line):
            problems.append(f"{path}: naming field on the upload path: {line.strip()}")
for problem in problems:
    print(f"[FAIL] {problem}")
sys.exit(1 if problems else 0)
PY
[ "$fail" -eq 0 ] && ok "no naming field on the upload path in any consumer"

# 3. The daemon builds the name itself; O_EXCL makes a collision an error rather
#    than a silent overwrite.
if grep -q "newULID(now)" daemon/internal/files/upload.go &&
   grep -q "CreateExclusive" daemon/internal/files/upload.go; then
  ok "the daemon generates the name and creates it exclusively"
else
  bad "daemon/internal/files/upload.go no longer names its own files exclusively"
fi

# 4. The extension comes from the sniff, never from a caller.
if grep -q "SniffImage(data)" daemon/internal/files/upload.go; then
  ok "the stored extension comes from the content sniff"
else
  bad "the extension is no longer derived from SniffImage"
fi

# 5. The golden fixtures that pin all of the above.
missing=0
for fixture in with-filename with-path with-mime non-base64 oversize; do
  f="contracts/v1/fixtures/invalid/filesystem-upload-$fixture.json"
  [ -f "$f" ] || { bad "missing golden fixture $f"; missing=1; }
done
[ "$missing" -eq 0 ] && ok "five golden invalid fixtures present"

exit "$fail"
