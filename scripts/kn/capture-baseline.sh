#!/usr/bin/env bash
# KN-00: capture the pre-V2-K1 baseline (plan/25/09-…md §3).
#
# Four files. Three are the same three `scripts/cv/capture-baseline.sh` takes, for the
# same reasons; the fourth is new to this phase.
#
# **The dependency digest is the fourth**, and it is what makes SR-2's "Central added
# no outbound connection" a gate rather than an argument. The evidence for that claim
# is "`pyproject.toml` gained no dependency", and a claim whose evidence nobody
# recorded before the phase started cannot be checked after it.
#
#   scripts/kn/capture-baseline.sh [commit]     # default: HEAD
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/kn/local/baseline"
COMMIT="${1:-HEAD}"
mkdir -p "$OUT"

git rev-parse "$COMMIT" > "$OUT/COMMIT"
echo "→ COMMIT $(cat "$OUT/COMMIT")"

# Scoped to `contracts/v1/`, not `contracts/`: the promise is about what a daemon
# decodes against, and `CHANGELOG.md` is where this phase records that it changed
# nothing. Hashing the prose would make writing that sentence break the gate the
# sentence is about (the failure `plan/18/09` §3 item 15 records).
find contracts/v1 -type f -print0 \
  | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}' \
  > "$OUT/contract-v1.sha256"
echo "→ contract-v1.sha256 $(cat "$OUT/contract-v1.sha256")"

# The dependency set, normalised. Not a hash of the file: `pyproject.toml` gains a
# `[tool.*]` line in a phase that adds no package, and a whole-file digest would call
# that a new egress. The list itself is what SR-2 item 7 is about.
python3 - <<'PY' > "$OUT/backend-deps.txt"
import pathlib, re, sys
text = pathlib.Path("backend/pyproject.toml").read_text(encoding="utf-8")
block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
names = sorted(re.findall(r'"([A-Za-z0-9._-]+)', block.group(1))) if block else []
print("\n".join(names))
PY
echo "→ backend-deps.txt ($(wc -l < "$OUT/backend-deps.txt") packages)"

# The pre-`0041` schema, for `GATE-KN-MIGRATION-ROUNDTRIP`. Needs a migrated database;
# skipped loudly rather than silently, because a gate that passes when it could not run
# is worse than one that says it did not.
if uv run --project backend python scripts/pj/schema_snapshot.py > "$OUT/schema.txt" 2>/dev/null; then
  echo "→ schema.txt ($(wc -l < "$OUT/schema.txt") lines)"
else
  rm -f "$OUT/schema.txt"
  echo "→ schema.txt SKIPPED (no migrated database at CLIORA_DATABASE_URL)"
fi
