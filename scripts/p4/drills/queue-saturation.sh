#!/usr/bin/env bash
# Drill: ClioraTerminalQueueNearLimit / ClioraTerminalQueueOverflow.
#
# Needs a browser terminal WebSocket that connects and then stops reading, which curl
# cannot do — so this delegates to the Python slow-client harness (P4-11) rather than
# pretending a shell can reproduce it.
. "$(dirname "$0")/_common.sh"

HARNESS="scripts/p4/load/terminal_clients.py"

confirm "This attaches a deliberately slow terminal client and floods it with output
until its bounded queue overflows and the connection is closed with terminal.gap."

if [ ! -f "$HARNESS" ]; then
  cat <<'MSG'
The slow-client harness is not present yet (it lands with P4-11).

Until then, reproduce by hand:
  1. Open a session's terminal in a browser.
  2. Run something that writes fast, e.g.  yes "$(head -c 200 /dev/zero | tr '\0' x)"
  3. Suspend the browser tab (background it, or throttle it in devtools).
The queue fills, the connection closes with code 1013, and the terminal shows an
explicit gap marker rather than pretending the output was continuous.
MSG
  follow_up "cliora_terminal_queue_overflow_total, cliora_terminal_client_queue_bytes" \
    "docs/runbooks/queue-saturation.md"
  exit 0
fi

: "${CLIORA_DRILL_PASSWORD:?Set CLIORA_DRILL_PASSWORD (and CLIORA_DRILL_ADMIN) for the drill Central}"

banner "Before"
metric terminal_queue_overflow_total

# The flags below must match the harness's actual interface. They did not: this drill was
# written in P4-09 against a guessed CLI (`--flood`, no base URL, no credentials) because
# the harness only landed with P4-11, and the mismatch sat unnoticed until the drill was
# first run end to end. `test_drill_harness_flags_exist` now compares the two.
#
# One slow client and one flood client, with the output rate high enough that the slow
# client's queue actually overflows inside the run rather than merely filling.
uv run --project backend python "$HARNESS" \
  --base-url "$CENTRAL" \
  --admin-user "${CLIORA_DRILL_ADMIN:-admin}" \
  --admin-password "$CLIORA_DRILL_PASSWORD" \
  --clients 4 --sessions 2 --slow-clients 1 --flood-clients 1 \
  --duration 12 --output-rate-bytes $((2 * 1024 * 1024))

banner "After"
metric terminal_queue_overflow_total

follow_up "cliora_terminal_queue_overflow_total" "docs/runbooks/queue-saturation.md"
