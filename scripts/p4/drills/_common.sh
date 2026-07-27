# Shared helpers for the alert drills (P4-09). Sourced, not executed.

set -euo pipefail

CENTRAL="${CLIORA_CENTRAL_URL:-http://127.0.0.1:8000}"
METRICS_TOKEN="${CLIORA_METRICS_SCRAPE_TOKEN:-}"

confirm() {
  # Several drills are disruptive, so the default is no. CLIORA_DRILL_YES=1 is for the
  # CI drill job, where the environment is already disposable.
  if [ "${CLIORA_DRILL_YES:-}" = "1" ]; then
    return 0
  fi
  printf '%s\n' "$1"
  printf 'Proceed? [y/N] '
  read -r answer
  case "$answer" in
    y | Y) return 0 ;;
    *) echo "aborted"; exit 1 ;;
  esac
}

require_metrics() {
  if [ -z "$METRICS_TOKEN" ]; then
    echo "Set CLIORA_METRICS_SCRAPE_TOKEN (and enable CLIORA_METRICS_ENABLED on Central)." >&2
    exit 1
  fi
}

# Print the current value of one metric, so a drill can show before/after without
# needing Prometheus itself.
metric() {
  require_metrics
  curl -fsS -H "X-Metrics-Token: ${METRICS_TOKEN}" "${CENTRAL}/api/metrics" \
    | grep -E "^cliora_${1}" || echo "(cliora_${1}: not present yet)"
}

banner() {
  echo
  echo "=== $* ==="
}

follow_up() {
  banner "What to watch"
  echo "Metric:  $1"
  echo "Runbook: $2"
  echo
  echo "Record the fire time, whether each runbook step worked, and the recovery time"
  echo "in artifacts/p4/<run>/drills.md."
}
