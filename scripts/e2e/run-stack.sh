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
# Port forwarding (plan/11) is included the same way the terminal path is: with a
# stand-in. `faketunnelapp` is the application being forwarded and
# `faketunnelprovider` stands in for the provider's ssh client, so the browser suite
# exercises Central, the protocol, the supervisor and both pages **without reaching
# the real provider** — no account, no outbound network, and no CI that goes red
# when somebody else has an outage. The URL the fake announces is on
# `.example.invalid` (RFC 2606: never resolves), so the suite can assert that a URL
# is shown and can never accidentally open it.
#
# Requires: uv, go, tmux, and a migrated-or-migratable PostgreSQL at
# CLIORA_DATABASE_URL. Honours E2E_ADMIN_USER / E2E_ADMIN_PASSWORD /
# CLIORA_ADMIN_PASSWORD, CENTRAL_PORT (default 8000), E2E_TUNNEL_APP_PORT
# (default 5199), and E2E_SECOND_NODE=1 to enroll a second node with its own
# workspace root (off by default — see the block that reads it).
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
TUNNEL_APP_PORT="${E2E_TUNNEL_APP_PORT:-5199}"
# Without this Central refuses to enable the port-forwarding integration at all
# (SECRET_KEY_MISSING) rather than storing a credential in plain text, so the stack
# has to supply one. A fixed value: it is a throwaway database and a fake provider,
# and a random key would make a failure impossible to reproduce.
export CLIORA_SECRET_ENCRYPTION_KEY="${CLIORA_SECRET_ENCRYPTION_KEY:-Y2xpb3JhLWUyZS1zdGFjay1rZXktMzItYnl0ZXMhISE=}"

WORK="$(mktemp -d)"
BIN="$WORK/bin"
WORKSPACE="$WORK/workspace"
export E2E_WORKSPACE_ROOT="$WORKSPACE"
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

echo "==> building daemon helpers (agentd, fakecli, faketunnelapp, faketunnelprovider, enroll-dev)"
export PATH="$PATH:/usr/local/go/bin"
( cd daemon && go build -o "$BIN/agentd" ./cmd/agentd \
  && go build -o "$BIN/fakecli" ./cmd/fakecli \
  && go build -o "$BIN/faketunnelapp" ./cmd/faketunnelapp \
  && go build -o "$BIN/faketunnelprovider" ./cmd/faketunnelprovider \
  && go build -o "$BIN/enroll-dev" ./cmd/enroll-dev )

echo "==> starting the app to forward on :$TUNNEL_APP_PORT"
setsid "$BIN/faketunnelapp" --addr "127.0.0.1:$TUNNEL_APP_PORT" >"$WORK/faketunnelapp.log" 2>&1 &
PIDS+=($!)

echo "==> migrating + seeding admin"
( cd backend && uv run --project . alembic upgrade head \
  && uv run --project . python -m app.bootstrap create-admin --username "$ADMIN_USER" )

# Runner mode is opt-in for the same reason the second node is: it changes what the
# stack *does* rather than only what it has. With it on, a daemon on this machine polls
# for agent work and launches child processes — which the P2/P3 suites neither need nor
# expect. `CV-12`'s measurement (`scripts/cv/measure-answer-to-turn.py`) turns it on.
if [ "${E2E_RUNNER:-}" = "1" ]; then
  # Both flags, in this order of dependence: the agent layer is mounted *inside* the
  # project layer, so with only the second one on every `/api/agents` route answers
  # 404 — correctly, and indistinguishably from a typo in the path.
  export CLIORA_PROJECTS_ENABLED=true
  export CLIORA_AGENT_RUNS_ENABLED=true
  # A *second* key, and Central's refusal to start without it is deliberate: a run's
  # secrets are sealed with this one and it is kept apart from the database backup,
  # precisely so a restored backup cannot decrypt them. Same throwaway-value reasoning
  # as the encryption key above.
  export CLIORA_SECRET_MASTER_KEY="${CLIORA_SECRET_MASTER_KEY:-Y2xpb3JhLWUyZS1zdGFjay1tYXN0ZXIta2V5LTMyISE=}"
fi

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

# The generated config points at /etc/agentd/pinggy_known_hosts, which a rootless stack
# cannot write. Point it at the repository's copy instead. The daemon would fall back to the
# keys embedded in the binary anyway; naming the file keeps this stack exercising the
# node's-own-file branch, which is the one an operator uses to rotate a key.
sed -i "s|known_hosts_path:.*|known_hosts_path: $ROOT/daemon/internal/tunnel/pinggy_known_hosts|" "$WORK/config.yaml"

# The run root is a **sibling** of the workspace root, never inside it:
# `runner.CheckIsolation` refuses to start otherwise, and that refusal is the point —
# a run's checkout must not be reachable through the file-tree API.
if [ "${E2E_RUNNER:-}" = "1" ]; then
  RUNS="$WORK/runs"
  mkdir -p "$RUNS"
  # Edited into the block enroll-dev already wrote, not appended after it: the file is
  # a marshalled struct, so every key is present and a second `runner:` is a parse
  # error rather than an override.
  python3 - "$WORK/config.yaml" "$RUNS" <<'PYEDIT'
import sys, yaml
path, runs = sys.argv[1], sys.argv[2]
cfg = yaml.safe_load(open(path))
cfg.setdefault("runner", {}).update({
    "enabled": True,
    "work_dir": runs,
    "max_concurrent": 2,
    "max_waiting": 4,
    "poll_interval_seconds": 5,
})
yaml.safe_dump(cfg, open(path, "w"), sort_keys=False, allow_unicode=True)
PYEDIT
  export E2E_RUNNER_WORK_DIR="$RUNS"
fi

echo "==> starting daemon (port forwarding via the stand-in provider)"
setsid env CLIORA_TUNNEL_PROVIDER_COMMAND_FOR_TESTS="$BIN/faketunnelprovider" \
  "$BIN/agentd" run --config "$WORK/config.yaml" --credentials "$WORK/credentials.yaml" \
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

# A second node, opt-in (plan/16 06-…md §2.5). The V2.0 project layer's whole point
# is that a project spans machines, and one node cannot demonstrate that.
#
# **Opt-in rather than always-on**, deliberately: the existing P2/P3 specs pick
# `nodes[0]` or "the first node that is online", and with two nodes racing to
# connect, which one that is stops being determinate. Leaving it off by default
# makes the question "does a second node destabilise the older suites" not arise,
# instead of answering it by reading every one of them.
#
# Its workspace root is a *different* directory on purpose. Two mounts of one
# directory would let a cross-node assertion pass on a path that happens to exist
# in both places, which is not the property being tested.
if [ "${E2E_SECOND_NODE:-}" = "1" ]; then
  WORKSPACE2="$WORK/workspace-b"
  mkdir -p "$WORKSPACE2/src"
  printf '# second node workspace\n' >"$WORKSPACE2/README.md"
  printf "print('E2E_SECOND_NODE_MARKER')\n" >"$WORKSPACE2/src/main.py"

  echo "==> enrolling a second node (e2e-node-2)"
  "$BIN/enroll-dev" --server "$BASE" --token "$ENROLL_TOKEN" --name e2e-node-2 \
    --workspace-root "$WORKSPACE2" --runtime-binary "$BIN/fakecli" \
    --config "$WORK/config2.yaml" --credentials "$WORK/credentials2.yaml" --allow-insecure
  sed -i "s|known_hosts_path:.*|known_hosts_path: $ROOT/daemon/internal/tunnel/pinggy_known_hosts|" "$WORK/config2.yaml"
  # A distinct state directory: two daemons sharing one would fight over the same
  # tmux socket and credential file.
  sed -i "s|state_dir:.*|state_dir: $WORK/state2|" "$WORK/config2.yaml" || true

  setsid env CLIORA_TUNNEL_PROVIDER_COMMAND_FOR_TESTS="$BIN/faketunnelprovider" \
    "$BIN/agentd" run --config "$WORK/config2.yaml" --credentials "$WORK/credentials2.yaml" \
    >"$WORK/agentd2.log" 2>&1 &
  PIDS+=($!)

  second=""
  for _ in $(seq 1 30); do
    NODES="$(curl -fsS "$BASE/api/nodes" -H "authorization: Bearer $ACCESS" 2>/dev/null || echo '[]')"
    second="$(python3 -c 'import json,sys
try: nodes=json.load(sys.stdin)
except Exception: nodes=[]
print("1" if sum(1 for n in nodes if n.get("status")=="online") >= 2 else "")' <<<"$NODES")"
    [ -n "$second" ] && break
    sleep 1
  done
  if [ -z "$second" ]; then
    echo "!! the second node did not come online; agentd2.log tail:" >&2
    tail -n 20 "$WORK/agentd2.log" >&2 || true
    exit 1
  fi
  echo "==> second node online; workspace root: $WORKSPACE2"
  export E2E_SECOND_NODE_WORKSPACE="$WORKSPACE2"
fi

# `enabled` is an administrator's switch on Central and deliberately not something
# `runner.register` can set (ADR 0029 amendment B5), so the stack has to throw it.
if [ "${E2E_RUNNER:-}" = "1" ]; then
  echo "==> enabling the runner"
  runner_id=""
  for _ in $(seq 1 30); do
    AGENTS="$(curl -fsS "$BASE/api/agents" -H "authorization: Bearer $ACCESS" 2>/dev/null || echo '[]')"
    runner_id="$(python3 -c 'import json,sys
try: rows=json.load(sys.stdin)
except Exception: rows=[]
print(rows[0]["id"] if rows else "")' <<<"$AGENTS")"
    [ -n "$runner_id" ] && break
    sleep 1
  done
  if [ -z "$runner_id" ]; then
    echo "!! the daemon never registered as a runner; agentd.log tail:" >&2
    tail -n 20 "$WORK/agentd.log" >&2 || true
    exit 1
  fi
  curl -fsS -X PATCH "$BASE/api/agents/$runner_id" \
    -H "authorization: Bearer $ACCESS" -H 'content-type: application/json' \
    -d '{"enabled":true}' >/dev/null
  export E2E_RUNNER_ID="$runner_id"
  echo "==> runner $runner_id enabled"
fi

export E2E_ADMIN_USER="$ADMIN_USER"
export E2E_ADMIN_PASSWORD="$ADMIN_PASS"
export E2E_BASE_URL="$BASE"
export E2E_TUNNEL_APP_PORT="$TUNNEL_APP_PORT"

if [ "$#" -gt 0 ]; then
  "$@"
else
  echo "Stack ready at $BASE (admin: $ADMIN_USER / $ADMIN_PASS)."
  echo "App to forward: http://127.0.0.1:$TUNNEL_APP_PORT (port $TUNNEL_APP_PORT). Ctrl-C to stop."
  wait
fi
