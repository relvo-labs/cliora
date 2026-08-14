"""Opening the pull request, outside the receive loop (DV-05, ADR 0033 §3).

**The single most important thing in this module is where it is not.**
`RunService.finish()` records the intent and returns; this does the network call. That
separation is not tidiness:

> `run.complete` arrives on the node WebSocket, and that socket also carries interactive
> terminal bytes. A 20-second HTTP call inside that receive loop stops somebody's
> terminal for 20 seconds.

`services/runs.py` already documents the same rule for `registry.request()`, and
`GATE-DV-NO-HTTP-IN-LOOP` scans for a violation because the symptom — a terminal that
stutters when an unrelated card finishes — has no obvious connection to its cause.

**Four outcomes, and only two of them are failures.**

| what happened | state | run result |
|---|---|---|
| the pull request was opened | `delivered` | unchanged |
| one already existed for this head | `delivered` | unchanged |
| the provider refused, or could not be reached | `branch_only` | `delivered_branch_only` |
| there was nothing to open one on | not queued at all | unchanged |

"Already exists" is a success rather than an error: one pull request per branch is the
provider's rule, not our failure, and `existing_pr`'s second run lands there by design.

**None of the four fails the run.** The branch is pushed and the work exists; a person
can open the pull request by hand, and the card is not blocked for lacking one
(`done_gate.py` reads `branch_only` as satisfied delivery evidence).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectRepository, Task, TaskRun
from app.services import audit as audit_actions
from app.services.audit import AuditService
from app.services.providers import (
    MAX_BODY_BYTES,
    ProviderError,
    PullRequestRef,
    adapter_for,
)
from app.settings import Settings, get_settings

PENDING = "pending_pr"
DELIVERED = "delivered"
BRANCH_ONLY = "branch_only"

# The result Central writes when the branch is there and the pull request is not.
#
# **Not a `run.complete` value**, and that is deliberate: the daemon never learns whether
# a pull request was opened, so putting this on the wire would create a branch on the
# node that can never be taken (ADR 0033 §3).
DELIVERED_BRANCH_ONLY = "delivered_branch_only"

# Delivery modes that want a pull request. `branch` deliberately does not: it says "push
# it and stop", and a card that wanted more would have said so.
PR_DELIVERIES = frozenset({"pull_request", "existing_pr"})


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    run_id: uuid.UUID
    state: str
    ref: str | None = None
    reason: str | None = None


class DeliveryService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    # --- the queue -----------------------------------------------------------

    def wants_pull_request(self, task: Task, pushed_branch: str | None) -> bool:
        """Whether this finished run has something to open a pull request on.

        Both halves matter. The card has to have asked, **and the branch has to really
        exist** — `pushed_branch` is the daemon's report rather than Central's
        composition, so a run whose push failed is never queued and the provider is
        never asked to open a pull request against a branch that is not there.
        """
        return bool(task.delivery in PR_DELIVERIES and pushed_branch)

    async def pending_count(self) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.delivery_state == PENDING)
                )
            ).scalar()
            or 0
        )

    async def claim_batch(self, limit: int) -> list[TaskRun]:
        return list(
            (
                await self._session.execute(
                    select(TaskRun)
                    .where(TaskRun.delivery_state == PENDING)
                    .order_by(TaskRun.finished_at)
                    .limit(limit)
                )
            ).scalars()
        )

    # --- one delivery --------------------------------------------------------

    async def deliver(self, run: TaskRun) -> DeliveryOutcome:
        """Open the pull request for one run, or record why not.

        Never raises for a provider problem: a refusal is a **result** here. Raising
        would leave the row in `pending_pr` and the worker would try it again on the
        next tick — which is a retry, and creation is not idempotent.
        """
        task = await self._session.get(Task, run.task_id)
        project = await self._session.get(Project, run.project_id)
        if task is None or project is None:  # pragma: no cover - FKs make this unreachable
            return await self._settle(run, BRANCH_ONLY, reason="the card is gone")

        repository = (
            await self._session.get(ProjectRepository, run.repository_id)
            if run.repository_id
            else None
        )
        if repository is None:
            return await self._settle(run, BRANCH_ONLY, reason="this project has no repository")

        adapter = adapter_for(repository.host, self._settings)
        if adapter is None:
            # Dispatch already refuses an unsupported host, so reaching here means the
            # repository changed after the run started.
            return await self._settle(
                run, BRANCH_ONLY, reason=f"{repository.host} has no provider adapter"
            )

        token = await self._provider_token(project, repository)
        if token is None:
            return await self._settle(
                run, BRANCH_ONLY, reason="this repository has no provider credential"
            )

        head = run.pushed_branch or ""
        base = task.target_branch or repository.default_branch
        try:
            existing = await adapter.find_pull_request(
                repo_path=repository.path, head=head, token=token
            )
            if existing is not None:
                # **A success, not a failure.** One pull request per branch is the
                # provider's rule; `existing_pr`'s second run lands here by design, and
                # so does a retried delivery.
                if task.delivery == "existing_pr":
                    await adapter.comment_on_pull_request(
                        repo_path=repository.path,
                        number=existing.number,
                        body=self._append_note(run),
                        token=token,
                    )
                return await self._settle(run, DELIVERED, ref=existing.url)

            opened: PullRequestRef = await adapter.create_pull_request(
                repo_path=repository.path,
                head=head,
                base=base,
                title=self._title(task),
                body=await self._body(task, run, project),
                token=token,
            )
        except ProviderError as exc:
            return await self._settle(run, BRANCH_ONLY, reason=exc.message)

        await AuditService(self._session).record(
            audit_actions.PR_CREATE,
            user_id=run.created_by,
            metadata={
                # Repo, number, head and base — and **never the token, nor its length**.
                "repository": f"{repository.host}{repository.path}",
                "number": opened.number,
                "head": head,
                "base": base,
                "run_id": str(run.id),
            },
        )
        return await self._settle(run, DELIVERED, ref=opened.url)

    async def _settle(
        self, run: TaskRun, state: str, *, ref: str | None = None, reason: str | None = None
    ) -> DeliveryOutcome:
        run.delivery_state = state
        if ref:
            run.delivery_ref = ref
        if state == BRANCH_ONLY:
            # The run itself stays succeeded: the branch is pushed and the work exists.
            # Only the *result* changes, because "what happened" and "what came of it"
            # are different columns.
            run.result = DELIVERED_BRANCH_ONLY
        await self._session.flush()
        return DeliveryOutcome(run_id=run.id, state=state, ref=ref, reason=reason)

    async def _provider_token(self, project: Project, repository: ProjectRepository) -> str | None:
        """The credential, decrypted **here** rather than at the claim.

        ADR 0032's `Consequences` says a project secret is decrypted inside the node
        receive loop, and that is still true of the secrets a run receives — AES-GCM is
        CPU-bound and awaits nothing. This one is different because a network call
        follows it, so it is decrypted in the worker instead. Both are true; they are
        different paths, and the amendment says so because "secrets are decrypted at the
        claim" otherwise reads as a description of the whole system.
        """
        if repository.provider_token_secret_id is None:
            return None
        from app.services.secrets import SecretService

        return await SecretService(self._session, settings=self._settings).provider_token(
            project.id, repository.provider_token_secret_id
        )

    # --- what the pull request says -----------------------------------------

    def _title(self, task: Task) -> str:
        return f"[{task.card_ref}] {task.title}"[:256]

    def _append_note(self, run: TaskRun) -> str:
        return (
            f"Cliora appended commits from run #{run.seq} on `{run.pushed_branch}`.\n\n"
            f"{run.summary or ''}"
        ).strip()[:MAX_BODY_BYTES]

    async def _body(self, task: Task, run: TaskRun, project: Project) -> str:
        """The body **the platform** produces, not the agent.

        The people reading it do not have Cliora accounts, so what they read has to be
        something the platform can stand behind. Three rules shape it: every check names
        its `source` **and** its `origin` — after "a machine ran it" the next question is
        "who set the standard" — failures are listed first and are never collapsed, and
        the last line discloses that the author of this pull request is the credential's
        owner rather than the person who dispatched the card.
        """
        from app.services.evidence import VerificationService

        lines = [f"## 目標\n\n{task.objective or task.title}\n"]

        criteria = task.acceptance_criteria or []
        if criteria:
            lines.append("## 驗收標準\n")
            for item in criteria:
                result = item.get("result", "not_verified")
                lines.append(f"- [{result}] {item.get('text', '')}")
            lines.append("")

        reports = await VerificationService(self._session).list_for(task.id)
        report = reports[0] if reports else None
        if report is not None and report.checks:
            lines.append("## 驗證\n")
            lines.append("| 檢查 | 結果 | 來源 | 由誰指定 |")
            lines.append("|---|---|---|---|")
            # Failures first, and never folded away.
            checks = sorted(report.checks, key=lambda c: 0 if c.get("exit_code") else 1)
            for check in checks:
                origin = "專案設定" if check.get("origin") == "project" else "這張卡"
                lines.append(
                    f"| {check.get('name')} | exit {check.get('exit_code')} | 機器事實 | {origin} |"
                )
            lines.append("")
        if report is not None and report.remaining_risks:
            lines.append("## 殘留風險\n")
            for risk in report.remaining_risks:
                lines.append(f"- {risk.get('text') or risk.get('check')}")
            lines.append("")

        lines.append("## 執行\n")
        lines.append(f"- Run: `{run.id}` (seq {run.seq})")
        if run.commit_sha:
            lines.append(f"- Commit: `{run.commit_sha}`")
        lines.append("- 本 PR 由 Cliora 代為建立；作者欄顯示的是憑證的擁有者，不是按下派工鍵的人。")
        body = "\n".join(lines)
        if len(body.encode()) > MAX_BODY_BYTES:
            body = body.encode()[: MAX_BODY_BYTES - 200].decode(errors="ignore")
            body += "\n\n…（內容過長已截斷，完整內容在 run 詳情）"
        return body
