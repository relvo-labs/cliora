#!/usr/bin/env bash
# CV-00: capture the pre-V2-C1 baseline (plan/23/08-…md §3).
#
# Two files, because this phase's gates need exactly two things: the commit the phase
# started from, and a digest of the wire.
#
# **The digest covers `contracts/v1/`, not `contracts/`.** The promise is that no node
# has to be upgraded — which is a promise about schemas and fixtures, the things a
# daemon decodes against. `CHANGELOG.md` is prose for people, and `CV-02` deliberately
# adds an entry to it saying that this release changes nothing on the wire. Hashing the
# whole directory would make writing that sentence break the gate that the sentence is
# about, which is the wrong shape of rule: it would be discharged by deleting the
# explanation (the failure `plan/18/09` §3 item 15 records).
#
#   scripts/cv/capture-baseline.sh [commit]     # default: HEAD
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/cv/local/baseline"
COMMIT="${1:-HEAD}"
mkdir -p "$OUT"

git rev-parse "$COMMIT" > "$OUT/COMMIT"
echo "→ COMMIT $(cat "$OUT/COMMIT")"

# Sorted so the digest is stable across filesystems; paths included so a rename counts
# as a change. `find -type f` rather than `git ls-files`: an untracked file under
# `contracts/v1/` is exactly the kind of thing this should notice.
find contracts/v1 -type f -print0 \
  | LC_ALL=C sort -z \
  | xargs -0 sha256sum \
  | sha256sum \
  | awk '{print $1}' > "$OUT/contract-v1.sha256"
echo "→ contract-v1.sha256 $(cat "$OUT/contract-v1.sha256")"

# The pre-`0040` schema, for `GATE-CV-MIGRATION-ROUNDTRIP`. Needs a migrated database at
# `CLIORA_DATABASE_URL`; skipped with a warning rather than failing, because the other
# two files are useful on their own and this one is the only part that needs a server.
if uv run --project backend python scripts/pj/schema_snapshot.py > "$OUT/schema.txt" 2>/dev/null; then
  echo "→ schema.txt ($(wc -l < "$OUT/schema.txt") lines)"
else
  rm -f "$OUT/schema.txt"
  echo "→ schema.txt SKIPPED (no migrated database at CLIORA_DATABASE_URL)"
fi
