#!/usr/bin/env bash
# Exit condition 16: **an un-upgraded `agentd` 0.12.0 node behaves as it did** (`CE-09`).
#
#   scripts/cv/compat-0120.sh          # run inside a runner-mode stack
#
# SR-1's only Medium finding is that this claim was *argued* and never *executed*
# (`docs/security-review-v2c1.md` §3.1). The argument is strong — `contracts/v1/` is
# byte-identical and the node half has no diff — but it proves "we changed nothing there",
# not "those files behave the same in front of the new Central". What changed is what
# Central *sends* and *derives*, and only a run can answer that.
#
# Three things this script does that a weaker version would skip:
#
#   * builds the old binary from `f91d9c4` in a **worktree** (D71) — there is no tag and
#     no published artifact, and `agentd version` is asserted, not assumed: a
#     compatibility test on the wrong version is worse than none;
#   * keeps the **new** node running alongside (a real upgrade is a mixed fleet) and uses
#     a tag to decide which one gets the work, so "which node claimed it" is determinate
#     rather than a race;
#   * reads the old node's log for decode failures. Contract 1.13.0's changelog says what
#     one looks like — "no reply at all: claimed, offer gone, lease expired, retried to
#     exhaustion, and nothing anywhere mentions compatibility" — so checking the outcome
#     alone would read a decode failure as "the card went blocked".
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
ROOT="$PWD"

: "${E2E_BASE_URL:?run inside scripts/e2e/run-stack.sh (E2E_RUNNER=1)}"
: "${E2E_DAEMON_CONFIG:?run inside a runner-mode stack}"
export PATH="$HOME/.local/bin:/usr/local/go/bin:$PATH"

OLD_COMMIT="${CE_OLD_COMMIT:-f91d9c4}"
WORKTREE="${CE_OLD_WORKTREE:-/tmp/cliora-0120}"
WORK="$(dirname "$E2E_DAEMON_CONFIG")"
OUT="$ROOT/artifacts/cv/local"
mkdir -p "$OUT"

cleanup() {
  [ -n "${OLD_PGID:-}" ] && { kill -- "-$OLD_PGID" 2>/dev/null || kill "$OLD_PGID" 2>/dev/null; }
  git worktree remove --force "$WORKTREE" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> building agentd from $OLD_COMMIT"
rm -rf "$WORKTREE"
git worktree add --detach "$WORKTREE" "$OLD_COMMIT" >/dev/null
( cd "$WORKTREE/daemon" && go build -o "$WORKTREE/agentd-old" ./cmd/agentd )
VERSION="$("$WORKTREE/agentd-old" version 2>&1 | tr -d '\r')"
echo "    $VERSION"
case "$VERSION" in
  *0.12.0*) ;;
  *) echo "!! that binary is not 0.12.0 — refusing to certify the wrong version" >&2; exit 1 ;;
esac

echo "==> enrolling it as a second node, tagged compat-0120"
ACCESS="$(curl -fsS -X POST "$E2E_BASE_URL/api/auth/login" -H 'content-type: application/json' \
  -d "{\"username\":\"${E2E_ADMIN_USER:-e2e-admin}\",\"password\":\"${E2E_ADMIN_PASSWORD:-e2e-admin-pw}\"}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["tokens"]["access_token"])')"
ENROLL="$(curl -fsS -X POST "$E2E_BASE_URL/api/enrollment-tokens" \
  -H "authorization: Bearer $ACCESS" -H 'content-type: application/json' \
  -d '{"ttl_seconds":3600,"max_uses":2}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')"

OLDWS="$WORK/workspace-0120"; OLDRUNS="$WORK/runs-0120"; mkdir -p "$OLDWS" "$OLDRUNS"
# Enrolled with the **new** enroll-dev, because enrolment is not the thing under test and
# 0.12.0's own dev enroller wrote the same file. The runtime binary is the same fakecli:
# what is being certified is the daemon, not the stand-in.
"$WORK/bin/enroll-dev" --server "$E2E_BASE_URL" --token "$ENROLL" --name e2e-node-0120 \
  --workspace-root "$OLDWS" --runtime-binary "$WORK/bin/fakecli" \
  --config "$WORK/config-0120.yaml" --credentials "$WORK/credentials-0120.yaml" --allow-insecure >/dev/null
sed -i "s|known_hosts_path:.*|known_hosts_path: $ROOT/daemon/internal/tunnel/pinggy_known_hosts|" "$WORK/config-0120.yaml"
# Edited with keys **0.12.0 itself declares**, and nothing else: the config is a
# marshalled struct and an unknown field is a parse error, not an ignored line. (The
# first attempt added `state_dir`, which no version of this struct has ever had — the
# second-node block in run-stack.sh `sed`s for it with `|| true`, so its absence had
# never been noticed.)
python3 - "$WORK/config-0120.yaml" "$OLDRUNS" <<'PYEDIT'
import sys, yaml
path, runs = sys.argv[1:3]
cfg = yaml.safe_load(open(path))
cfg.setdefault("runner", {}).update({
    "enabled": True, "work_dir": runs, "max_concurrent": 2, "max_waiting": 4,
    "poll_interval_seconds": 5,
    # The tag is how "which node claimed it" stops being a race between two runners
    # polling the same queue. `run_untagged: false` keeps it from taking the control
    # card meant for the new node.
    "tags": ["compat-0120"], "run_untagged": False,
})
yaml.safe_dump(cfg, open(path, "w"), sort_keys=False, allow_unicode=True)
PYEDIT

setsid env CLIORA_FAKECLI_SCRIPT="${E2E_AGENT_SCRIPT:-}" \
  "$WORKTREE/agentd-old" run --config "$WORK/config-0120.yaml" \
  --credentials "$WORK/credentials-0120.yaml" >"$WORK/agentd-0120.log" 2>&1 &
OLD_PGID=$!

echo "==> waiting for the 0.12.0 node to register as a runner"
OLD_RUNNER=""
for _ in $(seq 1 40); do
  OLD_RUNNER="$(curl -fsS "$E2E_BASE_URL/api/agents" -H "authorization: Bearer $ACCESS" \
    | python3 -c 'import json,sys
rows = json.load(sys.stdin)
print(next((r["id"] for r in rows if r["name"] == "e2e-node-0120"), ""))')"
  [ -n "$OLD_RUNNER" ] && break
  sleep 1
done
if [ -z "$OLD_RUNNER" ]; then
  echo "!! the 0.12.0 node never registered; agentd-0120.log tail:" >&2
  tail -n 25 "$WORK/agentd-0120.log" >&2
  exit 1
fi
curl -fsS -X PATCH "$E2E_BASE_URL/api/agents/$OLD_RUNNER" \
  -H "authorization: Bearer $ACCESS" -H 'content-type: application/json' \
  -d '{"enabled":true}' >/dev/null
echo "    runner $OLD_RUNNER enabled"

echo "==> the lifecycle, on the old node and then on the new one"
CE_OLD_RUNNER_ID="$OLD_RUNNER" \
CE_OLD_LOG="$WORK/agentd-0120.log" \
CE_OLD_VERSION="$VERSION" \
CE_OLD_COMMIT="$OLD_COMMIT" \
  uv run --project backend python "$ROOT/scripts/cv/journeys/compat_0120.py"
