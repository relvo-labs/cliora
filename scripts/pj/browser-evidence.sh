#!/usr/bin/env bash
# The two checks that need a real browser and a live stack (plan/16 PJ-07).
#
# Split out of evidence.sh because they cost a full stack bring-up twice — once
# with the project layer off and once with it on. The flag-off pass is the one that
# matters most: it compares the navigation rail against the pre-change baseline
# captured by PJ-00, which is the executable form of "with the flag off, nothing
# changed".
#
#   CLIORA_DATABASE_URL=postgresql+asyncpg://... scripts/pj/browser-evidence.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
: "${CLIORA_DATABASE_URL:=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_e2e}"
export CLIORA_DATABASE_URL
# A fresh Admin makes the evidence rerunnable against a persistent throwaway DB:
# live sessions intentionally survive a stack teardown and otherwise accumulate
# against the per-user cap across evidence runs.
E2E_ADMIN_PASSWORD="e2e-admin-pw"
export E2E_ADMIN_PASSWORD

BASELINE="artifacts/pj/local/baseline"
[ -f "$BASELINE/nav-baseline.txt" ] || { echo "no nav baseline; PJ-00 captures it"; exit 2; }

with_stack() {  # with_stack <label> <script-invocation...>
  local label="$1"; shift
  scripts/e2e/run-stack.sh bash -c "
    set -e
    uv run --project backend python scripts/pj/seed_users.py >/dev/null
    cd frontend
    (npm run dev -- --host 127.0.0.1 >/tmp/pj-vite-$label.log 2>&1 &)
    for i in \$(seq 1 40); do curl -sf http://127.0.0.1:5173 >/dev/null && break; sleep 1; done
    $*
  "
}

echo "=== flag OFF: the rail must match the pre-change baseline ==="
E2E_ADMIN_USER="pj-off-$$"
export E2E_ADMIN_USER
CLIORA_PROJECTS_ENABLED=false with_stack off \
  "node ../scripts/pj/nav-shot.mjs --out ../artifacts/pj/local/after-off --label flagoff &&
   env E2E_FULL_STACK=1 npm run test:e2e -- --project=chromium --workers=1" || exit 1

STATUS=0
if diff <(sed 's/nav-baseline/nav/' "$BASELINE/nav-baseline.txt") \
        <(sed 's/nav-flagoff/nav/' artifacts/pj/local/after-off/nav-flagoff.txt) >/dev/null; then
  echo "ok    navigation structure identical to the baseline"
else
  echo "FAIL  navigation structure changed with the flag off"; STATUS=1
fi
for role in admin developer viewer; do
  if cmp -s "$BASELINE/nav-baseline-$role.png" "artifacts/pj/local/after-off/nav-flagoff-$role.png"; then
    echo "ok    $role rail is pixel-identical"
  else
    echo "FAIL  $role rail differs"; STATUS=1
  fi
done

echo
echo "=== flag ON: the project screens ==="
E2E_ADMIN_USER="pj-on-$$"
export E2E_ADMIN_USER
CLIORA_PROJECTS_ENABLED=true E2E_SECOND_NODE=1 with_stack on \
  "node ../scripts/pj/smoke-projects.mjs &&
   node ../scripts/pj/measure-nav-height.mjs &&
   env E2E_FULL_STACK=1 E2E_PROJECTS=1 E2E_SECOND_NODE=1 npm run test:e2e -- --project=chromium --workers=1" || STATUS=1

exit "$STATUS"
