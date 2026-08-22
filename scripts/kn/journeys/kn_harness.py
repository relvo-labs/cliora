"""Shared plumbing for the `v2.0.0-alpha.3` journeys (`plan/25/09-…md` §6).

A thin wrapper over `scripts/cv/journeys/harness.py`, which `plan/24` built and which
already solves the three hard parts: `cliora` on the run's `PATH`, a fakecli that really
fails, and a daemon a test can restart. **This phase does not rebuild any of that.**

Two things are added, and both are properties of this phase rather than of the stack:

* project memory is **off by default**, so a journey has to turn it on;
* ingestion is **asynchronous**, so a journey that asserts on the index has to wait for
  the queue to drain — and must fail loudly rather than silently pass when it does not.

Run inside the stack:

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/kn/journeys/j11_cited_turn.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "cv" / "journeys"))
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402

# Named `kn_harness` rather than `harness` on purpose: the CV harness is also
# `harness`, and two modules with one name on `sys.path` is a circular import that
# reports itself as a missing attribute.
from harness import (  # noqa: E402  (scripts/cv/journeys/harness.py)
    Journey,
    Stack,
    commit,
    use_agent_script,
)

#: How long a journey waits for the ingestion worker. Generous against its three-second
#: round: a timeout here means "the queue never drained", which is a different failure
#: from "the content was not indexed" and has to be reported as such.
DRAIN_TIMEOUT_SECONDS = 60.0

# The CV harness writes evidence to `artifacts/cv/local/journeys` through a module
# constant. Re-pointing it is the smallest correct change: the file format, the commit
# stamp and the freshness rule are all the same, and only the destination differs. A
# forked `Journey` would be a second copy of a format two gates already read.
import harness as _cv_harness  # noqa: E402

KN_EVIDENCE = REPO / "artifacts/kn/local/journeys"
_cv_harness.EVIDENCE = KN_EVIDENCE

__all__ = ["Journey", "KN_EVIDENCE", "KnowledgeStack", "commit", "use_agent_script"]


class KnowledgeStack(Stack):
    """The CV stack, plus the two things project memory needs."""

    async def enable_knowledge(self, project_id: str) -> None:
        """Project memory is off by default (ADR 0038 §7), so every journey turns it on.

        Enabling is also the backfill trigger, which is why `drain_ingestion` follows it
        rather than following the first write: switching on a project that already has
        cards queues one hint per card.
        """
        reply = await self.client.post(
            f"/api/projects/{project_id}/knowledge/enabled",
            json={"enabled": True},
            headers=self.headers,
        )
        reply.raise_for_status()

    async def drain_ingestion(self, project_id: str) -> float:
        """Wait until this project has no pending or running job. Returns the wait.

        **Raises on timeout rather than returning.** A journey that carried on would
        assert against a half-built index and report whichever answer it happened to get,
        which is the one outcome worse than a red test.
        """
        loop = asyncio.get_running_loop()
        started = loop.time()
        while loop.time() - started < DRAIN_TIMEOUT_SECONDS:
            async with self.maker() as session:
                outstanding = await session.scalar(
                    sa.text(
                        "SELECT count(*) FROM knowledge_jobs "
                        "WHERE project_id = :pid AND state IN ('pending','running')"
                    ),
                    {"pid": project_id},
                )
            if not outstanding:
                return loop.time() - started
            await asyncio.sleep(0.5)
        raise TimeoutError(
            f"ingestion did not drain for project {project_id} within "
            f"{DRAIN_TIMEOUT_SECONDS}s — the worker is not running, or a job is looping"
        )
