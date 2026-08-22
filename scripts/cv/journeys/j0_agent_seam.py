#!/usr/bin/env python
"""`CE-01`'s assertion: **inside a real run, `cliora` exists, works, and is authorised.**

Not one of the seven journeys — a preflight for all of them. Every journey after this
one assumes an agent can call the CLI from inside a run, and when that assumption breaks
the symptom is indirect: the card is claimed, the run succeeds, and nothing was ever
asked. This makes it direct.

It is the *third* place the run-credential seam is checked, and each of the three fails
differently:

  1. `internal/cli/context_seam_test.go`  the daemon's filename and the CLI's agree
  2. **here**                             `cliora` is on PATH in a run, and its token works
  3. `j9_decision.py`                     that same token cannot write a decision

Two and three did not exist before `plan/24`, and their absence is why `CV-08`'s four
subcommands shipped without ever running inside an actual run (plan/23/10 §9.1).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Journey, Stack, use_agent_script  # noqa: E402

# `context show` proves the credential file was found and parsed; `task say` proves the
# token is accepted by Central. The marker carries the card ref, so a message from some
# other card cannot satisfy the assertion.
AGENT = """#!/usr/bin/env bash
set -uo pipefail
context="$(cliora context show 2>&1)" || { printf 'context show failed: %s\\n' "$context" >&2; exit 4; }
cliora task say "AGENT_SEAM_OK" || exit 5
printf '%s\\n' "$context"
"""


async def main() -> int:
    journey = Journey("j0-agent-seam", "cliora works inside a run")
    async with Stack() as stack:
        await stack.require_runner()
        await stack.require_quiet_database()
        use_agent_script(AGENT)

        journey.step("dispatching a clarification card")
        project_id = await stack.project("cv-seam")
        task = await stack.card(project_id, "檢查：run 裡的 cliora")
        dispatched = await stack.dispatch(task["id"])
        run_id = dispatched["run_id"]

        run = await stack.wait_for_terminal_run(run_id)
        journey.check(run is not None, "the run reached a terminal state")
        if run is None:
            return journey.finish()

        journey.note("run_status", run.status)
        journey.note("run_result", run.result)
        # A non-zero exit means the script's own `exit 4` / `exit 5` fired — which is
        # exactly the failure this preflight exists to surface, now that fakecli carries
        # a script's status out (`CE-01` ②).
        journey.check(
            run.status == "succeeded", "the agent's script exited 0", run.status
        )

        bodies = [m["body"] for m in await stack.messages(task["id"])]
        journey.note("messages", bodies)
        journey.check(
            any("AGENT_SEAM_OK" in b for b in bodies),
            "`cliora task say` from inside the run reached Central",
        )

        text = await stack.run_log(run_id)
        # The log goes into the evidence file, not just onto a terminal: when this
        # preflight fails it is the only place that says *why*, and a failure whose
        # explanation was printed and lost costs the next person the whole run again.
        journey.note("run_log", text)
        journey.check(
            task["card_ref"] in text,
            "`cliora context show` printed this card's ref",
            task["card_ref"],
        )
        journey.check(
            "無法連線到 Cliora" not in text,
            "the CLI did not report the platform as unreachable",
        )
    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
