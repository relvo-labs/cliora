"""The credential an agent inside a session may hold, and the path it authenticates on.

Two things live here, and keeping them in one module is deliberate: the token's scope
is only meaningful next to the reason a token can never become a `User`.

**A session token never resolves into a `User`.** `require_action` takes a `User` and
answers with that user's whole action set, so a token that produced one would inherit
`task.approve`, `terminal.operate` and everything else the person holds. The scope
list below would then be the only defence, and a single refactor eventually walks past
a list. Instead there are two disjoint dependencies (`api/http/deps.py`), each 401ing
on the other's token, and only four endpoints accept the agent one at all.

`AgentPrincipal` deliberately carries **no `user_id`**. A principal with one is
eventually passed to something that records an actor, and the agent starts
impersonating the person who opened the session (ADR 0028 sec 3). When the issuer is
genuinely needed, it is one lookup away on `session_tokens.issued_by`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import SessionToken, TerminalSession
from app.security.hashing import generate_secret, keyed_hash
from app.services import audit as audit_actions
from app.services.audit import AuditService
from app.services.rbac import PROJECT_VIEW, TASK_UPDATE
from app.settings import Settings, get_settings

# The prefix has three jobs, none of them decoration: `get_current_user` refuses it
# without parsing or a database lookup, secret scanners have a pattern to match, and a
# person who opens `.cliora/context/<id>.token` can tell what they are looking at.
TOKEN_PREFIX = "cliora_st_"

# Exactly two actions. What it can never hold is the interesting half: `task.approve`
# (an agent's output is not an approval), `task.create` (an agent proposes, a human
# creates — D28), every `file.*`, every `terminal.*`, and `project.manage`.
SESSION_TOKEN_SCOPES: frozenset[str] = frozenset({PROJECT_VIEW, TASK_UPDATE})

# Fields an agent may not set even through an endpoint it is allowed to call. `gates`
# is the load-bearing one — the gate endpoint is already out of reach, and this closes
# the open-shaped `PATCH` body behind it.
AGENT_FORBIDDEN_FIELDS = frozenset(
    {"gates", "owner_user_id", "assigned_runner_id", "required_secrets"}
)


@dataclass(frozen=True, slots=True)
class AgentPrincipal:
    """A session's agent, as an authenticated caller.

    No `user_id`, on purpose (see the module docstring). `project_id` is the resource
    boundary: a token may only touch cards in the project its session belongs to.
    """

    token_id: uuid.UUID
    session_id: uuid.UUID
    project_id: uuid.UUID
    scopes: frozenset[str]

    @property
    def actor_kind(self) -> str:
        return "agent"

    def holds(self, action: str) -> bool:
        return action in self.scopes


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """The one moment the plaintext exists.

    Returned to the caller that projects it into `.cliora/` and never stored, never
    logged, never returned by any other endpoint.
    """

    value: str
    row: SessionToken


class SessionTokenService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = AuditService(session)

    async def issue(
        self, *, terminal: TerminalSession, project_id: uuid.UUID, actor_id: uuid.UUID
    ) -> IssuedToken:
        """One token per session, scoped to one project.

        The scope list is **snapshotted** rather than read per request: a credential is
        a fixed grant, and consulting a constant at verification time would mean that
        editing that constant silently re-authorises every token already in the wild.
        """
        # A retry projects a new plaintext value. Revoke the previous value first
        # so a session never has two concurrently valid credentials after a lost
        # response or a manual re-projection.
        await self.revoke_for_session(terminal.id, actor_id=actor_id)
        value = generate_secret(prefix=TOKEN_PREFIX)
        row = SessionToken(
            id=uuid.uuid4(),
            session_id=terminal.id,
            project_id=project_id,
            token_hash=keyed_hash(value, self._settings),
            scopes=sorted(SESSION_TOKEN_SCOPES),
            issued_by=actor_id,
            expires_at=now_utc() + timedelta(hours=self._settings.session_token_ttl_hours),
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit.record(
            audit_actions.SESSION_TOKEN_ISSUE,
            user_id=actor_id,
            session_id=terminal.id,
            # The id, never the value. There is a test for this precise metadata.
            metadata={"token_id": str(row.id), "project_id": str(project_id)},
        )
        return IssuedToken(value=value, row=row)

    async def resolve(self, presented: str) -> AgentPrincipal | None:
        """Verify a presented token. `None` for every reason it could fail.

        Unknown, expired and revoked collapse to one answer deliberately: telling them
        apart hands a prober a signal, and the caller's next step is identical in all
        three cases.
        """
        if not presented.startswith(TOKEN_PREFIX):
            return None
        digest = keyed_hash(presented, self._settings)
        row = (
            await self._session.execute(
                select(SessionToken).where(SessionToken.token_hash == digest)
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at <= now_utc():
            return None
        return AgentPrincipal(
            token_id=row.id,
            session_id=row.session_id,
            project_id=row.project_id,
            scopes=frozenset(row.scopes or []),
        )

    async def touch(self, token_id: uuid.UUID) -> None:
        """Record use, best-effort.

        Deliberately not on the request's critical path and deliberately not exact: it
        feeds a "last used" line in the console, and a synchronous write per API call
        would cost more than that line is worth.
        """
        await self._session.execute(
            update(SessionToken).where(SessionToken.id == token_id).values(last_used_at=now_utc())
        )

    async def revoke_for_session(
        self, session_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> int:
        """Kill every token of one session.

        Called from the session state machine rather than from the four routes that can
        end a session — the same reasoning `SessionService._record_ended` documents:
        there will be a fifth door.
        """
        result = await self._session.execute(
            update(SessionToken)
            .where(SessionToken.session_id == session_id, SessionToken.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )
        revoked = int(result.rowcount or 0)
        if revoked:
            await self._audit.record(
                audit_actions.SESSION_TOKEN_REVOKE,
                user_id=actor_id,
                session_id=session_id,
                metadata={"revoked": revoked},
            )
        return revoked


def require_agent_scope(principal: AgentPrincipal, action: str) -> None:
    if not principal.holds(action):
        raise ApiError(
            "FORBIDDEN",
            "You do not have permission for this action",
            status.HTTP_403_FORBIDDEN,
        )
