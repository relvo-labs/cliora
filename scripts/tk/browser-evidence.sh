#!/usr/bin/env bash
# TK-11 browser evidence: the unchanged V2.0 surface with the flag off, then
# Projects plus the V2.1 task/requirement paths with it on.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
: "${CLIORA_DATABASE_URL:=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_e2e}"
export CLIORA_DATABASE_URL
export E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}"

BASELINE="artifacts/pj/local/baseline"
OUT="artifacts/tk/local"
mkdir -p "$OUT/after-off"
[ -f "$BASELINE/nav-baseline.txt" ] || {
  echo "no V2.0 navigation baseline; run scripts/pj/capture-baseline.sh first" >&2
  exit 2
}

with_stack() { # with_stack <label> <script-invocation...>
  local label="$1"; shift
  scripts/e2e/run-stack.sh bash -c "
    set -e
    uv run --project backend python scripts/pj/seed_users.py >/dev/null
    cd frontend
    (npm run dev -- --host 127.0.0.1 >/tmp/tk-vite-$label.log 2>&1 &)
    for i in \$(seq 1 40); do curl -sf http://127.0.0.1:5173 >/dev/null && break; sleep 1; done
    $*
  "
}

STATUS=0
echo "=== flag OFF: full existing browser suite and pixel baseline ==="
export E2E_ADMIN_USER="tk-off-$$"
CLIORA_PROJECTS_ENABLED=false with_stack off \
  "node ../scripts/pj/nav-shot.mjs --out ../$OUT/after-off --label flagoff &&
   env E2E_FULL_STACK=1 E2E_PROJECTS=0 E2E_TASKS=0 npm run test:e2e -- --project=chromium --workers=1" \
  || STATUS=1

if diff <(sed 's/nav-baseline/nav/' "$BASELINE/nav-baseline.txt") \
        <(sed 's/nav-flagoff/nav/' "$OUT/after-off/nav-flagoff.txt") >/dev/null; then
  echo "ok    navigation structure identical to V2.0"
else
  echo "FAIL  navigation structure changed with the flag off"
  STATUS=1
fi
for role in admin developer viewer; do
  if cmp -s "$BASELINE/nav-baseline-$role.png" "$OUT/after-off/nav-flagoff-$role.png"; then
    echo "ok    $role rail is pixel-identical"
  else
    echo "FAIL  $role rail differs"
    STATUS=1
  fi
done

echo "=== flag ON: Projects and V2.1 task/requirement paths ==="
export E2E_ADMIN_USER="tk-on-$$"
CLIORA_PROJECTS_ENABLED=true E2E_SECOND_NODE=1 with_stack on \
  "env E2E_FULL_STACK=1 E2E_PROJECTS=1 E2E_TASKS=1 E2E_SECOND_NODE=1 \
   npm run test:e2e -- --project=chromium --workers=1" \
  || STATUS=1

exit "$STATUS"
