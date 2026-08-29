#!/usr/bin/env bash
# HD-00: the numbers `beta.2` will be compared against (plan/27/00 §2).
#
# Modelled on `scripts/px/capture-baseline.sh` and different from it in exactly one way,
# which is the reason this file exists rather than a flag on that one:
#
#   plan/26 promised **not** to change its dependency lists.
#   plan/27 promises to change the frontend list **by exactly one** (D125,
#   `@axe-core/playwright`). So the gate reads "differs by exactly this one name",
#   and that sentence needs the before-list as data rather than as a claim.
#
# Five things are captured that plan/26's script did not need:
#
#   route list        `/board` is deleted this phase (D126). GATE-HD-OPENAPI-DIFF asserts
#                     the diff is that one path and nothing else.
#   httpx importers   D119 takes this from one module to exactly two.
#   ADR statuses      nine went `proposed` → `accepted` on 2026-08-27; a tenth appearing
#                     later should be visible.
#   stage writers     the three `stage='blocked'` sites HD-06 rewrites.
#   migration head    0043 → 0046 by the end, and 0046 is the irreversible one.
#
#   scripts/hd/capture-baseline.sh [commit]     # default: HEAD
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/hd/local/baseline"
COMMIT="${1:-HEAD}"
mkdir -p "$OUT"

git rev-parse "$COMMIT" > "$OUT/COMMIT"
echo "→ COMMIT $(cat "$OUT/COMMIT")"

# Read out of the commit, not the working tree: this script has to give the same answer
# when it is re-run after the phase, or the numbers it records are the numbers it was
# supposed to be comparing against.
at() { git show "$(cat "$OUT/COMMIT"):$1"; }

at daemon/VERSION > "$OUT/agentd-version"
find contracts -type f -print0 \
  | LC_ALL=C sort -z \
  | xargs -0 sha256sum \
  | sha256sum \
  | awk '{print $1}' > "$OUT/contracts.sha256"
echo "→ agentd $(cat "$OUT/agentd-version"), contracts $(cut -c1-12 < "$OUT/contracts.sha256")"

uv run --project backend python - "$(at backend/pyproject.toml)" > "$OUT/backend-deps.txt" <<'PY'
import re
import sys

text = sys.argv[1]
block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
names = sorted(re.findall(r'"([A-Za-z0-9._-]+)', block.group(1))) if block else []
print("\n".join(names))
PY
# **Both lists, and dev separately.** D125's one new package is a devDependency, so a
# gate that only watched `dependencies` would not see it and a gate that watched their
# union could not say which half moved.
node -e 'const p=JSON.parse(process.argv[1]);console.log(Object.keys(p.dependencies||{}).sort().join("\n"))' \
  "$(at frontend/package.json)" > "$OUT/frontend-deps.txt"
node -e 'const p=JSON.parse(process.argv[1]);console.log(Object.keys(p.devDependencies||{}).sort().join("\n"))' \
  "$(at frontend/package.json)" > "$OUT/frontend-dev-deps.txt"
echo "→ dependencies: $(wc -l < "$OUT/backend-deps.txt") backend, $(wc -l < "$OUT/frontend-deps.txt") frontend, $(wc -l < "$OUT/frontend-dev-deps.txt") frontend-dev"

at frontend/src/theme/tokens.css | grep -cE '^\s+--[a-z0-9-]+\s*:' > "$OUT/token-count"
echo "→ tokens $(cat "$OUT/token-count")"

at traceability/requirements.json > "$OUT/requirements-at-baseline.json"
python3 - "$OUT/requirements-at-baseline.json" > "$OUT/requirements.json" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
items = data["requirements"] if isinstance(data, dict) else data
families = sorted({item["id"].rsplit("-", 1)[0] for item in items})
print(json.dumps({"count": len(items), "families": len(families), "ids": families}, indent=2))
PY
echo "→ requirements $(python3 -c "import json;d=json.load(open('$OUT/requirements.json'));print(d['count'],'in',d['families'],'families')")"

# The migration head, by filename. `alembic heads` needs a database and this must run
# without one; the revision id is in the file and the file name carries it too.
git show "$(cat "$OUT/COMMIT")":backend/app/db/migrations/versions --name-only 2>/dev/null \
  | grep -E '^[0-9]{4}_' | sort | tail -1 > "$OUT/migration-head"
echo "→ migration head $(cat "$OUT/migration-head")"

# **Every module that can reach the network.** D119 takes this from one to exactly two,
# and `GATE-HD-EGRESS-ALLOWLIST` compares against this file rather than hard-coding the
# names — a gate holding its own copy of the answer is a gate that agrees with itself.
git grep -l -E '^(import|from) httpx' "$(cat "$OUT/COMMIT")" -- 'backend/app/**/*.py' \
  | sed 's|^[^:]*:||' | LC_ALL=C sort > "$OUT/httpx-importers.txt"
echo "→ httpx importers: $(tr '\n' ' ' < "$OUT/httpx-importers.txt")"

# The three `task.stage = 'blocked'` writers HD-06 rewrites. Captured as a count *and* as
# locations: "three became zero" is the assertion, and the locations are what makes a
# failure readable.
git grep -n -E '\.stage\s*=\s*["'"'"']blocked["'"'"']' "$(cat "$OUT/COMMIT")" -- 'backend/app/**/*.py' \
  | sed 's|^[^:]*:||' > "$OUT/legacy-blocked-writers.txt" || true
echo "→ stage='blocked' writers: $(wc -l < "$OUT/legacy-blocked-writers.txt")"

# ADR status lines. Nine moved proposed → accepted on 2026-08-27; this records that as
# the starting point so a tenth reverting is visible.
#
# **Every status line, not the first one.** ADR 0029 and 0031 carry V2.3 amendments with
# their own status, and both of those were `proposed` while the document's opening line
# said `accepted`. A `grep -m1` reports those two files as settled and the two amendments
# — which is what the 2026-08-27 sign-off actually had to close — disappear.
#
# `|| true` on the inner pipeline is load-bearing under `set -e` with `pipefail`: most
# ADRs carry no `Status:` line at all, `grep` exits 1 on those, and the script would stop
# here having written the six files above and none of the four below — silently, because
# a caller piping this into `tail` never sees the status.
: > "$OUT/adr-status.txt"
for f in $(git ls-tree --name-only "$(cat "$OUT/COMMIT")" docs/adr/); do
  while read -r status; do
    printf '%s\t%s\n' "$(basename "$f")" "$status" >> "$OUT/adr-status.txt"
  done < <(at "$f" | grep -oE 'Status: \*\*[a-z]+\*\*' || true)
done
echo "→ ADR status lines: $(grep -c 'accepted' "$OUT/adr-status.txt" || true) accepted, $(grep -c 'proposed' "$OUT/adr-status.txt" || true) proposed"

# The OpenAPI path list. `/board` is deleted this phase and nothing else may be.
if uv run --project backend python - > "$OUT/openapi-paths.txt" 2>/dev/null <<'PY'
from app.main import app

for path in sorted(app.openapi()["paths"]):
    print(path)
PY
then
  echo "→ OpenAPI paths $(wc -l < "$OUT/openapi-paths.txt")"
else
  rm -f "$OUT/openapi-paths.txt"
  echo "→ OpenAPI paths SKIPPED (app import failed)"
fi

# Tasks indexes: current database state, not the baseline commit's, and labelled as such.
if [ -n "${CLIORA_DATABASE_URL:-}" ]; then
  uv run --project backend python - <<'PY' > "$OUT/tasks-indexes.txt" || true
import asyncio
import os

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["CLIORA_DATABASE_URL"])
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'tasks' ORDER BY indexname"
                )
            )
        ).all()
    await engine.dispose()
    for row in rows:
        print(row[0])


asyncio.run(main())
PY
  echo "→ tasks indexes: $(tr '\n' ' ' < "$OUT/tasks-indexes.txt")"
else
  echo "→ tasks indexes SKIPPED (no CLIORA_DATABASE_URL)"
fi

echo "baseline written to $OUT"
