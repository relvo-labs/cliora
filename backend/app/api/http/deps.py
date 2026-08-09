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
from app.settings import Settings, get_settings


async def get_auth_service(session: AsyncSession = Depends(get_session)) -> AuthService:
    return AuthService(session)


def require_projects_enabled(settings: Settings = Depends(get_settings)) -> None:
    """404 the project layer when `CLIORA_PROJECTS_ENABLED` is off (ADR 0027 sec 3).

    **404, not 403.** A 403 says "this exists and you may not have it"; the layer
    genuinely does not exist in this deployment, and a deployment that has never
    enabled it should not be advertising a roadmap to anyone who probes a URL. For
    the same reason it carries no error code — a body naming `PROJECTS_DISABLED`
    would leak precisely the fact the bare 404 withholds.

    Applied as a router-level dependency so it cannot be forgotten on a new route,
    and so the route set stays identical whichever way the flag is set: the guard is
    in the handler, never in `include_router`.
    """
    if not settings.projects_enabled:
        raise ApiError("NOT_FOUND", "Not found", status.HTTP_404_NOT_FOUND)


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
