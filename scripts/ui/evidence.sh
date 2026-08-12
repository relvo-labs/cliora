#!/usr/bin/env bash
# plan/19 UI remediation evidence. Manual/stack-dependent checks are never reported
# as PASS merely because this machine cannot perform them.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

if ! command -v node >/dev/null 2>&1 && [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
  # shellcheck disable=SC1090
  . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  nvm use "$(cat .nvmrc)" >/dev/null
fi

fail=0
run() {
  local label="$1"
  shift
  if "$@" >/tmp/cliora-ui-evidence.log 2>&1; then
    printf '%s PASS\n' "$label"
  else
    printf '%s FAIL — %s\n' "$label" "$(tail -n 1 /tmp/cliora-ui-evidence.log)"
    fail=1
  fi
}

run "[1/9] 未定義 token .........." node scripts/frontend/check-tokens.mjs
run "[2/9] 守門反向測試 .........." \
  bash -c 'cd frontend && npm run test:unit -- --run src/theme/checkTokens.test.ts'

if [ -f artifacts/ui/local/showcase.png ]; then
  printf '%s\n' "[3/9] 三種進行中 ............ MANUAL — 見 artifacts/ui/local/showcase.png"
else
  printf '%s\n' "[3/9] 三種進行中 ............ MANUAL — 尚待擷取 dev-only showcase"
fi

run "[4/9] D24 ..................." \
  bash -c 'cd frontend && npm run test:unit -- --run src/theme/staticGuards.test.ts src/components/project/TaskBoard.test.ts'

if [ "${E2E_TASKS:-0}" = "1" ]; then
  run "[5/9] 拖曳拒絕 e2e .........." \
    bash -c 'cd frontend && npm run test:e2e -- --project=chromium --workers=1 -g "dependency refusal"'
  run "[5b/9] 等待文案 ............." \
    bash -c 'cd frontend && npm run test:e2e -- --project=chromium --workers=1 -g "queued waiting reasons"'
else
  printf '%s\n' "[5/9] 拖曳拒絕 e2e .......... SKIP — 需 E2E_TASKS=1 的 PostgreSQL stack"
  printf '%s\n' "[5b/9] 等待文案 ............. SKIP — 需 E2E_TASKS=1 的 PostgreSQL stack"
fi

run "[6/9] source 三處一致 ......." \
  bash -c 'cd frontend && npm run test:unit -- --run src/theme/staticGuards.test.ts src/components/project/TaskDetail.test.ts'

uv run --project backend python scripts/tk/measure_board_payload.py \
  --cards 200 --out plan/19/baseline/board-payload-after.json \
  >/tmp/cliora-ui-m1.json
m1_bytes="$(uv run --project backend python -c \
  'import json; print(json.load(open("plan/19/baseline/board-payload-after.json"))["summary"]["bytes"])')"
if [ "$m1_bytes" -le 90000 ]; then
  printf '[7/9] M1 重量 ............... PASS (%s bytes / 90000)\n' "$m1_bytes"
else
  printf '[7/9] M1 重量 ............... FAIL (%s bytes / 90000)\n' "$m1_bytes"
  fail=1
fi

if [ -d artifacts/ui/local/v1-baseline ] && [ -d artifacts/ui/local/v1-after ]; then
  run "[8/9] V1 逐像素 ............." \
    diff -qr artifacts/ui/local/v1-baseline artifacts/ui/local/v1-after
else
  printf '%s\n' "[8/9] V1 逐像素 ............. MANUAL — 尚待瀏覽器 stack 截圖"
fi

run "[9/9] Terminal 寬度 ........." \
  bash -c 'rg -q "grid-template-columns: 1fr 300px" frontend/src/views/SessionWorkspaceView.vue'

if [ -d frontend/dist ]; then
  if rg -q 'TokenShowcaseView|/poc/tokens|token-showcase' frontend/dist; then
    printf '%s\n' "[extra] production bundle ....... FAIL — dev showcase leaked"
    fail=1
  else
    printf '%s\n' "[extra] production bundle ....... PASS"
  fi
else
  printf '%s\n' "[extra] production bundle ....... SKIP — run make build first"
fi

exit "$fail"
