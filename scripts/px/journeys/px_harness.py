"""Shared plumbing for `v2.0.0-beta.1`'s three daemon journeys (`plan/26/10` §4).

A thin wrapper over `scripts/cv/journeys/harness.py`, which `plan/24` built and which
already solves the hard parts: `cliora` on a run's `PATH`, a fakecli that really fails,
and a daemon a journey can restart. **This phase rebuilds none of that.**

What is added is one thing, and it is the phase's own: **reading the answer through the
read model.** A journey here does not check a card by fetching `/api/tasks/{id}` — that
would test V2.1. It checks it through `work-items`, `work-counts` and `/api/me/work-items`,
because the claim under test is that those three agree with each other and with what the
daemon actually did.

Run inside the stack:

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/px/journeys/j15_no_eligible_runner.py
"""

from __future__ import annotations

import base64
import json
import pathlib
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "cv" / "journeys"))
sys.path.insert(0, str(REPO / "scripts" / "kn" / "journeys"))
sys.path.insert(0, str(REPO / "backend"))

# Named `px_harness` rather than `harness`: the CV harness is `harness`, and two modules
# with one name on `sys.path` is a circular import that reports itself as a missing
# attribute (the same trap `kn_harness` documents).
import harness as _cv_harness  # noqa: E402
from harness import Journey, commit, use_agent_script  # noqa: E402

# **`KnowledgeStack` rather than `Stack`.** J1 needs project memory — its
# "agent starts work citing what was accepted" segment is the phase's purpose and
# `plan/26/10` §4 forbids degrading it — and `alpha.3` already solved enabling and
# draining. Inheriting is cheaper than a second implementation that drifts.
from kn_harness import KnowledgeStack  # noqa: E402

PX_EVIDENCE = REPO / "artifacts/px/local/journeys"
# **After the `kn_harness` import, deliberately.** `EVIDENCE` is one module-level name in
# `harness`, and `kn_harness` assigns it too — importing it above and assigning here is
# what makes this phase's journeys write to `artifacts/px/local/`. Move this line up and they
# silently land in `artifacts/kn/`.
_cv_harness.EVIDENCE = PX_EVIDENCE

__all__ = [
    "Journey",
    "PX_EVIDENCE",
    "ReadModelStack",
    "commit",
    "encode_filter",
    "use_agent_script",
]


def encode_filter(filter_: dict[str, Any]) -> str:
    """`base64url(json)` — the same encoding the browser sends and the server decodes.

    Written here rather than imported because the browser's copy is TypeScript. One
    sentence of duplication against a cross-language boundary; the *shape* is asserted by
    the server's own tests.
    """
    raw = base64.urlsafe_b64encode(json.dumps(filter_).encode()).decode()
    return raw.rstrip("=")


class ReadModelStack(KnowledgeStack):
    """The CV stack, read through V2-P1's endpoints."""

    async def work_items(self, project_id: str, **params: Any) -> dict[str, Any]:
        reply = await self.client.get(
            f"/api/projects/{project_id}/work-items",
            params={key: value for key, value in params.items() if value is not None},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()

    async def work_counts(self, project_id: str, **params: Any) -> dict[str, Any]:
        reply = await self.client.get(
            f"/api/projects/{project_id}/work-counts",
            params={key: value for key, value in params.items() if value is not None},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()

    async def my_work_items(self, **params: Any) -> dict[str, Any]:
        reply = await self.client.get(
            "/api/me/work-items",
            params={key: value for key, value in params.items() if value is not None},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()

    async def card_in_read_model(
        self, project_id: str, task_id: str
    ) -> dict[str, Any] | None:
        """One card, as the read model sees it. None when the filter excludes it."""
        page = await self.work_items(project_id, limit=100)
        for group in page["groups"]:
            for item in group["items"]:
                if item["id"] == task_id:
                    return item
        return None

    async def attention_of(self, project_id: str, task_id: str) -> str | None:
        card = await self.card_in_read_model(project_id, task_id)
        return None if card is None else card.get("primary_attention")

    async def wait_for_attention(
        self, project_id: str, task_id: str, level: str | None, deadline: float = 60.0
    ) -> str | None:
        """Poll the read model until a card's primary attention is `level`.

        Polled rather than computed, because the point of the journey is that the value a
        *screen* would show arrives — attention has a phase that reads an in-process
        registry, so "the database says so" is not the same claim.
        """

        async def matches() -> object:
            current = await self.attention_of(project_id, task_id)
            return {"level": current} if current == level else None

        found = await self.wait_for(
            matches, deadline, f"{task_id} to show attention {level!r}"
        )
        return None if found is None else found["level"]

    async def set_labels(self, task_id: str, labels: list[str]) -> dict[str, Any]:
        task = await self.task(task_id)
        reply = await self.client.patch(
            f"/api/tasks/{task_id}",
            json={"required_labels": labels, "version": task["version"]},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()["task"]

    async def answer_and_continue(
        self, task_id: str, question_id: str, body: str
    ) -> dict[str, Any]:
        """ "Reply and continue" — the button the Drawer puts a sentence under.

        `resume=True` is the whole difference from a comment: it creates a new agent turn.
        The endpoint is `alpha.2`'s and this phase added nothing to it.
        """
        reply = await self.client.post(
            f"/api/tasks/{task_id}/questions/{question_id}/answer",
            json={"body": body, "resume": True},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()

    # --- the V2.5 flow J1 walks -------------------------------------------------
    #
    # Written here rather than in the journey because J1 is long enough that its own
    # file should read as the flow, not as HTTP.

    async def create_card(self, project_id: str, **fields: Any) -> dict[str, Any]:
        """A card with whatever fields the caller names — **including `card_kind`**.

        The two the console sends and the server ignored until this phase
        (`card_kind`, `requirement_id`) are ordinary keyword arguments here, so a
        regression shows up as this journey failing at step 2 rather than as a card that
        looks right and behaves like an implementation card.
        """
        reply = await self.client.post(
            f"/api/projects/{project_id}/tasks", json=fields, headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()["task"]

    async def patch(self, task_id: str, **fields: Any) -> dict[str, Any]:
        """A patch that reads the card's version first, the way the console does."""
        current = await self.task(task_id)
        reply = await self.client.patch(
            f"/api/tasks/{task_id}",
            json={**fields, "version": current["version"]},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()["task"]

    async def try_patch(
        self, task_id: str, **fields: Any
    ) -> tuple[int, dict[str, Any]]:
        """The same patch, without raising — for the refusals a journey asserts."""
        current = await self.task(task_id)
        reply = await self.client.patch(
            f"/api/tasks/{task_id}",
            json={**fields, "version": current["version"]},
            headers=self.headers,
        )
        return reply.status_code, reply.json()

    async def requirement(self, project_id: str, raw_text: str) -> dict[str, Any]:
        reply = await self.client.post(
            f"/api/projects/{project_id}/requirements",
            json={"raw_text": raw_text},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()

    async def requirement_detail(self, requirement_id: str) -> dict[str, Any]:
        reply = await self.client.get(
            f"/api/requirements/{requirement_id}", headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()

    async def try_approve_requirement(
        self, requirement_id: str
    ) -> tuple[int, dict[str, Any]]:
        reply = await self.client.post(
            f"/api/requirements/{requirement_id}/approve", headers=self.headers
        )
        return reply.status_code, reply.json()

    async def accept_proposal(
        self, proposal_id: str, *, note: str | None = None
    ) -> dict[str, Any]:
        reply = await self.client.post(
            f"/api/proposals/{proposal_id}/accept",
            json={"note": note} if note else {},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()

    async def approve_gate(self, task_id: str, gate_key: str) -> dict[str, Any]:
        reply = await self.client.post(
            f"/api/tasks/{task_id}/gates/{gate_key}", json={}, headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()

    async def verification_reports(self, task_id: str) -> list[dict[str, Any]]:
        reply = await self.client.get(
            f"/api/tasks/{task_id}/verification", headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()

    async def terminal_sessions(self, project_id: str) -> int:
        """How many terminal sessions this project ever had.

        The objective assertion behind "**全程不進 Terminal**". Every other claim in J1
        is about something happening; this one is about something *not* happening, and a
        count is the only form of that claim that cannot be satisfied by being careful
        while writing the journey.
        """
        import sqlalchemy as sa

        async with self.maker() as session:
            return int(
                await session.scalar(
                    sa.text(
                        "SELECT count(*) FROM terminal_sessions WHERE project_id = :pid"
                    ),
                    {"pid": project_id},
                )
                or 0
            )
