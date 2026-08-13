#!/usr/bin/env bash
# SC-00: capture the pre-V2.3 baselines (plan/20/01-…md §1).
#
# The same six baselines V2.2 took, from the same capturer, into a different
# directory. Forking the script would have been the obvious move and the wrong one:
# the six are the same six, so two copies would disagree the first time either is
# fixed — and a baseline nobody trusts is worse than no baseline.
#
#   scripts/sc/capture-baseline.sh          # five of six; latency needs the stack
#   scripts/e2e/run-stack.sh scripts/sc/capture-baseline.sh --latency-only
#
# The dirty-tree override is still AR_BASELINE_ALLOW_DIRTY, deliberately: it is the
# capturer's own switch, not this phase's, and renaming it here would leave two names
# for one behaviour.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
BASELINE_OUT="artifacts/sc/local/baseline" exec scripts/ar/capture-baseline.sh "$@"
