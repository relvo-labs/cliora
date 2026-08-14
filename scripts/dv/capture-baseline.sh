#!/usr/bin/env bash
# DV-00: capture the pre-V2.4 baselines (plan/21/01-…md §1).
#
# Third phase to reuse the AR capturer rather than fork it. The reason has not
# changed since V2.3 wrote it down: the six baselines are the same six, so a copy
# would disagree with this one the first time either is fixed — and a baseline
# nobody trusts is worse than no baseline.
#
#   scripts/dv/capture-baseline.sh          # five of six; latency needs the stack
#   scripts/e2e/run-stack.sh scripts/dv/capture-baseline.sh --latency-only
#
# The dirty-tree override is still AR_BASELINE_ALLOW_DIRTY: it is the capturer's own
# switch, and a third name for one behaviour would be worse than an inherited one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
BASELINE_OUT="artifacts/dv/local/baseline" exec scripts/ar/capture-baseline.sh "$@"
