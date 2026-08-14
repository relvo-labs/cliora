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
from app.db.models import AgentRunner, Node, Project, ProjectRepository, Task, TaskRun
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

# Why a runner stopped polling, as the daemon may report it. Closed, and compared
# against rather than stored verbatim: this string is rendered on the Agents page, and
# a node is not a trusted source of console copy.
BLOCKED_REASONS = frozenset({"at_capacity", "waiting_limit", "disk_quota", "disk_low"})

# Fields `PATCH /api/agents/{id}` may set. `runtimes` and `dedicated` are absent on
# purpose: both are the daemon's report about the machine, and letting an administrator
# type them in would make the console show the posture somebody wished for.
#
# **`labels` left this set in V2.3**, and for a stronger version of the same reason.
# While tags were displayed and never compared, editing one was harmless vanity; now
# they decide which machine gets which card, and an edit here would be a second source
# of truth that the node's next `runner.register` silently overwrites. Changing a
# runner's tags means changing that machine's config file (ADR 0029 amendment B5).
# `run_untagged` and `accept_secrets` never enter this set for the same reason.
EDITABLE_RUNNER_FIELDS = frozenset({"name", "enabled", "max_concurrent", "max_waiting"})


# What Central knows how to gate on. Kept beside the register handler rather than
# imported from the contract package, because this is the *server's* view of which
# features it will act on — a node may report one this build does not use yet.
KNOWN_RUNNER_FEATURES = frozenset({"verification", "evidence"})


def _tri_state(value: Any) -> bool:
    """A node's boolean declaration, where **absent means true**.

    Not `bool(payload.get(key))`: that maps a missing key to False, which is the
    tightening direction. A default has to equal the behaviour before the upgrade, and
    a machine that quietly stops claiming anything after one is the hardest kind of
    regression to trace (ADR 0029 amendment B3).
    """
    return value if isinstance(value, bool) else True


def _bounded(value: Any, *, default: int) -> int:
    """A node-reported capacity, clamped rather than trusted.

    The daemon computes these from its own config, but the value arrives over the
    wire; a negative or absurd number would turn one machine's misconfiguration into
    the queue's problem.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(0, min(64, value))


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
    # Cards pinned to this runner. A separate number from `active_runs`, and the one
    # that answers "is this machine a bottleneck": a card can be assigned to a runner
    # for days without ever having produced a run.
    assigned_cards: int = 0


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
        ids = [runner.id for runner, _ in rows]
        counts = await self._run_counts(ids)
        # One extra query for the whole list, not one per runner: the Agents page is a
        # list, and a per-row count is how a list page becomes N+1 queries.
        assigned = await self._assigned_counts(ids)
        return [
            RunnerView(
                runner=runner,
                node=node,
                online=bool(is_online(node.id)),
                active_runs=counts.get((runner.id, "active"), 0),
                waiting_runs=counts.get((runner.id, "waiting"), 0),
                assigned_cards=assigned.get(runner.id, 0),
            )
            for runner, node in rows
        ]

    async def view(self, runner: AgentRunner, *, is_online) -> RunnerView:  # noqa: ANN001
        node = await self._session.get(Node, runner.node_id)
        if node is None:  # pragma: no cover - the FK makes this unreachable
            raise ApiError("NOT_FOUND", "Agent not found", status.HTTP_404_NOT_FOUND)
        counts = await self._run_counts([runner.id])
        assigned = await self._assigned_counts([runner.id])
        return RunnerView(
            runner=runner,
            node=node,
            online=bool(is_online(node.id)),
            active_runs=counts.get((runner.id, "active"), 0),
            waiting_runs=counts.get((runner.id, "waiting"), 0),
            assigned_cards=assigned.get(runner.id, 0),
        )

    async def _assigned_counts(self, runner_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many cards name each runner.

        The plan calls this out as the easiest number to leave off the page, and the
        reason is that it is the only one that shows a *pinned* machine: a card can sit
        with `assigned_runner_id` set for days and never appear in `active_runs`, so a
        console that shows only occupancy makes an over-subscribed runner look idle.
        """
        if not runner_ids:
            return {}
        rows = (
            await self._session.execute(
                select(Task.assigned_runner_id, func.count())
                .where(
                    Task.assigned_runner_id.in_(runner_ids),
                    # Only cards still waiting on the machine. A finished card that
                    # happens to name this runner is history, and counting it would
                    # make every runner look permanently over-subscribed.
                    Task.stage != "done",
                )
                .group_by(Task.assigned_runner_id)
            )
        ).all()
        return {runner_id: int(count) for runner_id, count in rows}

    async def record_pressure(self, node_id: uuid.UUID, payload: Any) -> None:
        """Take the `runner` object off a heartbeat, if there is one.

        Three shapes arrive here and they mean three different things:

        * **absent** — this node is not a runner (or is running agentd 0.8.x). Nothing
          is written, so a node that leaves runner mode keeps its last known figures
          rather than having them silently zeroed;
        * **present, no `blocked_reason`** — a runner that is polling normally. The
          stored reason is cleared, which is the case that would rot if this only ever
          wrote non-empty values: a runner that filled its disk in March would still
          read 「磁碟用盡」 in June;
        * **present, with a reason** — stored, and the Agents page says which of the
          three things is happening instead of showing the machine as offline.

        Everything here is a report about the machine, so nothing is trusted as a
        number: a negative or absurd byte count is dropped rather than displayed.
        """
        if not isinstance(payload, dict):
            return
        runner = await self.for_node(node_id)
        if runner is None:
            return
        reason = payload.get("blocked_reason")
        runner.blocked_reason = reason if reason in BLOCKED_REASONS else None
        used, quota = payload.get("disk_used_bytes"), payload.get("disk_quota_bytes")
        if isinstance(used, int) and not isinstance(used, bool) and used >= 0:
            runner.disk_used_bytes = used
        if isinstance(quota, int) and not isinstance(quota, bool) and quota > 0:
            runner.disk_quota_bytes = quota
        runner.reported_at = now_utc()

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

    async def register(self, node_id: uuid.UUID, payload: dict[str, Any]) -> AgentRunner:
        """Upsert the one runner row for a node, from `runner.register`.

        Everything here is the machine's report about itself, and none of it is
        editable through the API — which is the same posture `node.register` already
        takes for `image_upload` and the codex sandbox flag (ADR 0023 D3).

        A node whose CLIs are installed but too old registers **successfully with an
        empty `runtimes`**, rather than failing. A failed registration reads as "the
        machine is broken"; an empty set plus the reason on the Agents page reads as
        what it is (ADR 0029 sec 7).

        `enabled` is deliberately *not* taken from the payload: whether a runner may
        take work is an administrator's decision, and letting a re-registration reset
        it would mean a daemon restart silently re-enabling something switched off.
        """
        runtimes = payload.get("runtimes")
        labels = payload.get("labels")
        runner = await self.for_node(node_id)
        node = await self._session.get(Node, node_id)
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            name = node.name if node is not None else str(node_id)
        runtimes_value = (
            sorted({item for item in runtimes if isinstance(item, str)})
            if isinstance(runtimes, list)
            else []
        )
        features = payload.get("features")
        features = features if isinstance(features, list) else []
        labels_value = (
            sorted({item for item in labels if isinstance(item, str)})
            if isinstance(labels, list)
            else []
        )
        values: dict[str, Any] = {
            "name": name[:128],
            "runtimes": runtimes_value,
            "labels": labels_value,
            # Absent means **true** for both, matching the column defaults, so a daemon
            # that predates V2.3 behaves exactly as it did. Note this is not
            # `bool(payload.get(...))`: that maps a missing key to False, which is the
            # tightening direction, and a machine that silently stops claiming anything
            # after an upgrade is the hardest kind of regression to trace back
            # (ADR 0029 amendment B3).
            "run_untagged": _tri_state(payload.get("run_untagged")),
            "accept_secrets": _tri_state(payload.get("accept_secrets")),
            # **Not `_tri_state`, and not permissive**: an absent list means the node
            # supports nothing new, because a support flag's "before the upgrade" value
            # is "cannot" (ADR 0029 amendment C). Unknown strings are dropped rather
            # than stored — the wire enum already rejects them, and storing one would
            # let a typo look like a capability.
            "features": sorted(
                {item for item in (features or []) if item in KNOWN_RUNNER_FEATURES}
            ),
            "max_concurrent": _bounded(payload.get("max_concurrent"), default=1),
            "max_waiting": _bounded(payload.get("max_waiting"), default=5),
            "dedicated": bool(payload.get("dedicated", False)),
        }
        if runner is None:
            runner = AgentRunner(id=uuid.uuid4(), node_id=node_id, **values)
            self._session.add(runner)
        else:
            for field, value in values.items():
                setattr(runner, field, value)
            runner.last_registered_at = now_utc()
        await self._session.flush()
        await self._audit.record(
            audit_actions.AGENT_REGISTER,
            user_id=None,
            node_id=node_id,
            metadata={
                "runner_id": str(runner.id),
                "runtimes": runtimes_value,
                # Recorded because it is the one condition of "dedicated runner" the
                # platform can check, and because a node that stops being dedicated
                # should leave a trace (ADR 0031 sec 6).
                "dedicated": bool(values["dedicated"]),
            },
        )
        return runner

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
