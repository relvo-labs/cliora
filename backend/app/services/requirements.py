"""Intake, specification versions and task proposals — the manual flow (TK-05).

`version2.md` §17 asks for this order explicitly: **build the data structures and the
human flow first, then let an agent use the same API.** So V2.1 delivers the tables
and the forms, and V2.5 points an agent at exactly these endpoints. If nobody uses the
manual flow, nobody will use the agent one either — which makes the usage of these
five endpoints the cheapest early signal V2.5 could ask for (D28 §4, M14).

Three refusals live here, and all three are **API-level**, not disabled buttons:

1. a specification with an unresolved open question cannot be approved, and the
   refusal names the questions;
2. an unapproved requirement cannot be decomposed;
3. an accepted proposal whose card is missing readiness items lands in `backlog`
   rather than in `ready`, and says which items were missing.

The third is the Definition of Ready finally biting something. It bites here rather
than on the board because this is the one moment where a card is created *by a
decision* rather than by a person typing it — and a decision is exactly what can be
made with a rule attached (D28).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import FeatureSpec, Project, Requirement, Task, TaskProposal
from app.repositories.tasks import TaskRepository
from app.services import audit as audit_actions
from app.services.activity import (
    PROPOSAL_ACCEPTED,
    REQUIREMENT_APPROVED,
    REQUIREMENT_CREATED,
    REQUIREMENT_SPEC_ADDED,
    ActivityService,
)
from app.services.audit import AuditService
from app.services.process import ProcessService
from app.services.tasks import TaskService

INTAKE = "intake"
CLARIFYING = "clarifying"
SPECIFIED = "specified"
APPROVED = "approved"
REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AcceptResult:
    created: list[Task]
    # Per created card: which readiness items it lacked. Carried out to the caller so
    # the console can say why a card landed in `backlog`, rather than leaving the user
    # to compare two screens.
    incomplete: dict[str, list[str]]


def _open_questions(spec: FeatureSpec) -> list[dict[str, Any]]:
    """Unresolved questions on a spec version.

    "Resolved" means an answer *or* an explicit `resolved_as` — the second is how a
    known unknown gets recorded without pretending it was answered (D28 §3).
    """
    return [
        question
        for question in (spec.open_questions or [])
        if not question.get("answer") and not question.get("resolved_as")
    ]


class RequirementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService(session)
        self._activity = ActivityService(session)
        self._tasks = TaskService(session)
        self._repo = TaskRepository(session)
        self._process = ProcessService(session)

    # --- reads ------------------------------------------------------------------

    async def require(self, requirement_id: uuid.UUID) -> Requirement:
        row = await self._session.get(Requirement, requirement_id)
        if row is None:
            raise ApiError(
                "REQUIREMENT_NOT_FOUND", "Requirement not found", status.HTTP_404_NOT_FOUND
            )
        return row

    async def listing(self, project_id: uuid.UUID) -> list[Requirement]:
        rows = (
            await self._session.execute(
                select(Requirement)
                .where(Requirement.project_id == project_id)
                .order_by(Requirement.created_at.desc())
            )
        ).scalars()
        return list(rows)

    async def specs(self, requirement_id: uuid.UUID) -> list[FeatureSpec]:
        rows = (
            await self._session.execute(
                select(FeatureSpec)
                .where(FeatureSpec.requirement_id == requirement_id)
                .order_by(FeatureSpec.seq)
            )
        ).scalars()
        return list(rows)

    async def latest_spec(self, requirement_id: uuid.UUID) -> FeatureSpec | None:
        return (
            await self._session.execute(
                select(FeatureSpec)
                .where(FeatureSpec.requirement_id == requirement_id)
                .order_by(FeatureSpec.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def proposals(self, requirement_id: uuid.UUID) -> list[TaskProposal]:
        rows = (
            await self._session.execute(
                select(TaskProposal)
                .where(TaskProposal.requirement_id == requirement_id)
                .order_by(TaskProposal.seq)
            )
        ).scalars()
        return list(rows)

    async def require_proposal(self, proposal_id: uuid.UUID) -> TaskProposal:
        row = await self._session.get(TaskProposal, proposal_id)
        if row is None:
            raise ApiError("PROPOSAL_NOT_FOUND", "Proposal not found", status.HTTP_404_NOT_FOUND)
        return row

    # --- writes -----------------------------------------------------------------

    async def create(self, *, project: Project, actor_id: uuid.UUID, raw_text: str) -> Requirement:
        """Intake: one sentence, nothing else required.

        Deliberately not a form. The flow starts with someone saying what they want in
        their own words, and ten mandatory fields at that moment is how the flow stops
        being used at all.
        """
        if project.status == "archived":
            raise ApiError("PROJECT_ARCHIVED", "This project is archived", status.HTTP_409_CONFLICT)
        card_ref = await self._repo.allocate_card_ref(project.id, "REQ")
        requirement = Requirement(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=card_ref,
            raw_text=raw_text,
            status=INTAKE,
            created_by=actor_id,
        )
        self._session.add(requirement)
        await self._session.flush()
        await self._audit.record(
            audit_actions.REQUIREMENT_CREATE,
            user_id=actor_id,
            metadata={"card_ref": card_ref, "project_id": str(project.id)},
        )
        await self._activity.record(
            REQUIREMENT_CREATED,
            project_id=project.id,
            actor_user_id=actor_id,
            payload={"card_ref": card_ref},
        )
        return requirement

    async def add_spec(
        self,
        *,
        requirement: Requirement,
        actor_id: uuid.UUID,
        fields: dict[str, Any],
        authored_by_kind: str = "user",
    ) -> FeatureSpec:
        """Append a specification version. Never an update.

        The review screen compares version N with N-1, and a specification that was
        quietly edited is the thing most worth being able to see later.
        """
        if requirement.status == APPROVED:
            raise ApiError(
                "REQUIREMENT_ALREADY_APPROVED",
                "This requirement is approved; a new version needs a new requirement",
                status.HTTP_409_CONFLICT,
            )
        next_seq = int(
            await self._session.scalar(
                select(func.coalesce(func.max(FeatureSpec.seq), 0) + 1).where(
                    FeatureSpec.requirement_id == requirement.id
                )
            )
            or 1
        )
        spec = FeatureSpec(
            id=uuid.uuid4(),
            requirement_id=requirement.id,
            seq=next_seq,
            objective=fields.get("objective"),
            scope=fields.get("scope"),
            non_goals=fields.get("non_goals"),
            acceptance_criteria=fields.get("acceptance_criteria") or [],
            open_questions=fields.get("open_questions") or [],
            authored_by_kind=authored_by_kind,
            authored_by=actor_id,
        )
        self._session.add(spec)
        requirement.status = SPECIFIED if not _open_questions(spec) else CLARIFYING
        await self._session.flush()
        await self._activity.record(
            REQUIREMENT_SPEC_ADDED,
            project_id=requirement.project_id,
            actor_user_id=actor_id,
            payload={"card_ref": requirement.card_ref, "seq": next_seq},
        )
        return spec

    async def approve(self, *, requirement: Requirement, actor_id: uuid.UUID) -> Requirement:
        """The first of D28's three human gates.

        Refused at the API, not by a disabled button: V2.5 sends an agent down this
        same path, and a UI-only rule would not be there when it did.
        """
        spec = await self.latest_spec(requirement.id)
        if spec is None:
            raise ApiError(
                "REQUIREMENT_NOT_SPECIFIED",
                "Write a specification before approving",
                status.HTTP_409_CONFLICT,
            )
        unresolved = _open_questions(spec)
        if unresolved:
            raise ApiError(
                "SPEC_HAS_OPEN_QUESTIONS",
                "Unresolved questions remain",
                status.HTTP_409_CONFLICT,
                details={
                    "questions": [
                        question.get("question", question.get("id", "?")) for question in unresolved
                    ]
                },
            )
        requirement.status = APPROVED
        requirement.approved_by = actor_id
        requirement.approved_at = now_utc()
        await self._session.flush()
        await self._audit.record(
            audit_actions.REQUIREMENT_APPROVE,
            user_id=actor_id,
            metadata={"card_ref": requirement.card_ref, "spec_seq": spec.seq},
        )
        await self._activity.record(
            REQUIREMENT_APPROVED,
            project_id=requirement.project_id,
            actor_user_id=actor_id,
            payload={"card_ref": requirement.card_ref, "spec_seq": spec.seq},
        )
        return requirement

    async def propose(
        self, *, requirement: Requirement, actor_id: uuid.UUID, tree: dict[str, Any]
    ) -> TaskProposal:
        """Record a decomposition. Proposals are not cards.

        The refusal below is D28's second gate: an unapproved specification cannot be
        decomposed, because a decomposition of something nobody has agreed to is work
        that will be thrown away.
        """
        if requirement.status != APPROVED:
            raise ApiError(
                "REQUIREMENT_NOT_APPROVED",
                "Approve the specification before decomposing it",
                status.HTTP_409_CONFLICT,
            )
        spec = await self.latest_spec(requirement.id)
        next_seq = int(
            await self._session.scalar(
                select(func.coalesce(func.max(TaskProposal.seq), 0) + 1).where(
                    TaskProposal.requirement_id == requirement.id
                )
            )
            or 1
        )
        proposal = TaskProposal(
            id=uuid.uuid4(),
            requirement_id=requirement.id,
            spec_id=spec.id if spec else None,
            seq=next_seq,
            tree=tree,
            status="pending",
        )
        self._session.add(proposal)
        await self._session.flush()
        return proposal

    async def accept(
        self,
        *,
        project: Project,
        requirement: Requirement,
        proposal: TaskProposal,
        actor_id: uuid.UUID,
        accept_ids: list[str] | None,
        note: str | None,
    ) -> AcceptResult:
        """Turn accepted proposal cards into real ones.

        Partial acceptance is the normal case, so `accept_ids` selects; `None` means
        all of them. Whatever is not accepted stays on the proposal with its reason,
        because "we decided not to do that" is a fact worth keeping.

        **A card missing readiness items lands in `backlog`, never in `ready`.** That
        is the Definition of Ready's one hard consequence in V2.1 — and it applies
        here rather than on the board because this is where a card is created by a
        decision instead of by someone typing it (D28).
        """
        if proposal.status in ("accepted", "rejected"):
            raise ApiError(
                "PROPOSAL_ALREADY_DECIDED",
                "This proposal was already decided",
                status.HTTP_409_CONFLICT,
            )
        process = await self._process.effective()
        required_readiness = process.readiness_keys()
        items = list((proposal.tree or {}).get("tasks", []))
        # What this proposal has already produced. Partial acceptance leaves the rest
        # *available* rather than declined (research/02/10 §2.7 condition 5), so a
        # second acceptance is legitimate — and has to be idempotent per item, or the
        # same card is created twice. The link back to the proposal item is stored on
        # the card because that is the only place the pairing survives.
        already = {
            str((task.links or {}).get("proposal_item_id"))
            for task in (
                await self._session.execute(select(Task).where(Task.proposal_id == proposal.id))
            ).scalars()
        }
        chosen = [
            item
            for item in items
            if (accept_ids is None or str(item.get("id", "")) in set(accept_ids))
            and str(item.get("id", "")) not in already
        ]
        created: list[Task] = []
        incomplete: dict[str, list[str]] = {}
        for item in chosen:
            readiness = item.get("readiness") or {}
            missing = [key for key in required_readiness if not readiness.get(key)]
            result = await self._tasks.create_task(
                project=project,
                actor_id=actor_id,
                fields={
                    "title": item.get("title", "untitled"),
                    "description": item.get("description"),
                    "objective": item.get("objective"),
                    "scope": item.get("scope"),
                    "non_goals": item.get("non_goals"),
                    # The rule, in one expression.
                    "stage": "backlog" if missing else item.get("stage", "ready"),
                    "risk": item.get("risk", "medium"),
                    "priority": item.get("priority", "normal"),
                    "acceptance_criteria": item.get("acceptance_criteria") or [],
                    "readiness": readiness,
                    "links": {
                        **(item.get("links") or {}),
                        "proposal_item_id": str(item.get("id", "")),
                    },
                    "required_labels": item.get("required_labels") or [],
                    "source": item.get("source", "repo"),
                    "delivery": item.get("delivery", "pull_request"),
                    "base_branch": item.get("base_branch"),
                    "target_branch": item.get("target_branch"),
                    "epic_id": None,
                    "user_story_id": None,
                },
            )
            task = result.task
            # Provenance: the detail page says "from requirement #N, proposal #M".
            task.requirement_id = requirement.id
            task.proposal_id = proposal.id
            created.append(task)
            if missing:
                incomplete[task.card_ref] = missing

        produced = already | {str(item.get("id", "")) for item in chosen}
        proposal.status = (
            "accepted"
            if produced >= {str(item.get("id", "")) for item in items}
            else "partially_accepted"
        )
        proposal.decided_by = actor_id
        proposal.decided_at = now_utc()
        proposal.decision_note = note
        await self._session.flush()
        await self._audit.record(
            audit_actions.PROPOSAL_ACCEPT,
            user_id=actor_id,
            metadata={
                "card_ref": requirement.card_ref,
                "proposal_seq": proposal.seq,
                "created": [task.card_ref for task in created],
            },
        )
        await self._activity.record(
            PROPOSAL_ACCEPTED,
            project_id=project.id,
            actor_user_id=actor_id,
            payload={
                "card_ref": requirement.card_ref,
                "created": [task.card_ref for task in created],
            },
        )
        return AcceptResult(created=created, incomplete=incomplete)
