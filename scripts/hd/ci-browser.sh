#!/usr/bin/env bash
# Automatic HD-04/HD-05 evidence inside an already-running Central/daemon stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

SEED_OUT="artifacts/px/local/w0/attention-demo.json"
uv run --project backend python scripts/px/seed-attention-demo.py --out "$SEED_OUT"
export E2E_HD_PROJECT
E2E_HD_PROJECT="$(sed -n 's/^[[:space:]]*"project_id": "\([0-9a-f-]*\)",*$/\1/p' "$SEED_OUT")"
if [[ ! "$E2E_HD_PROJECT" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "could not read project_id from $SEED_OUT" >&2
  exit 2
fi
export E2E_FRONTEND_PORT="${E2E_FRONTEND_PORT:-5173}"
export E2E_BASE_URL="http://127.0.0.1:${E2E_FRONTEND_PORT}"
export CLIORA_DEV_PROXY_TARGET="http://127.0.0.1:${CENTRAL_PORT:-8000}"

cd frontend
if (( $# )); then
  npx playwright test --config tests/hd/playwright.config.ts "$@" --workers=1
else
  npx playwright test --config tests/hd/playwright.config.ts a11y visual --workers=1
fi
