"""Agent runners and the repositories they fetch from (FR-AGENT-001/012, ADR 0029/0031).

Two small services in one module, because they answer the two halves of one question
a dispatch has to settle before it can queue anything: *is there a machine that can do
this*, and *does the platform know where this project's code lives*.

**A runner has no online state of its own.** There is no `status` column and no
`last_seen_at`: a runner is online exactly when its node is, and that is computed from
`NodeConnectionRegistry.is_connected` on the same path the Nodes page uses. A stored
copy would be a second answer that can go stale, and this module deliberately does not
create one (ADR 0029 sec 1).

**`dedicated` is reported, never set.** The daemon derives it from
`len(workspace.allowed_roots) == 0` and the platform displays it. That follows ADR
0023's rule for the codex sandbox flag — report the machine's actual posture, never
the one you wish it had — and it matters here because the platform has *no* technical
isolation between a run and the node's allowed roots (ADR 0031 sec 6).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import AgentRunner, Node, Project, ProjectRepository, TaskRun
from app.services import audit as audit_actions
from app.services.audit import AuditService
from app.settings import Settings, get_settings

# RFC 1123 host label, joined by dots. Deliberately not a URL parser: this service
# never sees a URL (see `RepositoryService`), so there is nothing to parse.
_HOST = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
# `owner/repo`, and more segments for hosts that nest groups. No leading slash, no
# `..`, no `~`, nothing that could climb out of the path when it is joined into a URL.
_REPO_PATH = re.compile(r"^[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-]+)+$")
# A ref name. The leading-dash exclusion is not cosmetic: `git clone --branch -x` would
# read as a flag, and the closed argv table cannot save a value that *is* a flag.
_BRANCH = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._\-/]*$")

SCHEMES = frozenset({"https", "ssh"})

# Fields `PATCH /api/agents/{id}` may set. `runtimes` and `dedicated` are absent on
# purpose: both are the daemon's report about the machine, and letting an administrator
# type them in would make the console show the posture somebody wished for.
EDITABLE_RUNNER_FIELDS = frozenset({"name", "enabled", "max_concurrent", "max_waiting", "labels"})


@dataclass(frozen=True, slots=True)
class RunnerView:
    """A runner plus the facts that are not on its row.

    `online` comes from the connection registry, `active_runs` and `waiting_runs` from
    the queue. Assembled here rather than stored, for the reason in the module
    docstring.
    """

    runner: AgentRunner
    node: Node
    online: bool
    active_runs: int
    waiting_runs: int


class RunnerService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = AuditService(session)

    async def require(self, runner_id: uuid.UUID) -> AgentRunner:
        runner = await self._session.get(AgentRunner, runner_id)
        if runner is None:
            raise ApiError("NOT_FOUND", "Agent not found", status.HTTP_404_NOT_FOUND)
        return runner

    async def for_node(self, node_id: uuid.UUID) -> AgentRunner | None:
        return (
            await self._session.execute(select(AgentRunner).where(AgentRunner.node_id == node_id))
        ).scalar_one_or_none()

    async def list_views(self, *, is_online) -> list[RunnerView]:  # noqa: ANN001 - callable
        """Every runner, with the derived facts the console shows.

        `is_online` is passed in rather than imported so this module never depends on
        the WebSocket registry: the queue service and the tests both call it with their
        own answer, and the service stays a pure function of the database plus that
        one predicate.
        """
        rows = (
            await self._session.execute(
                select(AgentRunner, Node)
                .join(Node, Node.id == AgentRunner.node_id)
                .where(Node.deleted_at.is_(None))
                .order_by(AgentRunner.name)
            )
        ).all()
        counts = await self._run_counts([runner.id for runner, _ in rows])
        return [
            RunnerView(
                runner=runner,
                node=node,
                online=bool(is_online(node.id)),
                active_runs=counts.get((runner.id, "active"), 0),
                waiting_runs=counts.get((runner.id, "waiting"), 0),
            )
            for runner, node in rows
        ]

    async def view(self, runner: AgentRunner, *, is_online) -> RunnerView:  # noqa: ANN001
        node = await self._session.get(Node, runner.node_id)
        if node is None:  # pragma: no cover - the FK makes this unreachable
            raise ApiError("NOT_FOUND", "Agent not found", status.HTTP_404_NOT_FOUND)
        counts = await self._run_counts([runner.id])
        return RunnerView(
            runner=runner,
            node=node,
            online=bool(is_online(node.id)),
            active_runs=counts.get((runner.id, "active"), 0),
            waiting_runs=counts.get((runner.id, "waiting"), 0),
        )

    async def _run_counts(self, runner_ids: list[uuid.UUID]) -> dict[tuple[uuid.UUID, str], int]:
        """Occupancy, split the way the two limits are.

        `waiting_for_input` is counted separately because it holds no process and so
        does not occupy `max_concurrent` — a run waiting on a person must not be able
        to take a node's execution capacity away (ADR 0029 sec 5).
        """
        if not runner_ids:
            return {}
        rows = (
            await self._session.execute(
                select(TaskRun.runner_id, TaskRun.status, func.count())
                .where(
                    TaskRun.runner_id.in_(runner_ids),
                    TaskRun.status.in_(("claimed", "running", "waiting_for_input")),
                )
                .group_by(TaskRun.runner_id, TaskRun.status)
            )
        ).all()
        out: dict[tuple[uuid.UUID, str], int] = {}
        for runner_id, run_status, count in rows:
            bucket = "waiting" if run_status == "waiting_for_input" else "active"
            out[(runner_id, bucket)] = out.get((runner_id, bucket), 0) + int(count)
        return out

    async def update(
        self, *, runner: AgentRunner, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> AgentRunner:
        unknown = sorted(set(changes) - EDITABLE_RUNNER_FIELDS)
        if unknown:
            # Refused by name rather than ignored: a silently dropped field is a change
            # the caller believes it made.
            raise ApiError(
                "INVALID_ARGUMENT",
                f"Not editable: {', '.join(unknown)}",
                status.HTTP_400_BAD_REQUEST,
            )
        for field, value in changes.items():
            if field in {"max_concurrent", "max_waiting"} and (
                not isinstance(value, int) or value < 0 or value > 64
            ):
                raise ApiError(
                    "INVALID_ARGUMENT",
                    f"{field} must be between 0 and 64",
                    status.HTTP_400_BAD_REQUEST,
                )
            if field == "labels" and (
                not isinstance(value, list) or not all(isinstance(item, str) for item in value)
            ):
                raise ApiError(
                    "INVALID_ARGUMENT", "labels must be strings", status.HTTP_400_BAD_REQUEST
                )
            setattr(runner, field, value)
        if "enabled" in changes:
            runner.disabled_at = None if changes["enabled"] else now_utc()
        await self._session.flush()
        await self._audit.record(
            audit_actions.AGENT_UPDATE,
            user_id=actor_id,
            node_id=runner.node_id,
            metadata={"runner_id": str(runner.id), "fields": sorted(changes)},
        )
        return runner


class RepositoryService:
    """Where a project's code lives — **three fields, never a URL**.

    The endpoint behind this accepts `scheme`, `host` and `path` separately, and that
    is a security decision rather than an interface preference. An endpoint that takes
    a URL and parses it receives `https://user:token@github.com/…` on its first day,
    and that token then lives in the database, in `git remote -v`, in the reflog and in
    error messages. Split into columns, **userinfo cannot be expressed at all** — which
    beats filtering it out (ADR 0031 sec 5).

    The host is checked against the deployment's allowlist here **and again** against
    the node's own list in the daemon. Two lists, both enforced, for the same reason
    `authorize_workspace` and the daemon's `os.Root` both check a path: Central is the
    coarse filter, the node is the final authority.
    """

    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = AuditService(session)

    async def list_for(self, project_id: uuid.UUID) -> list[ProjectRepository]:
        return list(
            (
                await self._session.execute(
                    select(ProjectRepository)
                    .where(ProjectRepository.project_id == project_id)
                    .order_by(ProjectRepository.created_at)
                )
            ).scalars()
        )

    async def require(self, project_id: uuid.UUID, repository_id: uuid.UUID) -> ProjectRepository:
        row = await self._session.get(ProjectRepository, repository_id)
        if row is None or row.project_id != project_id:
            raise ApiError("NOT_FOUND", "Repository not found", status.HTTP_404_NOT_FOUND)
        return row

    def host_allowed(self, host: str) -> bool:
        # An empty allowlist allows nothing. That is the right default for a deployment
        # that has not decided yet: the alternative — empty means "anywhere" — turns
        # forgetting to configure it into an outbound-fetch surface.
        return host.lower() in {item.lower() for item in self._settings.git_allowed_hosts}

    async def create(
        self,
        *,
        project: Project,
        scheme: str,
        host: str,
        path: str,
        default_branch: str,
        label: str | None,
        actor_id: uuid.UUID,
    ) -> ProjectRepository:
        if scheme not in SCHEMES:
            raise ApiError(
                "INVALID_ARGUMENT", "scheme must be https or ssh", status.HTTP_400_BAD_REQUEST
            )
        if not _HOST.match(host):
            raise ApiError(
                "INVALID_ARGUMENT", "host is not a hostname", status.HTTP_400_BAD_REQUEST
            )
        if not self.host_allowed(host):
            raise ApiError(
                "REPOSITORY_HOST_NOT_ALLOWED",
                f"This deployment does not allow repositories on {host}",
                status.HTTP_400_BAD_REQUEST,
            )
        if not _REPO_PATH.match(path):
            raise ApiError(
                "INVALID_ARGUMENT",
                "path must look like owner/repository",
                status.HTTP_400_BAD_REQUEST,
            )
        if not _BRANCH.match(default_branch):
            raise ApiError(
                "INVALID_ARGUMENT",
                "default_branch may not start with '-' and may only contain "
                "letters, digits, '.', '_', '-' and '/'",
                status.HTTP_400_BAD_REQUEST,
            )
        existing = (
            await self._session.execute(
                select(ProjectRepository).where(
                    ProjectRepository.project_id == project.id,
                    ProjectRepository.host == host,
                    ProjectRepository.path == path,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ApiError(
                "REPOSITORY_EXISTS",
                "That repository is already registered for this project",
                status.HTTP_409_CONFLICT,
            )
        row = ProjectRepository(
            id=uuid.uuid4(),
            project_id=project.id,
            scheme=scheme,
            host=host,
            path=path,
            default_branch=default_branch,
            label=label,
            created_by=actor_id,
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor_id,
            metadata={
                "project_id": str(project.id),
                "repository_id": str(row.id),
                # The identity, which is all there is — there is no credential here to
                # leave out.
                "repository": f"{scheme}://{host}/{path}",
            },
        )
        return row

    async def delete(self, *, repository: ProjectRepository, actor_id: uuid.UUID) -> None:
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor_id,
            metadata={
                "project_id": str(repository.project_id),
                "repository_id": str(repository.id),
                "removed": True,
            },
        )
        await self._session.delete(repository)
        await self._session.flush()


def clone_url(repository: ProjectRepository) -> str:
    """The URL the daemon is handed, assembled from the three columns.

    Assembled at the last moment and never stored, so there is no field anywhere that
    *could* hold a credential. `ssh` uses the `ssh://` form rather than the scp-like
    `git@host:path`, because the latter is ambiguous with a local path and this string
    goes straight into a closed argv table.
    """
    path = repository.path.lstrip("/")
    if repository.scheme == "ssh":
        return f"ssh://git@{repository.host}/{path}"
    return f"https://{repository.host}/{path}"
