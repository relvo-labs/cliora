#!/usr/bin/env bash
# RQ-00: capture the pre-V2.5 baselines (plan/22/01-…md §1).
#
# Fourth phase to reuse the AR capturer rather than fork it, for the reason V2.3
# first wrote down: the six baselines are the same six, and a copy would disagree
# with this one the first time either is fixed.
#
# **One addition this phase makes on its own**: `contract-tree.sha256`. The inherited
# `contract-fixtures.txt` records the fixture *list*, and the gate built on it allows
# additions — which is right for a phase that adds fixtures and wrong for this one,
# whose promise is that `contracts/` does not change by a single byte (plan/22/01 §1.1).
#
#   scripts/rq/capture-baseline.sh          # six of seven; latency needs the stack
#   scripts/e2e/run-stack.sh scripts/rq/capture-baseline.sh --latency-only
#
# The dirty-tree override is still AR_BASELINE_ALLOW_DIRTY: it is the capturer's own
# switch, and a fourth name for one behaviour would be worse than an inherited one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/rq/local/baseline"
BASELINE_OUT="$OUT" scripts/ar/capture-baseline.sh "$@"

# --latency-only re-enters for one file and must not redo the tree hash.
[ "${1:-}" = "--latency-only" ] && exit 0

echo "→ contract-tree.sha256"
# Sorted so the digest is stable across filesystems; paths included so a rename is a
# change. `find -type f` rather than `git ls-files`: an untracked file inside
# contracts/ is exactly the kind of thing this is meant to notice.
find contracts -type f -print0 \
  | LC_ALL=C sort -z \
  | xargs -0 sha256sum \
  | sha256sum \
  | awk '{print $1}' > "$OUT/contract-tree.sha256"
cat "$OUT/contract-tree.sha256"
