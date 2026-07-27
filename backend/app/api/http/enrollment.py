from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import require_action
from app.api.http.schemas import (
    CreateEnrollmentTokenRequest,
    EnrollmentTokenCreatedResponse,
    EnrollmentTokenResponse,
)
from app.db.engine import get_session
from app.db.models import User
from app.services.enrollment import EnrollmentService
from app.services.rbac import ENROLLMENT_MANAGE

router = APIRouter(prefix="/api/enrollment-tokens", tags=["enrollment"])


@router.post("", response_model=EnrollmentTokenCreatedResponse, status_code=201)
async def create_token(
    body: CreateEnrollmentTokenRequest,
    user: User = Depends(require_action(ENROLLMENT_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> EnrollmentTokenCreatedResponse:
    created = await EnrollmentService(session).create(
        created_by=user.id, ttl_seconds=body.ttl_seconds, max_uses=body.max_uses
    )
    await session.commit()
    return EnrollmentTokenCreatedResponse(
        id=created.token.id,
        token=created.plaintext,
        expires_at=created.token.expires_at,
        max_uses=created.token.max_uses,
    )


@router.get("", response_model=list[EnrollmentTokenResponse])
async def list_tokens(
    _: User = Depends(require_action(ENROLLMENT_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> list[EnrollmentTokenResponse]:
    tokens = await EnrollmentService(session).list()
    return [EnrollmentTokenResponse.from_token(token) for token in tokens]


@router.delete("/{token_id}")
async def revoke_token(
    token_id: uuid.UUID,
    user: User = Depends(require_action(ENROLLMENT_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await EnrollmentService(session).revoke(token_id, actor_id=user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
