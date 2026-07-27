#!/usr/bin/env bash
# Drill: ClioraDatabasePoolPressure / ClioraDatabasePoolExhausted.
#
# Central must be started with a pool of 1 and no overflow, so a handful of concurrent
# requests saturates it deterministically:
#
#   CLIORA_DB_POOL_SIZE=1 CLIORA_DB_MAX_OVERFLOW=0 CLIORA_DB_POOL_TIMEOUT_SECONDS=1 \
#   CLIORA_METRICS_ENABLED=true CLIORA_METRICS_SCRAPE_TOKEN=<32+ chars> \
#     uv run --project backend uvicorn app.main:app --app-dir backend --port 8000
#
# The point of the drill is the *shape* of the failure: requests must be refused with a
# 503 rather than hanging. A hang is the bug the pool timeout exists to prevent.
. "$(dirname "$0")/_common.sh"

CONCURRENCY="${CLIORA_DRILL_CONCURRENCY:-20}"

confirm "This floods ${CENTRAL} with ${CONCURRENCY} concurrent requests to saturate its
database pool. Only run it against a Central started with the tiny pool above."

banner "Before"
metric database_pool_usage
metric database_pool_timeout_total

banner "Flooding with ${CONCURRENCY} concurrent requests"
codes=$(mktemp)
for _ in $(seq "${CONCURRENCY}"); do
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 "${CENTRAL}/readyz" >>"${codes}" &
done
wait
echo "HTTP status codes returned:"
sort "${codes}" | uniq -c
rm -f "${codes}"
echo
echo "Expect some 503s. A 000 (timeout) or a hang means the pool timeout is not"
echo "bounding the wait — that is a defect, not a successful drill."

banner "After"
metric database_pool_usage
metric database_pool_timeout_total

follow_up "cliora_database_pool_timeout_total, cliora_database_pool_usage{state=\"checked_out\"}" \
  "docs/runbooks/db-exhaustion.md"
