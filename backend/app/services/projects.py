"""Project lifecycle, workspace bindings and the activity timeline (PJ-04, ADR 0027).

Two rules shape everything here, and both are borrowed rather than invented:

**A binding is a shortcut, never an authorization.** `sessions.authorize_workspace()`
runs when a binding is created *and again every time one is read or used*. This is the
same rule, the same function and the same wording as `services/favorites.py`, which is
the first instance of the shape in this codebase. Roots get disabled and directories
get deleted, so a path that was legal when bound may not be now (SEC-001); two copies
of one prefix rule would eventually disagree, and the day they disagree is a security
event rather than a bug.

**The timeline is not a second audit log.** Both are written on the same operations
and answer different questions. `activity_events` is readable with `project.view`,
which all three roles hold, so actor identity is redacted for anyone without
`audit.view` — see `services/activity.py::redact_actors`.

Authorization has the usual two layers (ADR 0016). The action layer lives on the
routes; the resource layer is deliberately thin here, because V2.0 has exactly two
resource rules: every holder of `project.view` sees every project (matching how
`node.view` already works), and every use of a bound path re-runs the prefix check.
No new predicate is added to `services/authz.py` for this phase.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import Project, ProjectWorkspace, User
from app.repositories.nodes import NodeRepository
from app.repositories.projects import BindingRow, ProjectRepository, ProjectSummary
from app.services import audit as audit_actions
from app.services.activity import (
    PROJECT_CREATED,
    PROJECT_UPDATED,
    WORKSPACE_BOUND,
    WORKSPACE_UNBOUND,
    ActivityItem,
    ActivityService,
)
from app.services.audit import AuditService
from app.services.favorites import (
    NODE_DISABLED,
    NODE_OFFLINE,
    OUTSIDE_ALLOWED_ROOT,
    USABLE,
    Usability,
    node_is_online,
    validate_path,
)
from app.services.sessions import authorize_workspace
from app.settings import Settings, get_settings

ACTIVE = "active"
PAUSED = "paused"
ARCHIVED = "archived"
STATUSES = (ACTIVE, PAUSED, ARCHIVED)

MAX_ACTIVITY_PAGE = 200
DEFAULT_ACTIVITY_PAGE = 50
MAX_PROJECT_PAGE = 200

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


def slugify(name: str) -> str:
    """Derive a slug from a display name.

    Only ever a *suggestion*: the caller may supply its own, and a collision is a
    409 rather than a silent suffix. Auto-suffixing (`traqora-2`) is refused for the
    same reason ADR 0026 refuses `data (1).csv` — a name the user did not choose,
    silently, is a name they will later fail to find.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:64].rstrip("-")
    return slug


def validate_slug(slug: str) -> str:
    if not _SLUG_RE.match(slug):
        raise ApiError(
            "PROJECT_SLUG_INVALID",
            "Slug must be lowercase letters, digits and hyphens",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return slug


class ProjectService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._repo = ProjectRepository(session)
        self._nodes = NodeRepository(session)
        self._audit = AuditService(session)
        self._activity = ActivityService(session)
        self._settings = settings or get_settings()

    # --- reads ----------------------------------------------------------- #

    async def list_projects(
        # Not `list`: a method by that name shadows the builtin for every annotation
        # later in the class body, so `list[ProjectSummary]` below would resolve to
        # this method. mypy caught it; the rename is the fix rather than a `# type:
        # ignore`, because the shadowing would keep biting every future signature.
        self,
        *,
        status_filter: str | None = None,
        owner_user_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectSummary]:
        if status_filter is not None and status_filter not in STATUSES:
            # INVALID_QUERY rather than a project-specific code: its documented cause
            # is "a filter was unknown", which is exactly this.
            raise ApiError(
                "INVALID_QUERY",
                "Unknown project status filter",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return await self._repo.list_summaries(
            status=status_filter,
            owner_user_id=owner_user_id,
            limit=min(limit, MAX_PROJECT_PAGE),
            offset=offset,
        )

    async def require(self, project_id: uuid.UUID) -> Project:
        project = await self._repo.get(project_id)
        if project is None:
            raise ApiError("PROJECT_NOT_FOUND", "Project not found", status.HTTP_404_NOT_FOUND)
        return project

    async def summary(self, project: Project) -> ProjectSummary:
        return await self._repo.summary(project)

    async def bindings(
        self,
        project_id: uuid.UUID,
        *,
        seconds_since_heartbeat: Callable[[uuid.UUID], float | None] | None = None,
    ) -> list[tuple[BindingRow, Usability]]:
        rows = await self._repo.list_bindings(project_id)
        return [(row, await self.usability(row, seconds_since_heartbeat)) for row in rows]

    async def usability(
        self,
        row: BindingRow,
        seconds_since_heartbeat: Callable[[uuid.UUID], float | None] | None,
    ) -> Usability:
        """Why this binding cannot be used right now — reasons in order of permanence.

        Same vocabulary and same ordering as `services/favorites.py::usability`, and
        deliberately not a new one: the two answer an identical question about an
        identical kind of stored path, and the browser already renders these four
        values. "The root is gone" outranks "the machine is down" because a binding
        that can never work again is worth saying so about even while the node
        happens to be offline.

        **One thing this cannot detect in V2.0**: a path that no longer exists on the
        node. That needs a `filesystem.*` round trip, and this phase adds no protocol
        message. The user meets it when they create a session and the daemon refuses,
        exactly as they would when typing a stale path by hand (plan/16 M-PJ-04).
        """
        node = await self._nodes.get(row.binding.node_id)
        if node is None or not node.is_enabled:
            return NODE_DISABLED
        try:
            authorize_workspace(node, row.binding.path)
        except ApiError:
            return OUTSIDE_ALLOWED_ROOT
        if seconds_since_heartbeat is not None and not node_is_online(
            node, seconds_since_heartbeat(row.binding.node_id), self._settings
        ):
            return NODE_OFFLINE
        return USABLE

    async def activity(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = DEFAULT_ACTIVITY_PAGE,
        before: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[ActivityItem]:
        return await self._repo.list_activity(
            project_id, limit=min(limit, MAX_ACTIVITY_PAGE), before=before
        )

    # --- writes ---------------------------------------------------------- #

    async def create(
        self, actor: User, *, name: str, slug: str | None, description: str | None
    ) -> Project:
        candidate = validate_slug(slug if slug else slugify(name))
        if not candidate:
            raise ApiError(
                "PROJECT_SLUG_INVALID",
                "Could not derive a slug from the name; supply one",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if await self._repo.get_by_slug(candidate) is not None:
            raise ApiError(
                "PROJECT_SLUG_TAKEN",
                "A project with this slug already exists",
                status.HTTP_409_CONFLICT,
            )

        # `owner_user_id` comes from the authenticated caller and is never accepted
        # from the request body — the same rule `session.create` follows for `user_id`.
        project = Project(
            id=uuid.uuid4(),
            name=name,
            slug=candidate,
            description=description,
            status=ACTIVE,
            owner_user_id=actor.id,
        )
        self._session.add(project)
        await self._session.flush()

        await self._audit.record(
            audit_actions.PROJECT_CREATE,
            user_id=actor.id,
            metadata={"project_id": str(project.id), "slug": project.slug},
        )
        await self._activity.record(
            PROJECT_CREATED,
            project_id=project.id,
            actor_user_id=actor.id,
            payload={"name": project.name, "slug": project.slug},
        )
        return project

    async def update(
        self,
        actor: User,
        project: Project,
        *,
        name: str | None,
        description: str | None,
        new_status: str | None,
    ) -> Project:
        changed: list[str] = []
        if name is not None and name != project.name:
            project.name = name
            changed.append("name")
        if description is not None and description != project.description:
            project.description = description
            changed.append("description")

        previous_status = project.status
        if new_status is not None and new_status != previous_status:
            if new_status not in STATUSES:
                # Unreachable through HTTP — `UpdateProjectRequest.status` is a
                # Literal, so the boundary rejects it first. Kept because a service
                # should not depend on its only current caller validating for it.
                raise ApiError(
                    "PROJECT_STATUS_INVALID",
                    "Unknown project status",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            project.status = new_status
            changed.append("status")

        if not changed:
            return project
        await self._session.flush()

        # `project.archive` is its own audit action even though archiving happens
        # through the same PATCH: "who archived that project" is a question asked on
        # its own, and answering it by filtering one action's metadata is not an
        # answer. The *timeline* keeps a single `project.updated` kind, because a
        # reader there is scanning one project in order and would have to merge two
        # kinds mentally (services/activity.py).
        archived = "status" in changed and project.status == ARCHIVED
        await self._audit.record(
            audit_actions.PROJECT_ARCHIVE if archived else audit_actions.PROJECT_UPDATE,
            user_id=actor.id,
            metadata={"project_id": str(project.id), "changed": changed},
        )
        payload: dict[str, object] = {"changed": changed}
        if "status" in changed:
            payload |= {"from": previous_status, "to": project.status}
        await self._activity.record(
            PROJECT_UPDATED, project_id=project.id, actor_user_id=actor.id, payload=payload
        )
        return project

    async def bind_workspace(
        self,
        actor: User,
        project: Project,
        *,
        node_id: uuid.UUID,
        path: str,
        label: str | None,
        is_primary: bool,
    ) -> tuple[ProjectWorkspace, bool]:
        """Bind a workspace path, or return the binding that already exists.

        Returns `(binding, created)`. A repeat bind is the same intent expressed
        twice, so it answers 200 with the existing row rather than 409 — the same
        judgement `services/favorites.py::add` makes, and for the same reason: a
        conflict would make the UI's optimistic toggle need a special case for
        "already there".
        """
        self._require_not_archived(project)
        validate_path(path)

        node = await self._nodes.get(node_id)
        if node is None or node.deleted_at is not None:
            raise ApiError("NODE_NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
        # The prefix check, from the one implementation of it. Binding a path that
        # could not start a session must not be storable as a shortcut to starting
        # one — and this runs again on every read and every use.
        authorize_workspace(node, path)

        existing = await self._repo.find_binding(project.id, node_id=node_id, path=path)
        if existing is not None:
            if is_primary and not existing.is_primary:
                await self._clear_primary(project.id)
                existing.is_primary = True
                await self._session.flush()
            return existing, False

        if is_primary:
            await self._clear_primary(project.id)

        binding = ProjectWorkspace(
            id=uuid.uuid4(),
            project_id=project.id,
            node_id=node_id,
            path=path,
            label=label,
            is_primary=is_primary,
        )
        self._session.add(binding)
        try:
            await self._session.flush()
        except IntegrityError as exc:  # pragma: no cover - concurrent duplicate
            # The unique constraint, not the lookup above, is what makes this
            # impossible. Two concurrent binds both see nothing and both insert; one
            # of them arrives here and is served the winner's row.
            await self._session.rollback()
            winner = await self._repo.find_binding(project.id, node_id=node_id, path=path)
            if winner is None:
                raise exc
            return winner, False

        await self._audit.record(
            audit_actions.PROJECT_WORKSPACE_BIND,
            user_id=actor.id,
            node_id=node_id,
            metadata={"project_id": str(project.id), "path": path},
        )
        await self._activity.record(
            WORKSPACE_BOUND,
            project_id=project.id,
            actor_user_id=actor.id,
            payload={"node_name": node.name, "path": path},
        )
        return binding, True

    async def unbind_workspace(self, actor: User, project: Project, binding_id: uuid.UUID) -> None:
        """Remove a binding. **Touches no session.**

        A session already running from this path keeps running, keeps its
        `project_id`, and keeps its terminal — exit condition 3. Unbinding says
        "stop offering this path here", not "stop the work".
        """
        binding = await self._repo.get_binding(project.id, binding_id)
        if binding is None:
            raise ApiError(
                "PROJECT_WORKSPACE_NOT_FOUND",
                "Workspace binding not found",
                status.HTTP_404_NOT_FOUND,
            )
        node = await self._nodes.get(binding.node_id)
        path, node_id = binding.path, binding.node_id
        await self._session.delete(binding)
        await self._session.flush()

        await self._audit.record(
            audit_actions.PROJECT_WORKSPACE_UNBIND,
            user_id=actor.id,
            node_id=node_id,
            metadata={"project_id": str(project.id), "path": path},
        )
        await self._activity.record(
            WORKSPACE_UNBOUND,
            project_id=project.id,
            actor_user_id=actor.id,
            payload={"node_name": node.name if node else None, "path": path},
        )

    # --- helpers used by the session path -------------------------------- #

    async def authorize_session_workspace(
        self, project: Project, *, node_id: uuid.UUID, workspace: str
    ) -> None:
        """Refuse a session whose workspace is not one of this project's bindings.

        Compared for **exact equality**, not by prefix. Two reasons: with nested
        bindings a prefix match has several answers and the timeline row has to name
        one, and the prefix comparison is already what `authorize_workspace` does —
        doing it twice on one path entangles the two meanings (the `/a/projects` vs
        `/a/projects-other` trap). To work in a subdirectory, bind the subdirectory.
        """
        self._require_not_archived(project)
        if not await self._repo.binding_exists(project.id, node_id=node_id, path=workspace):
            raise ApiError(
                "SESSION_PROJECT_MISMATCH",
                "The workspace does not belong to this project",
                status.HTTP_400_BAD_REQUEST,
            )

    def _require_not_archived(self, project: Project) -> None:
        if project.status == ARCHIVED:
            raise ApiError(
                "PROJECT_ARCHIVED",
                "This project is archived",
                status.HTTP_409_CONFLICT,
            )

    async def _clear_primary(self, project_id: uuid.UUID) -> None:
        """Demote the current primary before promoting another.

        In the same transaction as the promotion, so the partial unique index never
        sees two. The index is what actually enforces the rule; this is what stops it
        from turning a legitimate change of primary into an error.
        """
        for row in await self._repo.list_bindings(project_id):
            if row.binding.is_primary:
                row.binding.is_primary = False
        await self._session.flush()
