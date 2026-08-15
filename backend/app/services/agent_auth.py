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
from app.db.models import RunToken, SessionToken, TerminalSession
from app.security.hashing import generate_secret, keyed_hash
from app.services import audit as audit_actions
from app.services.audit import AuditService
from app.services.rbac import PROJECT_VIEW, TASK_UPDATE
from app.settings import Settings, get_settings

# The prefix has three jobs, none of them decoration: `get_current_user` refuses it
# without parsing or a database lookup, secret scanners have a pattern to match, and a
# person who opens `.cliora/context/<id>.token` can tell what they are looking at.
TOKEN_PREFIX = "cliora_st_"
# The run credential's prefix, and the same three jobs. A **separate table** rather
# than a nullable `session_id` on the one above: exit condition 12 forbids a run from
# having a `terminal_sessions` row, and `revoke_for_session`'s "there will be a fifth
# door" only means anything while that table serves one kind of subject (ADR 0029 §6).
RUN_TOKEN_PREFIX = "cliora_rt_"

KIND_SESSION = "session"
KIND_RUN = "run"

# Exactly two actions. What it can never hold is the interesting half: `task.approve`
# (an agent's output is not an approval), `task.create` (an agent proposes, a human
# creates — D28), every `file.*`, every `terminal.*`, and `project.manage`.
SESSION_TOKEN_SCOPES: frozenset[str] = frozenset({PROJECT_VIEW, TASK_UPDATE})

# **Identical to a session's, deliberately.** Posting a message, asking a question and
# attaching an artifact need no new action: after the 2026-08-11 ruling all three
# endpoints require `task.update`, which is exactly what this scope carries — so the
# scope now corresponds to what it does, instead of being covered by a resource check.
#
# No `task.message` or `task.attach` scope-only pseudo-actions either. `ROLE_ACTIONS`
# is the single source of the action vocabulary and
# `test_every_action_is_enforced_somewhere` asserts it in both directions; an action
# that exists only inside a token scope, held by no role, would turn that test into a
# list somebody has to remember to exclude from.
#
# What a run can never hold is the interesting half, and two of them are new here:
# `run.dispatch` and `run.cancel`. A run cannot queue work for anybody else and cannot
# cancel another run — without that, one prompt-injected agent could empty the queue.
RUN_TOKEN_SCOPES: frozenset[str] = frozenset({PROJECT_VIEW, TASK_UPDATE})

# Fields an agent may not set even through an endpoint it is allowed to call. `gates`
# is the load-bearing one — the gate endpoint is already out of reach, and this closes
# the open-shaped `PATCH` body behind it.
#
# `card_kind` joined the set in V2.5 and is the sharpest entry: a clarification run that
# could rewrite its own card to `implementation` would have lifted the "this kind of
# card carries no secret" refusal for the card's *next* dispatch. The field is otherwise
# editable — a person may correct a miscategorised card until it has been run — so
# excluding it here is the whole of the boundary (ADR 0034 §5).
AGENT_FORBIDDEN_FIELDS = frozenset(
    {"gates", "owner_user_id", "assigned_runner_id", "required_secrets", "card_kind"}
)


@dataclass(frozen=True, slots=True)
class AgentPrincipal:
    """An agent, as an authenticated caller — in either of its two shapes.

    Still **no `user_id`**, on purpose (see the module docstring), and that holds for
    both kinds: a run's principal must not be able to act as the person who dispatched
    it any more than a session's can act as the person who opened it.

    `kind` is an explicit field rather than `run_id is not None`. The guards below
    match on it, and a derived discriminator would silently take the wrong branch the
    day somebody adds a third kind of token.

    `project_id` is the resource boundary in both shapes; a run additionally carries
    `task_id`, because every CLI call has to check "does this card belong to this run"
    and the run↔task relation is immutable.
    """

    token_id: uuid.UUID
    project_id: uuid.UUID
    scopes: frozenset[str]
    kind: str = KIND_SESSION
    session_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None

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
            kind=KIND_SESSION,
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


class RunTokenService:
    """The credential an agent inside a *run* may hold (ADR 0029 §6).

    Everything that can be shared with :class:`SessionTokenService` is: the same
    pepper, the same `keyed_hash`, only the HMAC stored, scopes snapshotted at issue.
    What is not shared is the table, and that is the whole reason this class exists —
    `session_tokens.session_id` is NOT NULL against `terminal_sessions`, and a run must
    not have a row there.

    Revocation has **four** triggers and they all come through `revoke_for_run`: the
    run reaching a terminal state, being cancelled, its runner being disabled, and its
    directory being reclaimed. The last one is easy to miss: the token *file* is deleted
    when the run ends, but the row has to follow, or a reclaimed run leaves a valid
    credential with no subject.
    """

    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = AuditService(session)

    async def issue(self, *, run: RunTokenSubject) -> IssuedRunToken:
        """One token per run, scoped to that run's project and card.

        The lifetime is the run's wall clock plus a margin, **bounded by the
        deployment's existing ceiling on how long an agent credential may live**. That
        bound started to bite when the wall clock grew from one hour to six (ADR 0029
        §4), so it is asserted rather than assumed: a token that would outlive the
        ceiling is refused here instead of being issued and expiring mid-run.
        """
        ceiling = timedelta(hours=self._settings.run_token_ttl_hours)
        wanted = timedelta(seconds=run.timeout_seconds) + timedelta(minutes=15)
        if wanted > ceiling:
            raise ApiError(
                "RUN_TOKEN_TTL_EXCEEDED",
                "This run would need a credential that outlives the platform's limit "
                "on how long an agent credential may be valid",
                status.HTTP_409_CONFLICT,
                details={
                    "requested_seconds": int(wanted.total_seconds()),
                    "limit_seconds": int(ceiling.total_seconds()),
                },
            )
        await self.revoke_for_run(run.run_id)
        value = generate_secret(prefix=RUN_TOKEN_PREFIX)
        row = RunToken(
            id=uuid.uuid4(),
            run_id=run.run_id,
            project_id=run.project_id,
            task_id=run.task_id,
            token_hash=keyed_hash(value, self._settings),
            scopes=sorted(RUN_TOKEN_SCOPES),
            expires_at=now_utc() + wanted,
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit.record(
            audit_actions.RUN_TOKEN_ISSUE,
            user_id=None,
            metadata={"token_id": str(row.id), "run_id": str(run.run_id)},
        )
        return IssuedRunToken(value=value, row=row)

    async def resolve(self, presented: str) -> AgentPrincipal | None:
        if not presented.startswith(RUN_TOKEN_PREFIX):
            return None
        digest = keyed_hash(presented, self._settings)
        row = (
            await self._session.execute(select(RunToken).where(RunToken.token_hash == digest))
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at <= now_utc():
            return None
        return AgentPrincipal(
            token_id=row.id,
            kind=KIND_RUN,
            project_id=row.project_id,
            scopes=frozenset(row.scopes or []),
            run_id=row.run_id,
            task_id=row.task_id,
        )

    async def touch(self, token_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RunToken).where(RunToken.id == token_id).values(last_used_at=now_utc())
        )

    async def revoke_for_run(self, run_id: uuid.UUID) -> int:
        """Kill every token of one run. Called from the run state machine, never from
        the routes that can end a run — the same reasoning as its session counterpart,
        and here there are four doors rather than one."""
        result = await self._session.execute(
            update(RunToken)
            .where(RunToken.run_id == run_id, RunToken.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )
        revoked = int(result.rowcount or 0)
        if revoked:
            await self._audit.record(
                audit_actions.RUN_TOKEN_REVOKE,
                user_id=None,
                metadata={"run_id": str(run_id), "revoked": revoked},
            )
        return revoked


@dataclass(frozen=True, slots=True)
class RunTokenSubject:
    """What a run token is issued against. A small value type rather than the ORM row,
    so issuing does not need the whole `TaskRun` loaded."""

    run_id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class IssuedRunToken:
    """The one moment the plaintext exists. Written into the run directory at 0600 and
    deleted the instant the run ends — a credential's lifetime is the run, not the
    directory's retention."""

    value: str
    row: RunToken
