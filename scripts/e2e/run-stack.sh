#!/usr/bin/env bash
# Stand up the full P2 stack for end-to-end tests: Central (uvicorn) + a real
# daemon node whose "claude" runtime is the Fake CLI, so a browser can create a
# session and drive a live terminal without a real Claude/Codex install. Runs
# rootless (no systemd) via cmd/enroll-dev. Used by the p2 browser-e2e CI job
# and for local verification.
#
#   scripts/e2e/run-stack.sh [command...]
#
# With a command, the stack is started, the node is awaited online, the command
# is run (e.g. `npm run test:e2e`), and the stack is torn down with the command's
# exit code. With no command it prints connection details and waits (Ctrl-C to
# stop) for interactive local use.
#
# Requires: uv, go, tmux, and a migrated-or-migratable PostgreSQL at
# CLIORA_DATABASE_URL. Honours E2E_ADMIN_USER / E2E_ADMIN_PASSWORD /
# CLIORA_ADMIN_PASSWORD, CENTRAL_PORT (default 8000).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

: "${CLIORA_DATABASE_URL:?set CLIORA_DATABASE_URL to the PostgreSQL URL}"
export CLIORA_DATABASE_URL
export CLIORA_TEST_DATABASE_URL="${CLIORA_TEST_DATABASE_URL:-$CLIORA_DATABASE_URL}"
ADMIN_USER="${E2E_ADMIN_USER:-e2e-admin}"
ADMIN_PASS="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}"
export CLIORA_ADMIN_PASSWORD="${CLIORA_ADMIN_PASSWORD:-$ADMIN_PASS}"
PORT="${CENTRAL_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"

WORK="$(mktemp -d)"
BIN="$WORK/bin"
WORKSPACE="$WORK/workspace"
mkdir -p "$BIN" "$WORKSPACE"

# P3 workspace fixtures: one previewable file per interesting policy branch, so
# the file-tree / preview E2E can assert real daemon behaviour (lazy expand,
# excluded dir, filename search, and each denial screen) instead of mocks.
seed_workspace_fixtures() {
  mkdir -p "$WORKSPACE/src" "$WORKSPACE/deep/nested" "$WORKSPACE/node_modules/pkg"
  printf '# Cliora e2e workspace\n' >"$WORKSPACE/README.md"
  printf "print('E2E_PREVIEW_MARKER')\n" >"$WORKSPACE/src/main.py"
  printf 'export const answer = 42\n' >"$WORKSPACE/src/app.ts"
  printf "print('found me')\n" >"$WORKSPACE/deep/nested/needle_target.py"
  printf 'module.exports = 1\n' >"$WORKSPACE/node_modules/pkg/index.js"
  # Sensitive (denied by name), binary (NUL bytes), oversize (> 2 MiB cap).
  printf 'SECRET_TOKEN=e2e-must-never-be-previewed\n' >"$WORKSPACE/.env"
  printf -- '-----BEGIN PRIVATE KEY-----\ne2e\n' >"$WORKSPACE/server.pem"
  printf 'PNG\000\001\002\000binary\000payload\n' >"$WORKSPACE/logo.png"
  head -c 3145728 /dev/zero | tr '\0' 'x' >"$WORKSPACE/big.log"
}
seed_workspace_fixtures

PIDS=()
# Background servers are launched with setsid so each is its own process-group
# leader; teardown signals the whole group (kill -- -PGID) so uv→uvicorn and
# agentd children are never orphaned, even if the script is killed by a timeout.
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

echo "==> building daemon helpers (agentd, fakecli, enroll-dev)"
export PATH="$PATH:/usr/local/go/bin"
( cd daemon && go build -o "$BIN/agentd" ./cmd/agentd \
  && go build -o "$BIN/fakecli" ./cmd/fakecli \
  && go build -o "$BIN/enroll-dev" ./cmd/enroll-dev )

echo "==> migrating + seeding admin"
( cd backend && uv run --project . alembic upgrade head \
  && uv run --project . python -m app.bootstrap create-admin --username "$ADMIN_USER" )

echo "==> starting Central on :$PORT"
setsid bash -c "cd '$ROOT/backend' && exec uv run --project . uvicorn app.main:app --host 127.0.0.1 --port '$PORT'" \
  >"$WORK/central.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 30); do curl -fsS "$BASE/readyz" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "$BASE/readyz" >/dev/null

echo "==> logging in + minting an enrollment token"
TOKEN_JSON="$(curl -fsS -X POST "$BASE/api/auth/login" \
  -H 'content-type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}")"
ACCESS="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["tokens"]["access_token"])' <<<"$TOKEN_JSON")"
ENROLL_JSON="$(curl -fsS -X POST "$BASE/api/enrollment-tokens" \
  -H "authorization: Bearer $ACCESS" -H 'content-type: application/json' \
  -d '{"ttl_seconds":3600,"max_uses":5}')"
ENROLL_TOKEN="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])' <<<"$ENROLL_JSON")"

echo "==> enrolling a node (runtime claude -> fakecli)"
"$BIN/enroll-dev" --server "$BASE" --token "$ENROLL_TOKEN" --name e2e-node \
  --workspace-root "$WORKSPACE" --runtime-binary "$BIN/fakecli" \
  --config "$WORK/config.yaml" --credentials "$WORK/credentials.yaml" --allow-insecure

echo "==> starting daemon"
setsid "$BIN/agentd" run --config "$WORK/config.yaml" --credentials "$WORK/credentials.yaml" \
  >"$WORK/agentd.log" 2>&1 &
PIDS+=($!)

echo "==> waiting for the node to report online"
online=""
for _ in $(seq 1 30); do
  NODES="$(curl -fsS "$BASE/api/nodes" -H "authorization: Bearer $ACCESS" 2>/dev/null || echo '[]')"
  online="$(python3 -c 'import json,sys
try: nodes=json.load(sys.stdin)
except Exception: nodes=[]
print("1" if any(n.get("status")=="online" for n in nodes) else "")' <<<"$NODES")"
  [ -n "$online" ] && break
  sleep 1
done
if [ -z "$online" ]; then
  echo "!! node did not come online; central.log / agentd.log tail:" >&2
  tail -n 20 "$WORK/central.log" "$WORK/agentd.log" >&2 || true
  exit 1
fi
echo "==> node online; workspace root: $WORKSPACE"

if [ "$#" -gt 0 ]; then
  "$@"
else
  echo "Stack ready at $BASE (admin: $ADMIN_USER / $ADMIN_PASS). Ctrl-C to stop."
  wait
fi
