#!/usr/bin/env python
"""**J9** — an agent cannot decide (exit condition 9, SR-1 row 1).

There is no UI path for this, which is the point: the credential is read off disk exactly
the way an agent inside a run would read it, and the request is made with it. This is also
the third place the run-credential seam is checked — `context_seam_test.go` proves the
filenames agree, `j0_agent_seam.py` proves the token works, and this proves what it cannot
do with it.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import sqlalchemy as sa  # noqa: E402

from harness import BASE, Journey, Stack, use_agent_script  # noqa: E402

# The agent does nothing but hold still long enough for its token to be read off disk.
# `cliora task say` first, so the journey can tell "the token was never written" from
# "the token was written and the decision was refused" — two different failures.
AGENT = """#!/usr/bin/env bash
set -uo pipefail
cliora task say "AGENT_IS_ALIVE" || exit 5
sleep 20
"""


async def main() -> int:
    journey = Journey("j9-decision", "a run credential cannot write a decision")
    async with Stack() as stack:
        await stack.require_runner()
        await stack.require_quiet_database()
        use_agent_script(AGENT)

        journey.step("dispatching, then reading the run's own credential off disk")
        project_id = await stack.project("cv-j9")
        task = await stack.card(project_id)
        dispatched = await stack.dispatch(task["id"])
        run_id = dispatched["run_id"]
        claimed = await stack.wait_for_claim(run_id)
        journey.check(claimed is not None, "the runner claimed the run")
        if claimed is None:
            return journey.finish()

        work_dir = os.environ.get("E2E_RUNNER_WORK_DIR", "")
        token_path = Path(work_dir) / run_id / ".cliora" / "context" / "run.token"
        token = await stack.wait_for(
            lambda: asyncio.sleep(0, result=token_path.read_text().strip())
            if token_path.exists()
            else asyncio.sleep(0, result=None),
            30.0,
            "the daemon to write run.token",
        )
        journey.check(bool(token), "the run's credential is on disk", str(token_path))
        if not token:
            return journey.finish()

        journey.step("using it to post a decision")
        async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as agent:
            refused = await agent.post(
                "/api/cli/runs/messages",
                json={"body": "接受這份規格提案。", "kind": "decision"},
                headers={"authorization": f"Bearer {token}"},
            )
            journey.note("status", refused.status_code)
            journey.check(
                refused.status_code == 403, "refused with 403", refused.status_code
            )
            journey.check(
                refused.json().get("error", {}).get("code") == "AGENT_CANNOT_DECIDE",
                "and with the machine code that says why",
                refused.json().get("error", {}).get("code"),
            )

            # The same credential *can* speak — otherwise the 403 above might only mean
            # "this token is not valid for anything".
            allowed = await agent.post(
                "/api/cli/runs/messages",
                json={"body": "一則普通留言。", "kind": "comment"},
                headers={"authorization": f"Bearer {token}"},
            )
            journey.check(
                allowed.status_code == 201,
                "while an ordinary comment from the same credential is accepted",
                allowed.status_code,
            )

        kinds = [m["kind"] for m in await stack.messages(task["id"])]
        journey.check("decision" not in kinds, "no decision reached the card", kinds)

        # `audit_logs`, and the JSON column is called `metadata` on the wire and
        # `audit_metadata` on the model — read by its real name so this does not quietly
        # select nothing and call that a pass.
        async with stack.maker() as session:
            rows = (
                await session.execute(
                    sa.text(
                        "select action, metadata from audit_logs "
                        "order by created_at desc limit 25"
                    )
                )
            ).all()
        audited = [dict(row._mapping) for row in rows]
        journey.note("audit_actions", [row["action"] for row in audited])
        journey.check(bool(audited), "the attempt left an audit trail", len(audited))
        journey.check(
            all("body" not in (row.get("metadata") or {}) for row in audited),
            "and no audit entry carries a message body (SR-1 §1.5)",
        )

        # Tidy up: the agent is sleeping, and leaving it running would make the next
        # journey's quiet-database guard refuse to start.
        await stack.client.post(
            f"/api/runs/{run_id}/cancel", json={}, headers=stack.headers
        )
        await stack.wait_for_terminal_run(run_id, 60.0)
    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
