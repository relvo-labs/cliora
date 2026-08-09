#!/usr/bin/env bash
# GATE-TK-CONTRACT-ADDITIVE (plan/17/08 §4): every fixture that existed before this
# phase is byte-for-byte identical; only new ones may appear.
#
# Fixtures rather than the whole of `contracts/`, because adding a message type
# necessarily edits the envelope's type enum — see the header of contract_snapshot.py.
# A fixture is a recorded decision about what the wire accepts and rejects, and an
# edited one silently rewrites a promise made to every daemon already deployed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export PATH="$HOME/.local/bin:$PATH"

BASELINE="${1:-artifacts/tk/local/baseline/contract.sha256}"
[ -f "$BASELINE" ] || { echo "no baseline at $BASELINE (TK-00 captures it)"; exit 2; }

uv run --project backend python scripts/tk/contract_snapshot.py --diff "$BASELINE"
