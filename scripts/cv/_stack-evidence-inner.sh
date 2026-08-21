#!/usr/bin/env bash
# Runs inside the stack that `scripts/cv/stack-evidence.sh` started. Not meant to be
# invoked directly: it needs the E2E_* variables that stack exports.
#
# **The order is not arbitrary, and each step's guard is why.**
#
#   1. `answer-to-turn` first, on an untouched database. Its own guard counts a
#      `waiting_for_input` run as contention — that was plan/23's choice and this phase
#      does not relitigate it — so it has to run before anything parks a card.
#   2. the dataset and the four measurements next: 700 inert rows, nothing in flight.
#   3. the journeys, several of which leave a card waiting on purpose.
#   4. compatibility **last**, because a 0.12.0 node cannot report completion (`CE-17`)
#      and therefore leaves runs stuck in `running` — real contention for anything after.
set -uo pipefail
status=0

echo "==> answer to turn (exit condition 1)"
uv run --project backend python scripts/cv/measure-answer-to-turn.py --samples 20 || status=1

echo "==> the fixed dataset"
uv run --project backend python scripts/cv/seed-dataset.py || status=1

echo "==> the four remaining measurements"
uv run --project backend python scripts/cv/measure-conversation.py || status=1

for journey in j6_comments j8_concurrent j9_decision j5_chaos; do
  echo "==> journey $journey"
  uv run --project backend python "scripts/cv/journeys/$journey.py" || status=1
done

# The browser suite writes its JSON report where `GATE-CE-JOURNEY-COVERAGE` looks for it.
# Without that file the gate cannot tell "passed" from "skipped", which is its whole job.
echo "==> browser journeys (J1a, J3, J7)"
( cd frontend \
  && PLAYWRIGHT_JSON_OUTPUT_NAME="../artifacts/cv/local/playwright.json" \
     npx playwright test --project=chromium --workers=1 conversation.spec.ts \
     --reporter=json >/dev/null ) || status=1

echo "==> 0.12.0 compatibility"
scripts/cv/compat-0120.sh || status=1

exit "$status"
