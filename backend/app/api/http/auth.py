from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import get_auth_service, get_current_user
from app.api.http.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    WsTicketRequest,
    WsTicketResponse,
)
from app.db.engine import get_session
from app.db.models import User
from app.services.auth import AuthService
from app.services.ws_ticket import get_ws_ticket_service
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    auth: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    try:
        result = await auth.login(body.username, body.password)
    except ApiError:
        # A failed sign-in is an auditable security event, and the service has
        # already staged that row — so it must be committed even though the request
        # fails. Same pattern as the FAILED session row in sessions.py: the audit
        # must outlive the operation it records.
        await session.commit()
        raise
    await session.commit()
    return LoginResponse(
        tokens=TokenResponse(
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
        ),
        user=UserResponse.from_user(result.user, settings=settings),
    )


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    pair = await auth.refresh(body.refresh_token)
    await session.commit()
    return TokenResponse(access_token=pair.access_token, refresh_token=pair.refresh_token)


@router.post("/auth/logout")
async def logout(
    auth: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    await auth.logout(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=UserResponse)
async def me(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    return UserResponse.from_user(user, settings=settings)


@router.post("/ws-ticket", response_model=WsTicketResponse)
async def ws_ticket(
    body: WsTicketRequest,
    user: User = Depends(get_current_user),
) -> WsTicketResponse:
    ticket = get_ws_ticket_service().issue(user.id, body.resource)
    return WsTicketResponse(ticket=ticket)
