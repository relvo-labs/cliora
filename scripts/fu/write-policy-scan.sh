#!/usr/bin/env bash
# plan/15 FU-07. Which paths in a tree can a browser upload into, and which are
# refused and why (ADR 0026 §4)?
#
# A thin wrapper around daemon/internal/files/storescan, which drives the real
# policy function — a second implementation of a security rule in shell is exactly
# what ADR 0026 §4 avoids.
#
# Usage: scripts/fu/write-policy-scan.sh [dir] [-summary]
set -euo pipefail
cd "$(dirname "$0")/../.."
target="$(cd "${1:-.}" && pwd)"
shift || true
cd daemon
exec go run ./internal/files/storescan "$@" "$target"
