#!/usr/bin/env bash
# Pre-deploy check of the topology the Railway client-IP trust keywords rely on (#184).
#
# Read-only. Run it before promoting a deployment and again after any change to the
# environment's services, domains or TCP proxies. It fails (non-zero) unless the
# environment holds only Postgres, Central and console; neither console nor Central has a
# TCP proxy; Central has no public domain; and the two keyword variables are set.
#
#   scripts/railway/check-trust-topology.sh --environment production --console-service cliora
#   scripts/railway/check-trust-topology.sh ... --central-vars c.json --console-vars k.json  # staged
#   scripts/railway/check-trust-topology.sh ... --record evidence/topology.json
#
# Production's console service is named `cliora`: set CLIORA_RAILWAY_CONSOLE_SERVICE=cliora
# or pass --console-service cliora (default: console).
# Needs a logged-in `railway` CLI linked to the project (or --project-id plus
# RAILWAY_API_TOKEN). An expired OAuth login is refreshed by any railway command
# (e.g. `railway whoami`). Exit 1: a precondition does not hold. Exit 2: the facts could
# not be established (not logged in, expired token, API error, unrecognised response) —
# fail closed, never a pass. Neither tokens nor variable values are ever printed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
args=(
  --central-service "${CLIORA_RAILWAY_CENTRAL_SERVICE:-central}"
  --console-service "${CLIORA_RAILWAY_CONSOLE_SERVICE:-console}"
  --postgres-service "${CLIORA_RAILWAY_POSTGRES_SERVICE:-Postgres}"
  --environment "${CLIORA_RAILWAY_ENVIRONMENT:-production}"
)
have_project=0
live=1
for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --project-id|--status-json) have_project=1 ;;
    --replay) live=0 ;;
  esac
done

TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

if [ "$live" = 1 ]; then
  command -v railway >/dev/null || { echo "FAIL (closed): the railway CLI is required" >&2; exit 2; }
  railway whoami >/dev/null 2>&1 || {
    echo "FAIL (closed): the railway CLI is not logged in (railway login)" >&2; exit 2; }
fi
if [ "$have_project" = 0 ]; then
  [ "$live" = 1 ] || { echo "FAIL (closed): --replay needs --project-id" >&2; exit 2; }
  TMP="$(mktemp -d)"
  railway status --json >"$TMP/status.json" 2>/dev/null || {
    echo "FAIL (closed): railway status --json failed; link the project (railway link)" >&2; exit 2; }
  args+=(--status-json "$TMP/status.json")
fi

# Later flags override the defaults above (argparse keeps the last value).
python3 "$ROOT/scripts/railway/check_trust_topology.py" "${args[@]}" "$@"
