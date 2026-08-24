#!/usr/bin/env bash
# PX-00: the four numbers `beta.1` will be compared against (plan/26/00 §2).
#
# Every one of them is a number this phase either promises not to change or promises to
# change by an exact amount, and **none of them is checkable after the fact**:
#
#   BoardCardDTO bytes    D48 says `/board` does not move a byte. `PX-28` compares.
#   tasks indexes         `0043` adds four. Asserting "four were added" needs the before.
#   token count           62 → 72 exactly (`00` §4). A 73rd is a token nobody decided on.
#   requirements count    189 → 201 exactly (`FR-WORK-001`…`-012`).
#
# `plan/26` was written against a repository read on 2026-08-23, and `README.md`'s
# planning-baseline table quotes these values in prose. This writes them as data so that
# the comparison is a diff rather than somebody re-reading a table.
#
#   scripts/px/capture-baseline.sh [commit]     # default: HEAD
#
# The DTO measurement needs a migrated database with the fixed dataset in it
# (`scripts/cv/seed-dataset.py`, seed 20260819) at CLIORA_DATABASE_URL. Without one it
# is skipped with a warning rather than failing: the other three are static and useful
# on their own, and a baseline script that refuses to run without a database is one that
# does not get run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/px/local/baseline"
COMMIT="${1:-HEAD}"
mkdir -p "$OUT"

git rev-parse "$COMMIT" > "$OUT/COMMIT"
echo "→ COMMIT $(cat "$OUT/COMMIT")"

# **Everything file-derived below is read out of that commit, not out of the working
# tree.** A baseline script is usually run before the phase starts; this one has to give
# the same answer when it is run afterwards, or the numbers it records are the numbers it
# was supposed to be comparing against. `git show` is what makes the difference.
at() { git show "$(cat "$OUT/COMMIT"):$1"; }

# `daemon/` and `contracts/` are frozen this phase (GATE-PX-NO-DAEMON-DIFF,
# GATE-PX-CONTRACT-FROZEN). Both gates compare against these two lines.
at daemon/VERSION > "$OUT/agentd-version"
find contracts -type f -print0 \
  | LC_ALL=C sort -z \
  | xargs -0 sha256sum \
  | sha256sum \
  | awk '{print $1}' > "$OUT/contracts.sha256"
echo "→ agentd $(cat "$OUT/agentd-version"), contracts $(cut -c1-12 < "$OUT/contracts.sha256")"

# The dependency **lists**, not the files: a `[tool.*]` edit or a script rename must not
# read as a new package. `GATE-PX-TOUCH-LIST` compares against these.
# The content arrives as an argument rather than on stdin: `python -` reads its
# *program* from stdin, so a heredoc and a pipe cannot both be used.
uv run --project backend python - "$(at backend/pyproject.toml)" > "$OUT/backend-deps.txt" <<'PY'
import re
import sys

text = sys.argv[1]
block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
names = sorted(re.findall(r'"([A-Za-z0-9._-]+)', block.group(1))) if block else []
print("\n".join(names))
PY
node -e 'console.log(Object.keys(JSON.parse(process.argv[1]).dependencies||{}).sort().join("\n"))' \
  "$(at frontend/package.json)" > "$OUT/frontend-deps.txt"
echo "→ dependencies: $(wc -l < "$OUT/backend-deps.txt") backend, $(wc -l < "$OUT/frontend-deps.txt") frontend"

# Custom properties in the token file. `grep -c` on the declaration form rather than a
# CSS parse: the file is one flat `:root` block and has been since P4-07.
at frontend/src/theme/tokens.css | grep -cE '^\s+--[a-z0-9-]+\s*:' > "$OUT/token-count"
echo "→ tokens $(cat "$OUT/token-count")"

# Through a file, not an argument: `requirements.json` is a couple of hundred kilobytes
# and `execve` has a limit.
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

# Every index on `tasks`, from the model rather than from a live database: this has to
# work without one, and `0043`'s job is to make the model and the database agree.
# Every index on `tasks`. **The one thing here that is current state rather than the
# baseline commit's**, because it comes from a live database and a database has one
# schema at a time. Labelled as such in the file so nobody reads it as a "before".
#
# **From the database, not from the migrations**: they write
# their indexes as raw `CREATE INDEX` strings spread over several source lines, and the
# obvious regex finds two of the three and reports the miss as success. `0043` adds four
# and `PX-22`'s roundtrip test compares against this file.
uv run --project backend python - <<'PY' > "$OUT/tasks-indexes.txt"
import asyncio
import os
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> int:
    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("no CLIORA_DATABASE_URL - index list unavailable", file=sys.stderr)
        return 1
    engine = create_async_engine(url)
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
    return 0


raise SystemExit(asyncio.run(main()))
PY
echo "→ tasks indexes: $(tr '\n' ' ' < "$OUT/tasks-indexes.txt")"

# **Two board numbers, and they are not the same measurement.** `plan/19`'s 89,251 —
# the one quoted in `repositories/tasks.py`'s docstring and in plan/26's baseline table
# — comes from `scripts/tk/measure_board_payload.py`, a *synthetic* generator with its
# own seed, its own titles and a hand-written summary dict that predates `BoardCardDTO`.
# The real DTO on the real fixed dataset is a different, smaller number. Both are
# captured because both are pins: the synthetic one guards the shape decision `plan/17`
# made, and the real one is what `PX-28` can honestly compare `beta.1` against.
uv run --project backend python scripts/tk/measure_board_payload.py \
  --cards 200 --out "$OUT/board-payload-synthetic.json" >/dev/null
echo "→ synthetic summary $(python3 -c "import json;print(json.load(open('$OUT/board-payload-synthetic.json'))['summary']['bytes'])") bytes (plan/19's 89,251)"

if [ -n "${CLIORA_DATABASE_URL:-}" ] \
  && uv run --project backend python scripts/px/measure-dto.py --out "$OUT/board-card-bytes.json" >/dev/null 2>&1; then
  echo "→ BoardCardDTO $(python3 -c "import json;print(json.load(open('$OUT/board-card-bytes.json'))['bytes'])") bytes (real DTO, seed 20260819)"
else
  rm -f "$OUT/board-card-bytes.json"
  echo "→ BoardCardDTO SKIPPED (needs the seeded dataset at CLIORA_DATABASE_URL)"
fi

echo "baseline written to $OUT"
