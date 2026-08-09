"""HTTP boundary dependencies: session, current user, and RBAC guards.

FastAPI caches a dependency result per request, so `get_session` resolves to one
`AsyncSession` shared by the auth service and the route — the route owns the
commit for that single unit of work.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.api.errors import ApiError
from app.api.middleware import actor_var, agent_var, denial_var
from app.db.engine import get_session
from app.db.models import User
from app.services.agent_auth import TOKEN_PREFIX, AgentPrincipal, SessionTokenService
from app.services.auth import AuthService
from app.services.rbac import TASK_APPROVE, has_action
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
    request: Request,
    authorization: str | None = Header(default=None),
    auth: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError("UNAUTHENTICATED", "Missing bearer token", status.HTTP_401_UNAUTHORIZED)
    presented = authorization[len("Bearer ") :]
    if presented.startswith(TOKEN_PREFIX):
        # A session credential must never become a `User`. `require_action` answers
        # with a user's *entire* action set, so a token that resolved into one would
        # inherit `task.approve` and every terminal action along with it — and the
        # scope list would become the only thing standing in the way (ADR 0028 sec 3).
        #
        # Resolve only for refusal attribution. The result can set agent_var for an
        # audit row, but this branch can never return it (or manufacture a User), so
        # the two authentication paths remain structurally disjoint. Invalid,
        # expired and revoked values still produce the identical public answer.
        principal = await SessionTokenService(session, settings=settings).resolve(presented)
        route = getattr(request.scope.get("route"), "path", "")
        if principal is not None and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            agent_var.set(principal.token_id)
            action = TASK_APPROVE if "/gates/" in route else "human_authentication"
            denial_var.set((action, "credential_type"))
            metrics.increment(
                metrics.AUTHZ_DENIED_TOTAL,
                action=action,
                role="session_agent",
                reason="credential_type",
            )
        # The same 401 as any other bad token, with no hint that the token type was
        # the problem: a distinguishable answer is something a prober can use.
        raise ApiError("UNAUTHENTICATED", "Missing bearer token", status.HTTP_401_UNAUTHORIZED)
    user = await auth.authenticate_access(presented)
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


async def get_agent_principal(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AgentPrincipal:
    """Authenticate a session credential. The second, disjoint authentication path.

    Refuses anything that is not a session token — including a perfectly valid user
    JWT — so the two paths cannot be reached through each other. Only the four
    endpoints the CLI needs depend on this (`plan/17/04-…md` §2.3).

    404 is not an option here and 403 is not either: this is authentication, and the
    caller presented nothing this path recognises.
    """
    if not settings.projects_enabled:
        # Not a 404: a 404 belongs to a resource, and this is a credential nobody in
        # this deployment can hold.
        raise ApiError("UNAUTHENTICATED", "Missing bearer token", status.HTTP_401_UNAUTHORIZED)
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError("UNAUTHENTICATED", "Missing bearer token", status.HTTP_401_UNAUTHORIZED)
    principal = await SessionTokenService(session, settings=settings).resolve(
        authorization[len("Bearer ") :]
    )
    if principal is None:
        raise ApiError("UNAUTHENTICATED", "Missing bearer token", status.HTTP_401_UNAUTHORIZED)
    agent_var.set(principal.token_id)
    return principal


def require_agent_action(action: str) -> Callable[[AgentPrincipal], Awaitable[AgentPrincipal]]:
    """The agent-side counterpart of `require_action`.

    The metrics label says `session_agent` rather than a role name, and the token id
    never becomes a label — one would make the metric's cardinality grow with every
    session ever opened.
    """

    async def dependency(
        principal: AgentPrincipal = Depends(get_agent_principal),
    ) -> AgentPrincipal:
        if not principal.holds(action):
            denial_var.set((action, "action"))
            metrics.increment(
                metrics.AUTHZ_DENIED_TOTAL,
                action=action,
                role="session_agent",
                reason="action",
            )
            raise ApiError(
                "FORBIDDEN", "You do not have permission for this action", status.HTTP_403_FORBIDDEN
            )
        return principal

    return dependency
