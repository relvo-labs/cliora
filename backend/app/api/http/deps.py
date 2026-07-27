"""HTTP boundary dependencies: session, current user, and RBAC guards.

FastAPI caches a dependency result per request, so `get_session` resolves to one
`AsyncSession` shared by the auth service and the route — the route owns the
commit for that single unit of work.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.api.errors import ApiError
from app.api.middleware import actor_var, denial_var
from app.db.engine import get_session
from app.db.models import User
from app.services.auth import AuthService
from app.services.rbac import has_action


async def get_auth_service(session: AsyncSession = Depends(get_session)) -> AuthService:
    return AuthService(session)


async def get_current_user(
    authorization: str | None = Header(default=None),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError("UNAUTHENTICATED", "Missing bearer token", status.HTTP_401_UNAUTHORIZED)
    user = await auth.authenticate_access(authorization[len("Bearer ") :])
    # Publish the actor so an authorization refusal can name who was refused
    # (app/api/middleware.py).
    actor_var.set(user.id)
    return user


def require_action(action: str) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if not has_action(user, action):
            # "action": the role never holds it, as opposed to holding it but not
            # for this resource (see services/authz.py).
            denial_var.set((action, "action"))
            metrics.increment(
                metrics.AUTHZ_DENIED_TOTAL, action=action, role=user.role.name, reason="action"
            )
            raise ApiError(
                "FORBIDDEN", "You do not have permission for this action", status.HTTP_403_FORBIDDEN
            )
        return user

    return dependency
