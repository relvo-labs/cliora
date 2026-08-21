"""Shared plumbing for the `v2.0.0-alpha.2` API-level journeys (`plan/24/03`).

Four of the seven journeys are scripts rather than browser tests (D69), because what
they assert is timing or concurrency that a browser cannot control: a daemon killed
between two steps (J5), twenty writes and a count (J6), two requests genuinely in
flight at once (J8), and a request no UI can make (J9).

They all need the same six things, and this module is those six:

* the stack's credentials and base URL, from the variables `run-stack.sh` exports;
* a database session, because the assertions are about rows, not responses;
* a project and a clarification card an agent needs no repository for;
* a refusal to run against a database with other runs still in flight — the lesson
  `plan/23/10` §5 paid for (a leftover run takes the runner's slot and every number
  afterwards is of the queue);
* an assertion collector that reports **every** failure rather than the first, since a
  journey takes minutes and stopping at the first one wastes the rest;
* one evidence file per journey, stamped with the commit, because
  `GATE-CE-EVIDENCE-FRESH` refuses numbers that were measured somewhere else.

Run inside the stack:

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/cv/journeys/j6_comments.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

import httpx  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import AgentRunner, Task, TaskMessage, TaskQuestion, TaskRun  # noqa: E402

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")
ADMIN = os.environ.get("E2E_ADMIN_USER", "e2e-admin")
PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD", "e2e-admin-pw")
DB_URL = os.environ.get("CLIORA_DATABASE_URL", "")
EVIDENCE = REPO / "artifacts/cv/local/journeys"

#: How long to wait for the runner to pick something up. Generous against the 5s poll:
#: a timeout here means "the runner never took it", which is a different failure from a
#: slow one and is reported as such.
CLAIM_DEADLINE = 90.0
AGENT_DEADLINE = 120.0


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class Journey:
    """One journey: its assertions, its timing, and its evidence file."""

    def __init__(self, name: str, title: str) -> None:
        self.name = name
        self.title = title
        self.checks: list[dict] = []
        self.notes: dict[str, object] = {}
        self.started = time.monotonic()

    def check(self, ok: bool, claim: str, detail: object = None) -> bool:
        """Record one assertion. **Never raises** — see the module docstring."""
        self.checks.append({"claim": claim, "ok": bool(ok), "detail": _plain(detail)})
        print(
            f"  {'PASS' if ok else 'FAIL'}  {claim}"
            + (f"  — {detail}" if detail is not None and not ok else ""),
            flush=True,
        )
        return bool(ok)

    def note(self, key: str, value: object) -> None:
        self.notes[key] = _plain(value)

    def step(self, message: str) -> None:
        print(f"==> {message}", flush=True)

    def finish(self) -> int:
        failed = [c for c in self.checks if not c["ok"]]
        payload = {
            "journey": self.name,
            "title": self.title,
            "commit": commit(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "seconds": round(time.monotonic() - self.started, 2),
            "checks": self.checks,
            "notes": self.notes,
            "verdict": "PASS" if not failed else "FAIL",
        }
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        out = EVIDENCE / f"{self.name}.json"
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"\n{self.name}: {len(self.checks) - len(failed)}/{len(self.checks)} "
            f"→ {payload['verdict']}  ({out.relative_to(REPO)})"
        )
        return 0 if not failed else 1


def _plain(value: object) -> object:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class Stack:
    """The running stack: HTTP client, database, and the enabled runner."""

    def __init__(self) -> None:
        if not DB_URL:
            raise SystemExit("CLIORA_DATABASE_URL is unset — run inside the e2e stack")
        self.engine = create_async_engine(DB_URL, pool_pre_ping=True)
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.client = httpx.AsyncClient(base_url=BASE, timeout=30.0)
        self.headers: dict[str, str] = {}
        self.runner: AgentRunner | None = None

    async def __aenter__(self) -> "Stack":
        reply = await self.client.post(
            "/api/auth/login", json={"username": ADMIN, "password": PASSWORD}
        )
        reply.raise_for_status()
        self.headers = {
            "authorization": f"Bearer {reply.json()['tokens']['access_token']}"
        }
        async with self.maker() as session:
            self.runner = (
                (
                    await session.execute(
                        sa.select(AgentRunner).where(AgentRunner.enabled.is_(True))
                    )
                )
                .scalars()
                .first()
            )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.client.aclose()
        await self.engine.dispose()

    # --- guards ----------------------------------------------------------------

    async def require_runner(self) -> AgentRunner:
        if self.runner is None:
            raise SystemExit("no enabled runner: start the stack with E2E_RUNNER=1")
        return self.runner

    #: The statuses that actually occupy one of the runner's `max_concurrent` slots.
    #: **`waiting_for_input` is not one of them** — ADR 0029 §5 keeps two numbers
    #: precisely because a run parked on a person's reply holds no process. Counting it
    #: would make every journey after the first refuse to start, since several of them
    #: leave a card waiting on purpose.
    CONTENDING = ("queued", "claimed", "running")

    async def require_quiet_database(self) -> None:
        """Refuse to start while other runs hold execution capacity (`plan/23/10` §5).

        A leftover *running* run holds a slot, and every wait afterwards is really a wait
        on that slot. Refused rather than reported: a number produced under contention
        gets quoted later as if it were the platform's.
        """
        async with self.maker() as session:
            in_flight = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.status.in_(self.CONTENDING))
                )
            ).scalar_one()
        if in_flight:
            raise SystemExit(
                f"{in_flight} run(s) are holding runner capacity in this database; they "
                "will compete for its slots. Use an empty one:\n"
                "  dropdb cliora_e2e && createdb cliora_e2e"
            )

    # --- fixtures --------------------------------------------------------------

    async def project(self, prefix: str = "cv-journey") -> str:
        name = f"{prefix}-{uuid.uuid4().hex[:8]}"
        reply = await self.client.post(
            "/api/projects", json={"name": name, "slug": name}, headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()["id"]

    async def card(
        self, project_id: str, title: str = "釐清：這一輪的驗收標準"
    ) -> dict:
        """A card an agent needs no repository for: `source: none`, `delivery: none`, `ready`.

        **Not a `clarification` card**, despite the title. `CreateTaskRequest` has no
        `card_kind` field, so passing one — as `measure-answer-to-turn.py` also does — was
        silently ignored and the card has always been an ordinary implementation card. A
        real clarification card needs a requirement
        (`TASK_CLARIFICATION_NEEDS_REQUIREMENT`), which is V2.5's flow; the conversation
        machinery under test here does not care which kind the card is.
        """
        reply = await self.client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": title, "source": "none", "delivery": "none"},
            headers=self.headers,
        )
        reply.raise_for_status()
        task = reply.json()["task"]
        if task["stage"] != "ready":
            moved = await self.client.patch(
                f"/api/tasks/{task['id']}",
                json={"stage": "ready", "version": task["version"]},
                headers=self.headers,
            )
            moved.raise_for_status()
            task = moved.json()["task"]
        return task

    async def dispatch(self, task_id: str) -> dict:
        reply = await self.client.post(
            f"/api/tasks/{task_id}/dispatch", json={}, headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()

    async def waiting_parent(
        self, task_id: str, project_id: str, *, live: bool = False
    ) -> str:
        """A finished run that left an open question — the state D59 made possible.

        Written directly rather than produced by dispatching: it is *setup*, not the
        interval under test, and racing an agent to ask a question would only add
        flakiness to the part nobody is measuring (the same reasoning
        `measure-answer-to-turn.py` records for its own staging).
        """
        from app.services.conversation import ConversationService

        runner = await self.require_runner()
        # Two shapes of waiting, and D66 keeps both: an agent that asked and **ended**
        # (`succeeded` / `awaiting_input`), and one that asked and is **still polling**
        # (`waiting_for_input`). D67 treats a plain comment differently in each, so a
        # journey about comments needs to be able to stage either.
        async with self.maker() as session:
            task = await session.get(Task, uuid.UUID(task_id))
            run = TaskRun(
                id=uuid.uuid4(),
                task_id=uuid.UUID(task_id),
                project_id=uuid.UUID(project_id),
                seq=1,
                status="waiting_for_input" if live else "succeeded",
                result=None if live else "awaiting_input",
                runner_id=runner.id,
                source_kind="none",
                input_from_seq=0,
                input_to_seq=0,
                finished_at=None if live else datetime.now(timezone.utc),
            )
            session.add(run)
            await session.flush()
            run.root_run_id = run.id
            await ConversationService(session).post(
                task=task,
                body="要我用哪一版的驗收標準？",
                kind="question",
                author_kind="agent",
                author_runner_id=runner.id,
                run_id=run.id,
            )
            await session.commit()
            return str(run.id)

    # --- reads -----------------------------------------------------------------

    async def open_question(self, task_id: str) -> str | None:
        reply = await self.client.get(
            f"/api/tasks/{task_id}/questions", headers=self.headers
        )
        reply.raise_for_status()
        return next((q["id"] for q in reply.json() if q["state"] == "open"), None)

    async def questions(self, task_id: str) -> list[dict]:
        reply = await self.client.get(
            f"/api/tasks/{task_id}/questions", headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()

    async def messages(self, task_id: str, limit: int = 500) -> list[dict]:
        reply = await self.client.get(
            f"/api/tasks/{task_id}/messages",
            params={"limit": limit},
            headers=self.headers,
        )
        reply.raise_for_status()
        return reply.json()["items"]

    async def task(self, task_id: str) -> dict:
        reply = await self.client.get(f"/api/tasks/{task_id}", headers=self.headers)
        reply.raise_for_status()
        body = reply.json()
        return body.get("task", body)

    async def run_log(self, run_id: str) -> str:
        """The run's stored event stream, joined.

        `lines[].data` and not `items[].body`: the segments are returned **unparsed**
        because the event schema belongs to a third-party CLI (`RunLogLineDTO`).
        """
        reply = await self.client.get(f"/api/runs/{run_id}/logs", headers=self.headers)
        reply.raise_for_status()
        return "\n".join(line.get("data", "") for line in reply.json().get("lines", []))

    async def runs(self, task_id: str) -> list[dict]:
        reply = await self.client.get(
            f"/api/tasks/{task_id}/runs", headers=self.headers
        )
        reply.raise_for_status()
        return reply.json()

    async def count_runs(self, task_id: str) -> int:
        async with self.maker() as session:
            return (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.task_id == uuid.UUID(task_id))
                )
            ).scalar_one()

    async def continuations_of(self, question_id: str) -> list[TaskRun]:
        async with self.maker() as session:
            return list(
                (
                    await session.execute(
                        sa.select(TaskRun).where(
                            TaskRun.resumed_question_id == uuid.UUID(question_id)
                        )
                    )
                )
                .scalars()
                .all()
            )

    async def sequence(self, task_id: str) -> list[int]:
        async with self.maker() as session:
            return list(
                (
                    await session.execute(
                        sa.select(TaskMessage.conversation_seq)
                        .where(TaskMessage.task_id == uuid.UUID(task_id))
                        .order_by(TaskMessage.conversation_seq)
                    )
                )
                .scalars()
                .all()
            )

    async def question_row(self, question_id: str) -> TaskQuestion | None:
        async with self.maker() as session:
            return await session.get(TaskQuestion, uuid.UUID(question_id))

    # --- waits -----------------------------------------------------------------

    async def wait_for(self, predicate, deadline: float, what: str):
        """Poll `predicate` until it returns something truthy, or give up.

        Returns `None` on timeout rather than raising: "the runner never took it" is a
        result a journey should record and carry on from, not a stack trace.
        """
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            value = await predicate()
            if value:
                return value
            await asyncio.sleep(0.25)
        print(f"  (timed out after {deadline:.0f}s waiting for {what})", flush=True)
        return None

    async def wait_for_open_question(
        self, task_id: str, deadline: float = AGENT_DEADLINE
    ):
        return await self.wait_for(
            lambda: self.open_question(task_id), deadline, "the agent to ask a question"
        )

    async def wait_for_claim(self, run_id: str, deadline: float = CLAIM_DEADLINE):
        async def claimed():
            async with self.maker() as session:
                run = await session.get(TaskRun, uuid.UUID(run_id))
                return run if run and run.claimed_at is not None else None

        return await self.wait_for(claimed, deadline, "the runner to claim the run")

    async def wait_for_terminal_run(
        self, run_id: str, deadline: float = AGENT_DEADLINE
    ):
        async def done():
            async with self.maker() as session:
                run = await session.get(TaskRun, uuid.UUID(run_id))
                return run if run and run.finished_at is not None else None

        return await self.wait_for(done, deadline, "the run to finish")


def use_agent_script(body: str) -> None:
    """Point the stack's agent at a different script for the rest of this journey.

    `run-stack.sh` fixes `CLIORA_FAKECLI_SCRIPT` when the daemon starts, so the only way
    to change the agent's behaviour is to rewrite the file it names. One file, therefore
    one journey at a time — which is why the browser suite runs `--workers=1`.
    """
    path = os.environ.get("E2E_AGENT_SCRIPT")
    if not path:
        raise SystemExit(
            "E2E_AGENT_SCRIPT is unset — start the stack with E2E_RUNNER=1"
        )
    Path(path).write_text(body, encoding="utf-8")
    os.chmod(path, 0o755)
