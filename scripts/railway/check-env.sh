#!/usr/bin/env bash
# Pre-deploy variable check for the Railway environment (RW-06).
#
# Thin on purpose: it fetches the variable sets and hands them to
# `scripts/railway/check_env.py`, where every rule lives and is unit-tested. A gate whose
# logic is embedded in a shell heredoc cannot be tested, and an untested pre-deploy gate is
# a gate nobody trusts enough to keep passing.
#
#   scripts/railway/check-env.sh --domain cliora.example.com
#   scripts/railway/check-env.sh --central-vars a.json --console-vars b.json   # offline
#
# Values are never printed — only variable names and the property that failed. This runs in
# CI, and CI logs outlive the deploy.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CENTRAL_SERVICE="${CLIORA_RAILWAY_CENTRAL_SERVICE:-central}"
CONSOLE_SERVICE="${CLIORA_RAILWAY_CONSOLE_SERVICE:-console}"
POSTGRES_SERVICE="${CLIORA_RAILWAY_POSTGRES_SERVICE:-Postgres}"

DOMAIN=""
CENTRAL_VARS=""
CONSOLE_VARS=""
POSTGRES_VARS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --domain)        DOMAIN="$2"; shift 2 ;;
    --central-vars)  CENTRAL_VARS="$2"; shift 2 ;;
    --console-vars)  CONSOLE_VARS="$2"; shift 2 ;;
    --postgres-vars) POSTGRES_VARS="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

if [ -z "$CENTRAL_VARS" ] || [ -z "$CONSOLE_VARS" ]; then
  command -v railway >/dev/null || {
    echo "the railway CLI is required (or pass --central-vars/--console-vars)" >&2
    exit 2
  }
  TMP="$(mktemp -d)"
  # `--json` shape is not something to bet a gate on; check_env.normalise() accepts both a
  # flat mapping and a list of {name,value} records.
  railway variables --service "$CENTRAL_SERVICE" --json >"$TMP/central.json" || {
    echo "could not read variables for service '$CENTRAL_SERVICE'" >&2; exit 2; }
  railway variables --service "$CONSOLE_SERVICE" --json >"$TMP/console.json" || {
    echo "could not read variables for service '$CONSOLE_SERVICE'" >&2; exit 2; }
  CENTRAL_VARS="$TMP/central.json"
  CONSOLE_VARS="$TMP/console.json"
  if railway variables --service "$POSTGRES_SERVICE" --json >"$TMP/postgres.json" 2>/dev/null; then
    POSTGRES_VARS="$TMP/postgres.json"
  else
    echo "note: could not read '$POSTGRES_SERVICE' variables; skipping the password cross-check"
  fi
fi

args=(
  --central-vars "$CENTRAL_VARS"
  --console-vars "$CONSOLE_VARS"
  --central-config "$ROOT/deploy/railway/central.railway.json"
)
[ -n "$POSTGRES_VARS" ] && args+=(--postgres-vars "$POSTGRES_VARS")
[ -n "$DOMAIN" ] && args+=(--domain "$DOMAIN")

exec python3 "$ROOT/scripts/railway/check_env.py" "${args[@]}"
