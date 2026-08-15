"""Intake, specification review and proposal acceptance (TK-05, D28).

Seven endpoints, and the three that refuse are the point of the ticket:
`open_questions` blocks approval, an unapproved requirement cannot be decomposed, and
an accepted card missing readiness items lands in `backlog`. All three live in the
service so that V2.5's agent — which will call exactly these routes — meets the same
rules a person does.

`task.approve` guards approval and acceptance rather than `task.update`: both are
decisions, and a decision is what a session credential's scope is written to exclude.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import require_action, require_projects_enabled
from app.api.http.schemas import (
    AcceptProposalRequest,
    AcceptProposalResultDTO,
    CreateProposalRequest,
    CreateRequirementRequest,
    CreateSpecRequest,
    FeatureSpecDTO,
    RejectProposalRequest,
    RequirementDetailDTO,
    RequirementSummaryDTO,
    TaskProposalDTO,
)
from app.api.http.tasks import _task_dto
from app.db.engine import get_session
from app.db.models import FeatureSpec, Requirement, TaskProposal, User
from app.services.projects import ProjectService
from app.services.rbac import PROJECT_VIEW, TASK_APPROVE, TASK_CREATE, TASK_UPDATE
from app.services.requirements import RequirementService, _open_questions
from app.services.tasks import TaskService
from app.settings import Settings, get_settings

router = APIRouter(
    prefix="/api", tags=["requirements"], dependencies=[Depends(require_projects_enabled)]
)


def _service(session: AsyncSession) -> RequirementService:
    return RequirementService(session)


def _spec_dto(spec: FeatureSpec) -> FeatureSpecDTO:
    return FeatureSpecDTO(
        id=spec.id,
        seq=spec.seq,
        objective=spec.objective,
        scope=spec.scope,
        non_goals=spec.non_goals,
        acceptance_criteria=spec.acceptance_criteria or [],
        open_questions=spec.open_questions or [],
        sections=spec.sections or {},
        authored_by_kind=spec.authored_by_kind,
        authored_by=spec.authored_by,
        run_id=spec.run_id,
        created_at=spec.created_at,
    )


def _proposal_dto(proposal: TaskProposal, accepted: set[str] | None = None) -> TaskProposalDTO:
    """`accepted` is passed in rather than looked up here, so the caller decides how
    many queries a list of proposals costs."""
    produced = accepted or set()
    all_ids = [str(item.get("id", "")) for item in (proposal.tree or {}).get("tasks", [])]
    return TaskProposalDTO(
        id=proposal.id,
        seq=proposal.seq,
        spec_id=proposal.spec_id,
        tree=proposal.tree or {},
        status=proposal.status,
        decided_by=proposal.decided_by,
        decided_at=proposal.decided_at,
        decision_note=proposal.decision_note,
        run_id=proposal.run_id,
        created_at=proposal.created_at,
        accepted_item_ids=sorted(item for item in all_ids if item in produced),
        remaining_item_ids=[item for item in all_ids if item not in produced],
    )


async def _refreshed(session: AsyncSession, row: object) -> None:
    """Reload a row before serialising it.

    `requirements.updated_at` carries `onupdate=func.now()`, so any flush that touched
    the row leaves that column expired — and reading an expired column is a SELECT,
    which asyncpg cannot issue from inside a plain attribute access. The task routes
    solve this the same way (`services/tasks.py::refresh`).
    """
    await session.refresh(row)


def _summary_dto(requirement: Requirement, spec_count: int) -> RequirementSummaryDTO:
    return RequirementSummaryDTO(
        id=requirement.id,
        project_id=requirement.project_id,
        card_ref=requirement.card_ref,
        raw_text=requirement.raw_text,
        status=requirement.status,
        created_by=requirement.created_by,
        approved_by=requirement.approved_by,
        approved_at=requirement.approved_at,
        spec_count=spec_count,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


@router.post(
    "/projects/{project_id}/requirements", response_model=RequirementSummaryDTO, status_code=201
)
async def create_requirement(
    project_id: uuid.UUID,
    body: CreateRequirementRequest,
    user: User = Depends(require_action(TASK_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RequirementSummaryDTO:
    project = await ProjectService(session, settings=settings).require(project_id)
    requirement = await _service(session).create(
        project=project, actor_id=user.id, raw_text=body.raw_text
    )
    await _refreshed(session, requirement)
    dto = _summary_dto(requirement, 0)
    await session.commit()
    return dto


@router.get("/projects/{project_id}/requirements", response_model=list[RequirementSummaryDTO])
async def list_requirements(
    project_id: uuid.UUID,
    _: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[RequirementSummaryDTO]:
    await ProjectService(session, settings=settings).require(project_id)
    service = _service(session)
    rows = await service.listing(project_id)
    return [_summary_dto(row, len(await service.specs(row.id))) for row in rows]


async def requirement_detail(
    session: AsyncSession, requirement_id: uuid.UUID
) -> RequirementDetailDTO:
    """The requirement with every version and proposal.

    A plain function rather than only a route, because V2.5's run credential reads the
    same view through `/api/cli/runs/requirement` — and two assemblies of one payload
    drift the first time either gains a field.
    """
    service = _service(session)
    requirement = await service.require(requirement_id)
    specs = await service.specs(requirement_id)
    latest = specs[-1] if specs else None
    return RequirementDetailDTO(
        **_summary_dto(requirement, len(specs)).model_dump(),
        specs=[_spec_dto(spec) for spec in specs],
        proposals=[
            _proposal_dto(item, await service.produced_item_ids(item.id))
            for item in await service.proposals(requirement_id)
        ],
        # Sent with the requirement so the console can disable the approve button and
        # name the reason in the same response.
        blocking_questions=[
            question.get("question", question.get("id", "?"))
            for question in (_open_questions(latest) if latest else [])
        ],
    )


@router.get("/requirements/{requirement_id}", response_model=RequirementDetailDTO)
async def read_requirement(
    requirement_id: uuid.UUID,
    _: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> RequirementDetailDTO:
    return await requirement_detail(session, requirement_id)


@router.post("/requirements/{requirement_id}/specs", response_model=FeatureSpecDTO, status_code=201)
async def add_spec(
    requirement_id: uuid.UUID,
    body: CreateSpecRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> FeatureSpecDTO:
    service = _service(session)
    requirement = await service.require(requirement_id)
    spec = await service.add_spec(
        requirement=requirement, actor_id=user.id, fields=body.model_dump()
    )
    await _refreshed(session, spec)
    dto = _spec_dto(spec)
    await session.commit()
    return dto


@router.post("/requirements/{requirement_id}/approve", response_model=RequirementSummaryDTO)
async def approve_requirement(
    requirement_id: uuid.UUID,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
) -> RequirementSummaryDTO:
    """D28's first human gate. Refused at the API, never only in the UI."""
    service = _service(session)
    requirement = await service.require(requirement_id)
    await service.approve(requirement=requirement, actor_id=user.id)
    await _refreshed(session, requirement)
    dto = _summary_dto(requirement, len(await service.specs(requirement_id)))
    await session.commit()
    return dto


@router.post(
    "/requirements/{requirement_id}/proposals", response_model=TaskProposalDTO, status_code=201
)
async def create_proposal(
    requirement_id: uuid.UUID,
    body: CreateProposalRequest,
    user: User = Depends(require_action(TASK_CREATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskProposalDTO:
    service = _service(session)
    requirement = await service.require(requirement_id)
    proposal = await service.propose(requirement=requirement, actor_id=user.id, tree=body.tree)
    await _refreshed(session, proposal)
    dto = _proposal_dto(proposal)
    await session.commit()
    return dto


@router.post("/proposals/{proposal_id}/accept", response_model=AcceptProposalResultDTO)
async def accept_proposal(
    proposal_id: uuid.UUID,
    body: AcceptProposalRequest,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AcceptProposalResultDTO:
    """D28's second human gate: accepting is what turns a proposal into cards."""
    service = _service(session)
    proposal = await service.require_proposal(proposal_id)
    requirement = await service.require(proposal.requirement_id)
    project = await ProjectService(session, settings=settings).require(requirement.project_id)
    result = await service.accept(
        project=project,
        requirement=requirement,
        proposal=proposal,
        actor_id=user.id,
        accept_ids=body.accept_ids,
        note=body.note,
        overrides=body.overrides,
    )
    tasks = TaskService(session)
    dto = AcceptProposalResultDTO(
        created=[await _task_dto(tasks, task) for task in result.created],
        incomplete=result.incomplete,
        unresolved_dependencies=result.unresolved_dependencies,
    )
    await session.commit()
    return dto


@router.post("/proposals/{proposal_id}/reject", response_model=TaskProposalDTO)
async def reject_proposal(
    proposal_id: uuid.UUID,
    body: RejectProposalRequest,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
) -> TaskProposalDTO:
    """Rejection keeps the proposal **and its reason**.

    A `POST` with a body rather than V2.1's `DELETE`: a `DELETE` body is legal HTTP and
    is stripped by enough clients that the reason would sometimes arrive and sometimes
    not — and a silently lost reason is the exact defect this route exists to fix.
    """
    service = _service(session)
    proposal = await service.require_proposal(proposal_id)
    await service.reject(proposal=proposal, actor_id=user.id, note=body.note)
    dto = _proposal_dto(proposal, await service.produced_item_ids(proposal.id))
    await session.commit()
    return dto


@router.delete("/proposals/{proposal_id}", status_code=204, deprecated=True)
async def delete_proposal(
    proposal_id: uuid.UUID,
    body: RejectProposalRequest,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Deprecated in V2.5; use `POST /proposals/{id}/reject`.

    Kept so an existing client is not broken, but it now requires the same reason: a
    route that accepts a rejection without one produces rows nobody can act on later.
    """
    service = _service(session)
    proposal = await service.require_proposal(proposal_id)
    await service.reject(proposal=proposal, actor_id=user.id, note=body.note)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
