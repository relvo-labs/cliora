"""The six conditions a card meets to enter `done`, and the one exit around them (DV-07).

This is the board's **second** hard refusal. ADR 0028 said there was exactly one — a
card may not enter `ready` or beyond with an unfinished dependency — and the narrowness
was the design, because a board that refuses everything stops being written to. So the
second one needs its own justification rather than an appeal to the first:

> The dependency rule refuses a card **entering work**, which is a judgement the
> platform can be wrong about. The Done Gate refuses a card **claiming to be
> finished**, and there the platform holds every fact involved.

Four properties of this module are decisions rather than implementation details.

**There is one entrance.** `TaskService.update()` is the only caller, because it is the
only thing that assigns `task.stage`. A run does **not** move a card — `finish()` never
touches the column and `GATE-DV-SINGLE-DONE-PATH` scans for an assignment there. Without
that scan somebody eventually adds a helpful "advance the card when the run succeeds",
and the gate is bypassed by a door nobody thinks to check.

**Every refusal names every missing item.** Not the first one: the actions a person
takes for a missing summary and a missing report are different, and one message would
send half the readers to the wrong page (the same call `services/runs.py` made for its
two secret refusals).

**"Handled" means somebody said they accept it, not that it was fixed.** A failing check
listed in `remaining_risks` is handled. Defining it as "fixed" would block every card
behind a known environment problem, and people would route around the gate — which is
the outcome this gate exists to prevent.

**The gate applies only where the evidence it asks for can exist.** All six conditions
are about artefacts the agent-runner layer produces — runs, reports, pushed branches —
so the gate is bound to `CLIORA_AGENT_RUNS_ENABLED`, exactly as PRD §8.15 says of every
capability in that section. A board-only deployment has no runs, therefore no reports,
therefore no card that could ever reach `done`: applying the gate there would not be
strictness, it would be breaking V2.1 for people who never asked for V2.2.

⚠️ `plan/21/08-…md` §6 anticipated this for condition ⑥ alone. That was too narrow —
conditions ①–④ fail on a board-only deployment for the same reason — and an existing
V2.1 test caught it (`test_finishing_the_blockers_unblocks_the_card`).

**The gate is not configurable.** `process_overrides` can disable readiness items and
review gates; the six conditions here are module constants and are deliberately absent
from `process_definitions`. Otherwise the first person who finds the gate inconvenient
turns it off, and turning it off leaves no trace, while `--force` leaves three.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Task, TaskArtifact, TaskRun, VerificationReport
from app.settings import Settings, get_settings

# The four values a criterion's result may hold, closed by migration 0036. Before that
# it was a free string, so "every criterion has a result" would have passed on any text
# at all — the check and the closure are one change, not two (ADR 0033 §5).
CRITERION_RESULTS = frozenset({"passed", "failed", "partial", "not_verified"})
UNVERIFIED = "not_verified"

# Report results that mean a report exists in a usable sense. `not_started` is a
# placeholder a run writes before it has anything to say.
_REPORT_INCOMPLETE = frozenset({"not_started"})

# Run results that carry the "there was nothing to deliver" conclusion. Honesty rule 2
# says an empty diff produces no pull request; this is the other half of that sentence —
# a card must not then be blocked for lacking one (ADR 0033 §2).
_NO_CHANGE_RESULTS = frozenset({"no_changes"})


@dataclass(frozen=True, slots=True)
class MissingItem:
    """One unmet condition, with a sentence a person can act on."""

    key: str
    text: str


@dataclass(frozen=True, slots=True)
class GateResult:
    missing: tuple[MissingItem, ...]

    @property
    def satisfied(self) -> bool:
        return not self.missing


class DoneGateService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    @property
    def applies(self) -> bool:
        """Whether this deployment has the layer that produces the evidence."""
        return bool(self._settings.agent_runs_enabled)

    async def evaluate(self, task: Task, project: Project | None = None) -> GateResult:
        """The six conditions, in the order the console lists them.

        Dependencies are **not** re-checked here: `TaskService._check_dependencies_for`
        already refuses them for every gated lane, and duplicating it would produce two
        error codes for one situation.
        """
        if not self.applies:
            return GateResult(())
        missing: list[MissingItem] = []
        latest_run = await self._latest_finished_run(task.id)
        report = await self._latest_report(task.id)

        # ① a completion summary — from the report if it carries one, otherwise from
        # the last run's own summary. Two sources because a `source: none` card may
        # never run at all, and a person writing the report by hand is a supported path.
        summary = (report.completion_summary if report else None) or (
            latest_run.summary if latest_run else None
        )
        if not (summary or "").strip():
            missing.append(MissingItem("completion_summary", "缺完成摘要"))

        # ② every acceptance criterion has a result
        unverified = [
            str(item.get("text") or "(未命名)")
            for item in (task.acceptance_criteria or [])
            if isinstance(item, dict) and item.get("result", UNVERIFIED) == UNVERIFIED
        ]
        if unverified:
            missing.append(
                MissingItem(
                    "acceptance_criteria",
                    "這幾項驗收標準還沒有結果：" + "、".join(unverified),
                )
            )

        # ③ a verification report exists
        if report is None or report.result in _REPORT_INCOMPLETE:
            missing.append(MissingItem("verification_report", "缺驗證報告"))

        # ④ no unhandled critical failure
        if report is not None:
            accepted = {
                str(risk.get("check") or risk.get("text") or "").strip()
                for risk in (report.remaining_risks or [])
                if isinstance(risk, dict)
            }
            unhandled = [
                f"{check.get('name')}（{check.get('origin', 'project')}）"
                for check in (report.checks or [])
                if isinstance(check, dict)
                and check.get("exit_code") not in (0, None)
                and str(check.get("name") or "").strip() not in accepted
            ]
            if unhandled:
                missing.append(
                    MissingItem(
                        "critical_failure",
                        "這幾項檢查失敗且未被列為殘留風險：" + "、".join(unhandled),
                    )
                )

        # ④b the project's optional requirement, off by default
        if project is not None and project.require_project_verification:
            ran_project_check = report is not None and any(
                isinstance(check, dict) and check.get("origin") == "project"
                for check in (report.checks or [])
            )
            if not ran_project_check:
                missing.append(
                    MissingItem(
                        "project_verification",
                        "這個專案要求至少通過一條專案層級的驗證，而這張卡只跑了卡片宣告的檢查",
                    )
                )

        # ⑥ the delivery evidence this card's mode implies (⑤ is dependencies, above)
        gap = await self._delivery_gap(task, latest_run)
        if gap is not None:
            missing.append(MissingItem("delivery", gap))

        return GateResult(tuple(missing))

    async def _delivery_gap(self, task: Task, run: TaskRun | None) -> str | None:
        """One branch per `delivery` value. `GATE-DV-DELIVERY-COVERAGE` reads this.

        A missing branch is not a missing feature but a silent one: the value falls
        through to "no evidence required" and the card walks into `done` unchecked.

        **A card that was never dispatched has no delivery to evidence.** `delivery`
        describes how *an agent run* hands its result back, and `tasks.delivery` defaults
        to `pull_request` — so without this, every hand-managed card on the board would
        need a pull request it was never going to have. The card is still held to the
        other conditions; it is condition ⑥ that has nothing to ask about.

        ⚠️ Found by an existing V2.1 test rather than by the plan, which anticipated the
        board-only *deployment* but not the never-dispatched *card* inside a deployment
        that does use runs.
        """
        if run is None:
            return None
        delivery = task.delivery
        if delivery == "none":
            return None
        if delivery == "artifact":
            count = await self._artifact_count(task.id)
            return None if count else "這張卡宣告以產物交付，但一件產物都沒有"
        if delivery == "branch":
            return None if run.pushed_branch else "沒有已推送的分支"
        if delivery == "pull_request":
            if run.delivery_ref:
                return None
            # A pull request that could not be created is not the card's fault: the
            # branch is pushed and the work exists. The console says so beside the card
            # rather than blocking it (ADR 0033 §2, honesty rule 2's other half).
            if run.delivery_state == "branch_only":
                return None
            if run.result in _NO_CHANGE_RESULTS:
                return None
            return "沒有 PR 連結，也沒有「無變更」的結論"
        if delivery == "existing_pr":
            return None if run.pushed_branch else "沒有追加的 commit"
        # Unreachable while `DELIVERIES` is closed, and deliberately loud rather than
        # permissive: a new mode with no branch here must fail visibly at review time.
        return f"未知的交付方式 '{delivery}'，無法判斷完成證據"

    async def _artifact_count(self, task_id: uuid.UUID) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(TaskArtifact)
                    .where(TaskArtifact.task_id == task_id, TaskArtifact.deleted_at.is_(None))
                )
            ).scalar()
            or 0
        )

    async def _latest_finished_run(self, task_id: uuid.UUID) -> TaskRun | None:
        return (
            await self._session.execute(
                select(TaskRun)
                .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_not(None))
                .order_by(TaskRun.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _latest_report(self, task_id: uuid.UUID) -> VerificationReport | None:
        return (
            await self._session.execute(
                select(VerificationReport)
                .where(VerificationReport.task_id == task_id)
                .order_by(VerificationReport.reported_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
