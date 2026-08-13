#!/usr/bin/env bash
# The whole V2.2 stack, rootless: Central + a real enrolled runner node + the Vite dev
# server (AR-12 / plan/18/09 §5).
#
# `scripts/e2e/run-stack.sh` already stands up Central and an enrolled node, but it
# does two things this cannot use: it leaves both V2.2 flags off, and the config it
# generates has no `runner` block — so the node registers as a plain node and never
# claims a card. Rather than teach that script a second personality, this one is the
# V2.2 shape end to end and says so.
#
#   scripts/ar/dev-stack.sh          # start and wait; Ctrl-C to stop
#
# The node is deliberately **mixed use**: it keeps a workspace root so interactive
# sessions still work, which is the common setup and the one the Agents page marks with
# ⚠. A dedicated runner is `workspace.allowed_roots: []`.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

DB="${CLIORA_DATABASE_URL:-postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_dev}"
PORT="${CENTRAL_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${CLIORA_ADMIN_PASSWORD:-admin-pw}"
BASE="http://127.0.0.1:${PORT}"

export CLIORA_DATABASE_URL="$DB"
export CLIORA_TEST_DATABASE_URL="$DB"
export CLIORA_ADMIN_PASSWORD="$ADMIN_PASS"
# Both flags, and the inner one only means anything with the outer one on.
export CLIORA_PROJECTS_ENABLED=true
export CLIORA_AGENT_RUNS_ENABLED=true
# Empty allows nothing, by design — so a dev stack has to say what it will fetch.
export CLIORA_GIT_ALLOWED_HOSTS='["github.com"]'
export CLIORA_SECRET_ENCRYPTION_KEY="${CLIORA_SECRET_ENCRYPTION_KEY:-Y2xpb3JhLWRldi1zdGFjay1rZXktMzItYnl0ZXMhISE=}"

WORK="$(mktemp -d)"
BIN="$WORK/bin"
WORKSPACE="$WORK/workspace"
RUNS="$WORK/runs"
mkdir -p "$BIN" "$WORKSPACE/src" "$RUNS"
printf '# dev workspace\n' >"$WORKSPACE/README.md"

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

echo "==> building agentd + fakecli + enroll-dev"
export PATH="$PATH:/usr/local/go/bin"
( cd daemon \
  && go build -o "$BIN/agentd" ./cmd/agentd \
  && go build -o "$BIN/fakecli" ./cmd/fakecli \
  && go build -o "$BIN/enroll-dev" ./cmd/enroll-dev )

echo "==> migrating + seeding admin"
( cd backend && uv run --project . alembic upgrade head \
  && uv run --project . python -m app.bootstrap create-admin --username "$ADMIN_USER" )

echo "==> starting Central on :$PORT (projects + agent runs enabled)"
setsid bash -c "cd '$ROOT/backend' && exec uv run --project . uvicorn app.main:app --host 127.0.0.1 --port '$PORT'" \
  >"$WORK/central.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 40); do curl -fsS "$BASE/readyz" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "$BASE/readyz" >/dev/null

echo "==> enrolling a node"
ACCESS="$(curl -fsS -X POST "$BASE/api/auth/login" -H 'content-type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["tokens"]["access_token"])')"
ENROLL="$(curl -fsS -X POST "$BASE/api/enrollment-tokens" \
  -H "authorization: Bearer $ACCESS" -H 'content-type: application/json' \
  -d '{"ttl_seconds":3600,"max_uses":5}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')"
"$BIN/enroll-dev" --server "$BASE" --token "$ENROLL" --name dev-runner-01 \
  --workspace-root "$WORKSPACE" --runtime-binary "$BIN/fakecli" \
  --config "$WORK/config.yaml" --credentials "$WORK/credentials.yaml" --allow-insecure

# The tunnel block's known_hosts points at /etc, which a rootless stack cannot read.
sed -i "0,/known_hosts_path:/s|known_hosts_path:.*|known_hosts_path: $ROOT/daemon/internal/tunnel/pinggy_known_hosts|" "$WORK/config.yaml"

# The edits `enroll-dev` cannot make. It serialises the **whole** config struct, so a
# `runner:` block already exists with `enabled: false` — appending a second one is a
# duplicate key and the daemon refuses to start. So this rewrites the block in place.
#
# `enabled: false` being what enrollment writes is correct, incidentally: a machine must
# not begin running unattended work because somebody enrolled or upgraded it.
python3 - "$WORK/config.yaml" "$RUNS" "$ROOT" <<'PYCFG'
import sys
import pathlib

config_path, runs, root = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = config_path.read_text().splitlines()
out, skipping = [], False
for line in lines:
    if line.startswith("runner:"):
        skipping = True
        out.extend([
            "runner:",
            "    enabled: true",
            # Outside every allowed root, in both directions — the daemon refuses
            # runner mode otherwise, and names the offending root.
            f"    work_dir: {runs}",
            "    max_concurrent: 1",
            "    max_waiting: 5",
            "    poll_interval_seconds: 5",
            "    git:",
            "        allowed_hosts:",
            "            - github.com",
            # A separate file from the tunnel's in production; the repository's copy is
            # what a rootless dev stack can actually read.
            f"        known_hosts_path: {root}/daemon/internal/tunnel/pinggy_known_hosts",
        ])
        continue
    if skipping:
        if line and not line[0].isspace():
            skipping = False
        else:
            continue
    out.append(line)
config_path.write_text("\n".join(out) + "\n")
PYCFG

echo "==> starting agentd (runner mode)"
setsid "$BIN/agentd" run --config "$WORK/config.yaml" --credentials "$WORK/credentials.yaml" \
  >"$WORK/agentd.log" 2>&1 &
PIDS+=($!)

echo "==> starting the web dev server on :$WEB_PORT"
setsid bash -c "cd '$ROOT/frontend' && exec npm run dev -- --port '$WEB_PORT'" \
  >"$WORK/web.log" 2>&1 &
PIDS+=($!)

echo "==> waiting for the node and the runner to register"
for _ in $(seq 1 40); do
  agents="$(curl -fsS "$BASE/api/agents" -H "authorization: Bearer $ACCESS" 2>/dev/null || echo '[]')"
  [ "$(python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' <<<"$agents")" != "0" ] && break
  sleep 1
done

echo
echo "Central   $BASE      (admin: $ADMIN_USER / $ADMIN_PASS)"
echo "Console   http://127.0.0.1:$WEB_PORT"
echo "logs      $WORK/{central,agentd,web}.log"
echo "run dir   $RUNS"
echo
curl -fsS "$BASE/api/agents" -H "authorization: Bearer $ACCESS" | python3 -m json.tool || true
echo
echo "Ctrl-C to stop."
wait
