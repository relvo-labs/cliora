"""Project secrets: five endpoints, and none of them returns a value.

FR-RUNENV-001, ADR 0032. Four shapes are decided here rather than in the service:

**The routes are mounted unconditionally and refuse through a dependency.** The two
OpenAPI dumps in the phase baseline are byte-identical, and that sameness is a property
worth keeping: once a route's *existence* depends on a flag, "did the API surface
change" stops having one answer. The order is `require_projects_enabled` then
`require_agent_runs_enabled` — reversed, a deployment with the project layer off would
answer 403 instead of 404 and disclose that the route exists.

**Reading the list needs `secret.manage`, not `project.view`.** A list of which
credentials a project holds and when each was last used is reconnaissance in its own
right. What a Developer actually needs — the names, to tick on a card — is the last
endpoint, and it returns nothing else.

**There is no PATCH.** A rename orphans every card pointing at the old name, and a kind
change retroactively alters where an already-delivered value was allowed to go. Both are
"delete and create", which is what they are.

**Nothing here can return plaintext**, and that is enforced twice over: `ProjectSecretDTO`
has no field for it, and `GATE-SC-NO-SECRET-IN-RESPONSE` scans every response schema in
the whole document — because the endpoint most likely to leak a value is not this one,
which is being watched, but some future route that hands back a whole row.
"""

from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import (
    get_session,
    require_action,
    require_agent_runs_enabled,
    require_projects_enabled,
)
from app.api.http.schemas import (
    CreateProjectSecretRequest,
    ProjectSecretDTO,
    RotateProjectSecretRequest,
    SecretKind,
)
from app.db.models import ProjectSecret, User
from app.services.projects import ProjectService
from app.services.rbac import SECRET_MANAGE, TASK_UPDATE
from app.services.secrets import SecretService

router = APIRouter(
    prefix="/api",
    tags=["secrets"],
    dependencies=[
        Depends(require_projects_enabled),
        Depends(require_agent_runs_enabled),
    ],
)


def _dto(secret: ProjectSecret) -> ProjectSecretDTO:
    return ProjectSecretDTO(
        id=secret.id,
        project_id=secret.project_id,
        name=secret.name,
        # The column is a `VARCHAR` with a CHECK behind it, so the narrowing is real —
        # but it happens in the database, and the type checker cannot see that. Casting
        # here rather than widening the DTO: the closed set is what the console renders
        # against, and losing it would let an unknown kind reach the page silently.
        kind=cast(SecretKind, secret.kind),
        created_by=secret.created_by,
        created_at=secret.created_at,
        rotated_at=secret.rotated_at,
        last_used_at=secret.last_used_at,
    )


@router.get("/projects/{project_id}/secrets", response_model=list[ProjectSecretDTO])
async def list_secrets(
    project_id: uuid.UUID,
    _user: User = Depends(require_action(SECRET_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectSecretDTO]:
    await ProjectService(session).require(project_id)
    return [_dto(row) for row in await SecretService(session).list_for(project_id)]


@router.get("/projects/{project_id}/secret-names", response_model=list[str])
async def list_secret_names(
    project_id: uuid.UUID,
    _user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Just the names, for the card editor.

    A Developer has to declare `required_secrets` on a card, which means knowing which
    names exist — but that is not a reason to hand them `secret.manage` and with it the
    creation, rotation and deletion of every credential the project holds.
    """
    await ProjectService(session).require(project_id)
    return sorted(await SecretService(session).existing_names(project_id))


@router.post(
    "/projects/{project_id}/secrets",
    response_model=ProjectSecretDTO,
    status_code=status.HTTP_201_CREATED,
)
async def create_secret(
    project_id: uuid.UUID,
    body: CreateProjectSecretRequest,
    user: User = Depends(require_action(SECRET_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> ProjectSecretDTO:
    project = await ProjectService(session).require(project_id)
    secret = await SecretService(session).create(
        project=project, name=body.name, kind=body.kind, value=body.value, actor_id=user.id
    )
    await session.commit()
    return _dto(secret)


@router.put("/projects/{project_id}/secrets/{secret_id}", response_model=ProjectSecretDTO)
async def rotate_secret(
    project_id: uuid.UUID,
    secret_id: uuid.UUID,
    body: RotateProjectSecretRequest,
    user: User = Depends(require_action(SECRET_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> ProjectSecretDTO:
    """Rotation is an overwrite of the value, and nothing else."""
    project = await ProjectService(session).require(project_id)
    service = SecretService(session)
    secret = await service.require(project_id, secret_id)
    await service.rotate(project=project, secret=secret, value=body.value, actor_id=user.id)
    await session.commit()
    return _dto(secret)


@router.delete(
    "/projects/{project_id}/secrets/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # FastAPI asserts that a 204 declares no body, and the annotated `-> None` alone is
    # not enough for it.
    response_class=Response,
)
async def delete_secret(
    project_id: uuid.UUID,
    secret_id: uuid.UUID,
    user: User = Depends(require_action(SECRET_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Soft delete, effective at the next claim.

    **The platform stops delivering it; it does not revoke it anywhere else.** Cliora
    does not know what that token is called at GitHub, so the console says so at the
    point of deletion — without that sentence, deleting reads as "it is now safe".
    """
    project = await ProjectService(session).require(project_id)
    service = SecretService(session)
    secret = await service.require(project_id, secret_id)
    await service.delete(project=project, secret=secret, actor_id=user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
