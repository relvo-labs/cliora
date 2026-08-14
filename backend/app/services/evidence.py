"""Execution plans, verification reports and evidence (DV-06, ADR 0033 §3b).

Three tables, one module, and the reason they share one is that they answer one question
read three ways: the plan is what was going to happen, the report is what the checks
said, the evidence is what was observed.

**Four properties here are decisions, not implementation details.**

**`source` is decided by the write path and never by the payload.** The functions below
have no `source` parameter — the caller decides it by being the caller — so "an agent
claimed its report was machine-verified" is not a validation failure, it is
*unrepresentable*. That is a level stronger than checking the principal's type, because
a check has a second call site and a missing parameter does not.

**Discarding a claimed `source` writes an activity row.** Only ignoring it would make an
agent overstating its evidence and an agent with a typo leave identical traces, and those
two need different responses.

**`kind` decides `source` for evidence, never the other way round.** `_SOURCE_FOR_KIND`
binds them, so "an agent wrote a `git_state`" cannot become a row that looks like a
machine fact — it is refused before it is anything.

**Nothing here updates.** No function returns an updated row and the repository layer has
no `update()` against these tables. Append-only is their entire integrity property — they
are the grounds on which a card claims to be finished — and `GATE-DV-APPEND-ONLY` scans
for a violation because the property has no other trace in the code.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import EvidenceItem, ExecutionPlan, Project, Task, VerificationReport
from app.services.activity import (
    ACTOR_AGENT,
    ACTOR_USER,
    EXECUTION_PLAN_RECORDED,
    VERIFICATION_REPORTED,
    VERIFICATION_SOURCE_IGNORED,
    ActivityService,
)

# --- the three closed vocabularies -------------------------------------------

PLAN_STEP_STATUSES = frozenset({"pending", "in_progress", "completed", "skipped", "failed"})
REPORT_RESULTS = frozenset({"not_started", "running", "passed", "failed", "partial"})
CHECK_ORIGINS = frozenset({"project", "card"})

AGENT_REPORTED = "agent_reported"
PLATFORM_OBSERVED = "platform_observed"
MACHINE_VERIFIED = "machine_verified"

# `kind` decides `source`. One table rather than a rule, so the mapping has exactly one
# reading and an agent-written machine fact is not expressible (ADR 0033 §3b).
_SOURCE_FOR_KIND: dict[str, str] = {
    "git_state": MACHINE_VERIFIED,
    "changed_files": MACHINE_VERIFIED,
    "diff_stat": MACHINE_VERIFIED,
    "command_result": MACHINE_VERIFIED,
    "run_event": PLATFORM_OBSERVED,
    "delivery": PLATFORM_OBSERVED,
    "agent_finding": AGENT_REPORTED,
    "agent_limitation": AGENT_REPORTED,
    "agent_risk": AGENT_REPORTED,
}
# The three an agent may write. Everything else is written by the daemon (through the
# run's completion frame) or by Central itself.
AGENT_WRITABLE_KINDS = frozenset(
    {kind for kind, source in _SOURCE_FOR_KIND.items() if source == AGENT_REPORTED}
)

# Bounds in the service layer rather than the database: JSONB has no cheap length
# constraint, and here the refusal can point somewhere useful. Artifacts already have a
# quota, a retention period, a download path and a stored-XSS posture (ADR 0030 Part B);
# letting evidence grow into a file store would mean doing all four again.
MAX_EVIDENCE_PAYLOAD_BYTES = 16 * 1024
MAX_EVIDENCE_PER_RUN = 64


# --- assembling the two verification stores for one offer (ADR 0033 §3b) ---

# The wire form is `origin\tname\tcmd\targ…` inside `spec.allowed_verification_commands`,
# a field contract 1.11.0 already carries. **`spec` gains no new field**, and that is the
# point: the receiving decoder rejects unknown fields and answers nothing, so a new field
# would cost every un-upgraded node its offers (ADR 0029 amendment C).
_ORIGIN_CODES = {"project": "p", "card": "c"}

# Each element of that field is bounded at 256 characters by the contract, and the whole
# list at 16. Two stores of 8 fit exactly; the per-command bounds below are what keep one
# encoded command inside 256, and they are checked **when the command is saved** rather
# than when the offer is assembled — a command that stores fine and silently never ships
# would make "this project's verification never ran" a fact nobody goes looking for.
MAX_COMMANDS_PER_STORE = 8
MAX_COMMAND_NAME = 32
MAX_ARGV_ITEMS = 16
MAX_ARGV_ITEM = 128
MAX_ENCODED_COMMAND = 256


def encode_command(origin: str, command: dict[str, Any]) -> str:
    return "\t".join([_ORIGIN_CODES[origin], str(command["name"]), *command["argv"]])


def validate_commands(commands: list[dict[str, Any]], *, origin: str) -> list[dict[str, Any]]:
    """One validator for both stores.

    Two nearly identical validators drift the moment either is fixed, and the card store
    is the easier of the two to change — so it is held to exactly the project store's
    rules rather than to looser ones.
    """
    if len(commands) > MAX_COMMANDS_PER_STORE:
        raise ApiError(
            "VERIFICATION_COMMANDS_INVALID",
            f"最多 {MAX_COMMANDS_PER_STORE} 條驗證命令",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    cleaned: list[dict[str, Any]] = []
    for command in commands:
        name = str(command.get("name") or "").strip()
        argv = command.get("argv") or []
        if not name or len(name) > MAX_COMMAND_NAME:
            raise ApiError(
                "VERIFICATION_COMMANDS_INVALID",
                f"命令名稱必須是 1–{MAX_COMMAND_NAME} 個字元",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV_ITEMS:
            raise ApiError(
                "VERIFICATION_COMMANDS_INVALID",
                f"argv 必須是 1–{MAX_ARGV_ITEMS} 個元素",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"name": name},
            )
        for item in argv:
            if not isinstance(item, str) or not item or len(item) > MAX_ARGV_ITEM:
                raise ApiError(
                    "VERIFICATION_COMMANDS_INVALID",
                    f"argv 的每個元素必須是 1–{MAX_ARGV_ITEM} 個字元的字串",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"name": name},
                )
            if "\t" in item:
                # The encoding's separator. Refused rather than escaped: an escape needs
                # a decoder on the other side, and this is a value nobody legitimately
                # needs a tab in.
                raise ApiError(
                    "VERIFICATION_COMMANDS_INVALID",
                    "argv 不能含有 tab 字元",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"name": name},
                )
        entry = {"name": name, "argv": list(argv)}
        encoded = len(encode_command(origin, entry))
        if encoded > MAX_ENCODED_COMMAND:
            # Measured here, where a person can act on it — not at send time, where the
            # only symptom is a check that never runs (plan/20 D2's lesson, one layer up).
            raise ApiError(
                "VERIFICATION_COMMANDS_INVALID",
                f"「{name}」編碼後 {encoded} 字元，超過 {MAX_ENCODED_COMMAND} 的上限",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"name": name, "encoded": encoded},
            )
        cleaned.append(entry)
    return cleaned


def assemble_verification_commands(project: Project, task: Task) -> list[str]:
    """Both stores, project first.

    **The order is a priority declaration, not presentation.** If the group's timeout
    expires, what is cut is the tail — so the project's definition of "done" survives and
    the card's supplement is what gets dropped, rather than the other way round.
    """
    encoded: list[str] = []
    for command in (project.verification_commands or [])[:MAX_COMMANDS_PER_STORE]:
        encoded.append(encode_command("project", command))
    for command in (task.verification_commands or [])[:MAX_COMMANDS_PER_STORE]:
        encoded.append(encode_command("card", command))
    return encoded


class PlanService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._activity = ActivityService(session)

    async def list_for(self, task_id: uuid.UUID) -> list[ExecutionPlan]:
        return list(
            (
                await self._session.execute(
                    select(ExecutionPlan)
                    .where(ExecutionPlan.task_id == task_id)
                    .order_by(ExecutionPlan.seq.desc())
                )
            ).scalars()
        )

    async def record(
        self,
        *,
        task: Task,
        steps: list[dict[str, Any]],
        note: str | None,
        run_id: uuid.UUID | None,
        actor_kind: str,
        user_id: uuid.UUID | None,
        runner_id: uuid.UUID | None,
    ) -> ExecutionPlan:
        """Append a version. **There is no update path**, here or in the API.

        `note` is required from the second version onward: *why* the plan changed is the
        reason a version row exists at all rather than a mutable column. The rule is here
        rather than in a CHECK constraint because as a constraint the difference between
        a first plan and a revision arrives as an unreadable database error.
        """
        self._validate_steps(steps)
        for attempt in range(2):
            seq = await self._next_seq(task.id)
            if seq > 1 and not (note or "").strip():
                raise ApiError(
                    "PLAN_NOTE_REQUIRED",
                    "改寫執行計畫必須說明為什麼",
                    status.HTTP_400_BAD_REQUEST,
                )
            plan = ExecutionPlan(
                id=uuid.uuid4(),
                task_id=task.id,
                project_id=task.project_id,
                run_id=run_id,
                seq=seq,
                note=(note or "").strip() or None,
                steps=steps,
                created_by_kind=actor_kind,
                created_by=user_id,
                created_by_runner_id=runner_id,
            )
            self._session.add(plan)
            try:
                await self._session.flush()
            except IntegrityError:
                # Two writers took the same `seq`. **Retried once, not indefinitely**:
                # a second collision means something is writing at a rate this table is
                # not for, and an unbounded retry turns a data problem into a CPU one.
                await self._session.rollback()
                if attempt == 1:
                    raise ApiError(
                        "PLAN_SEQ_CONFLICT",
                        "另一個寫入者同時提交了執行計畫，請重試",
                        status.HTTP_409_CONFLICT,
                    ) from None
                continue
            await self._activity.record(
                EXECUTION_PLAN_RECORDED,
                project_id=task.project_id,
                task_id=task.id,
                actor_user_id=user_id,
                actor_kind=actor_kind,
                payload={"card_ref": task.card_ref, "seq": seq},
            )
            return plan
        raise AssertionError("unreachable")  # pragma: no cover

    def _validate_steps(self, steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if not isinstance(step, dict):
                raise ApiError(
                    "PLAN_STEPS_INVALID",
                    "Every step must be an object",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            state = step.get("status", "pending")
            if state not in PLAN_STEP_STATUSES:
                raise ApiError(
                    "PLAN_STEPS_INVALID",
                    f"Unknown step status: {state}",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"allowed": sorted(PLAN_STEP_STATUSES)},
                )

    async def _next_seq(self, task_id: uuid.UUID) -> int:
        current = (
            await self._session.execute(
                select(func.coalesce(func.max(ExecutionPlan.seq), 0)).where(
                    ExecutionPlan.task_id == task_id
                )
            )
        ).scalar() or 0
        return int(current) + 1


class VerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._activity = ActivityService(session)

    async def list_for(self, task_id: uuid.UUID) -> list[VerificationReport]:
        return list(
            (
                await self._session.execute(
                    select(VerificationReport)
                    .where(VerificationReport.task_id == task_id)
                    .order_by(VerificationReport.reported_at.desc())
                )
            ).scalars()
        )

    async def report_from_agent(
        self,
        *,
        task: Task,
        payload: dict[str, Any],
        run_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        runner_id: uuid.UUID | None,
    ) -> VerificationReport:
        """A submitted report. **Always `agent_reported`, whoever submitted it.**

        There is no parameter for `source`, so this function cannot be made to write
        another level by any caller. A payload that names one is discarded *and recorded*
        — without the record, an agent overstating its evidence and an agent with a typo
        are indistinguishable afterwards (ADR 0033 §3b, exit condition 19).
        """
        claimed = payload.get("source")
        if claimed is not None and claimed != AGENT_REPORTED:
            await self._activity.record(
                VERIFICATION_SOURCE_IGNORED,
                project_id=task.project_id,
                task_id=task.id,
                actor_user_id=user_id,
                actor_kind=ACTOR_AGENT if runner_id else ACTOR_USER,
                payload={
                    "card_ref": task.card_ref,
                    "claimed": str(claimed)[:64],
                    "stored": AGENT_REPORTED,
                },
            )
        return await self._write(
            task=task,
            payload=payload,
            source=AGENT_REPORTED,
            run_id=run_id,
            actor_kind=ACTOR_AGENT if runner_id else ACTOR_USER,
            user_id=user_id,
            runner_id=runner_id,
        )

    async def record_machine_verified(
        self,
        *,
        task: Task,
        run_id: uuid.UUID,
        checks: list[dict[str, Any]],
        summary: str | None,
        runner_id: uuid.UUID | None,
    ) -> VerificationReport:
        """The daemon's own checks, from `run.complete`.

        **The only writer of `machine_verified`**, and `GATE-DV-MACHINE-VERIFIED-ONE-WRITER`
        asserts there is no second one. Reaching here requires a valid node credential and
        a run that belongs to that node, which is what the level is worth.

        `origin` is stored as the daemon reported it rather than looked up: Central could
        look it up and would get a different answer if somebody edited either store
        mid-run, and a value travelling with its result cannot drift from the command that
        produced it.
        """
        normalised = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            origin = check.get("origin")
            normalised.append(
                {
                    "name": str(check.get("name") or "")[:128],
                    "origin": origin if origin in CHECK_ORIGINS else "project",
                    "exit_code": check.get("exit_code"),
                    "duration_ms": check.get("duration_ms"),
                    "output_tail": str(check.get("output_tail") or "")[:2000] or None,
                }
            )
        failed = any(entry["exit_code"] not in (0, None) for entry in normalised)
        return await self._write(
            task=task,
            payload={
                "result": "failed" if failed else "passed",
                "checks": normalised,
                "completion_summary": summary,
            },
            source=MACHINE_VERIFIED,
            run_id=run_id,
            actor_kind=ACTOR_AGENT,
            user_id=None,
            runner_id=runner_id,
        )

    async def _write(
        self,
        *,
        task: Task,
        payload: dict[str, Any],
        source: str,
        run_id: uuid.UUID | None,
        actor_kind: str,
        user_id: uuid.UUID | None,
        runner_id: uuid.UUID | None,
    ) -> VerificationReport:
        result = payload.get("result", "not_started")
        if result not in REPORT_RESULTS:
            raise ApiError(
                "VERIFICATION_REPORT_INVALID",
                f"Unknown verification result: {result}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"field": "result", "allowed": sorted(REPORT_RESULTS)},
            )
        for field in ("checks", "acceptance_criteria", "remaining_risks"):
            value = payload.get(field)
            if value is not None and not isinstance(value, list):
                raise ApiError(
                    "VERIFICATION_REPORT_INVALID",
                    f"{field} must be a list",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"field": field},
                )
        report = VerificationReport(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=task.project_id,
            run_id=run_id,
            result=result,
            checks=payload.get("checks") or [],
            acceptance_criteria=payload.get("acceptance_criteria") or [],
            remaining_risks=payload.get("remaining_risks") or [],
            completion_summary=payload.get("completion_summary"),
            source=source,
            reported_by_kind=actor_kind,
            reported_by=user_id,
            reported_by_runner_id=runner_id,
        )
        self._session.add(report)
        await self._session.flush()
        await self._activity.record(
            VERIFICATION_REPORTED,
            project_id=task.project_id,
            task_id=task.id,
            actor_user_id=user_id,
            actor_kind=actor_kind,
            payload={"card_ref": task.card_ref, "result": result, "source": source},
        )
        return report


class EvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for(self, task_id: uuid.UUID) -> list[EvidenceItem]:
        return list(
            (
                await self._session.execute(
                    select(EvidenceItem)
                    .where(EvidenceItem.task_id == task_id)
                    .order_by(EvidenceItem.collected_at.desc())
                )
            ).scalars()
        )

    async def add(
        self,
        *,
        task: Task,
        kind: str,
        payload: dict[str, Any],
        run_id: uuid.UUID | None,
        actor_kind: str,
        user_id: uuid.UUID | None,
        runner_id: uuid.UUID | None,
        agent_written: bool,
    ) -> EvidenceItem:
        """One observed fact. **`kind` decides `source`.**

        `agent_written` is not "who is calling" in the authorization sense — the route
        already answered that — it is which half of the table this caller may reach. An
        agent naming a machine kind is refused rather than downgraded, because a
        downgraded row still asserts something nobody observed.
        """
        source = _SOURCE_FOR_KIND.get(kind)
        if source is None:
            raise ApiError(
                "EVIDENCE_KIND_INVALID",
                f"Unknown evidence kind: {kind}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"allowed": sorted(_SOURCE_FOR_KIND)},
            )
        if agent_written and kind not in AGENT_WRITABLE_KINDS:
            raise ApiError(
                "EVIDENCE_KIND_NOT_WRITABLE",
                "這種證據只能由平台或節點寫入",
                status.HTTP_403_FORBIDDEN,
                details={"kind": kind, "allowed": sorted(AGENT_WRITABLE_KINDS)},
            )
        encoded = len(json.dumps(payload, ensure_ascii=False).encode())
        if encoded > MAX_EVIDENCE_PAYLOAD_BYTES:
            raise ApiError(
                "EVIDENCE_PAYLOAD_TOO_LARGE",
                "這件證據太大，請改附成卡片產物",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                details={"size": encoded, "limit": MAX_EVIDENCE_PAYLOAD_BYTES},
            )
        if run_id is not None:
            count = (
                await self._session.execute(
                    select(func.count())
                    .select_from(EvidenceItem)
                    .where(EvidenceItem.run_id == run_id)
                )
            ).scalar() or 0
            if int(count) >= MAX_EVIDENCE_PER_RUN:
                raise ApiError(
                    "EVIDENCE_RUN_LIMIT",
                    "這次執行的證據筆數已達上限",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    details={"count": int(count), "limit": MAX_EVIDENCE_PER_RUN},
                )
        item = EvidenceItem(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=task.project_id,
            run_id=run_id,
            kind=kind,
            source=source,
            written_by_kind=actor_kind,
            written_by=user_id,
            written_by_runner_id=runner_id,
            payload=payload,
        )
        self._session.add(item)
        await self._session.flush()
        return item
