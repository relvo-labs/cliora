"""Persistence for epics, user stories, task cards and their dependencies (TK-02/TK-04).

Two queries here carry decisions rather than plumbing:

* :meth:`TaskRepository.allocate_card_ref` is the counter, and it is one statement on
  purpose — the row lock is the whole mechanism (ADR 0028 sec 7);
* :meth:`TaskRepository.reaches` is the cycle check, a recursive walk in the database
  rather than in Python, so it sees rows another transaction has committed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, and_, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Epic, Project, Task, TaskDependency, UserStory


@dataclass(frozen=True, slots=True)
class BoardCard:
    """A card as the board renders it, plus the two counts it needs.

    Not the ORM row: M1 measured a 200-card board at 439 KB with the full card and
    74 KB with this shape, and 500 cards puts the full shape over a megabyte
    (`plan/17/10-…md` §1). Acceptance criteria and gate detail belong to the card
    detail view, and a test asserts they never reappear here.
    """

    task: Task
    owner_name: str | None
    blocking_count: int
    gates_approved_count: int


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- allocation ---------------------------------------------------------------

    async def allocate_card_ref(self, project_id: uuid.UUID, prefix: str) -> str:
        """Take the next number for a project, under the row lock.

        One statement, and `RETURNING next_card_seq - 1` because the column names the
        *next* number rather than the last one taken. `count(*) + 1` would collide
        between two browser tabs, and the reference goes on to name a branch in V2.3.

        Epics, stories and tasks share the counter, so numbers skip. That is the
        decision, not a defect: the reference identifies, it does not count.
        """
        result = await self._session.execute(
            text(
                "UPDATE projects SET next_card_seq = next_card_seq + 1 "
                "WHERE id = :project_id RETURNING next_card_seq - 1"
            ),
            {"project_id": project_id},
        )
        return f"{prefix}-{int(result.scalar_one())}"

    # --- reads --------------------------------------------------------------------

    async def get(self, task_id: uuid.UUID) -> Task | None:
        return await self._session.get(Task, task_id)

    async def get_by_ref(self, project_id: uuid.UUID, card_ref: str) -> Task | None:
        return (
            await self._session.execute(
                select(Task).where(Task.project_id == project_id, Task.card_ref == card_ref)
            )
        ).scalar_one_or_none()

    async def get_epic(self, epic_id: uuid.UUID) -> Epic | None:
        return await self._session.get(Epic, epic_id)

    async def get_story(self, story_id: uuid.UUID) -> UserStory | None:
        return await self._session.get(UserStory, story_id)

    def _board_select(self, project_id: uuid.UUID) -> Select[tuple[Task]]:
        return select(Task).where(Task.project_id == project_id).order_by(Task.updated_at.desc())

    async def board_cards(self, project_id: uuid.UUID) -> list[BoardCard]:
        """Every card in a project, with the two derived counts the board shows.

        The blocking count is computed in one grouped query rather than per card: the
        per-card version is the N+1 that turns a 200-card board from one round trip
        into two hundred and one.
        """
        from app.db.models import User

        rows = (
            await self._session.execute(
                select(Task, User.display_name)
                .join(User, User.id == Task.owner_user_id, isouter=True)
                .where(Task.project_id == project_id)
                .order_by(Task.updated_at.desc(), Task.id.desc())
            )
        ).all()
        blocking = await self.blocking_counts(project_id)
        cards = []
        for task, owner_name in rows:
            gates = task.gates or {}
            cards.append(
                BoardCard(
                    task=task,
                    owner_name=owner_name,
                    blocking_count=blocking.get(task.id, 0),
                    gates_approved_count=sum(1 for value in gates.values() if value),
                )
            )
        return cards

    async def blocking_counts(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """How many unfinished dependencies each card in this project still has."""
        blocked = Task.__table__.alias("blocked")
        blocker = Task.__table__.alias("blocker")
        rows = (
            await self._session.execute(
                select(TaskDependency.task_id, func.count())
                .select_from(TaskDependency)
                .join(blocked, blocked.c.id == TaskDependency.task_id)
                .join(blocker, blocker.c.id == TaskDependency.depends_on_task_id)
                .where(and_(blocked.c.project_id == project_id, blocker.c.stage != "done"))
                .group_by(TaskDependency.task_id)
            )
        ).all()
        return {row[0]: int(row[1]) for row in rows}

    async def unfinished_dependencies(self, task_id: uuid.UUID) -> list[str]:
        """The `card_ref`s still blocking one card, for the refusal message.

        References rather than ids, because the error is read by a person and
        `TASK-3, TASK-7` is the sentence they can act on (FR-TASK-002.AC-02).
        """
        rows = (
            await self._session.execute(
                select(Task.card_ref)
                .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                .where(TaskDependency.task_id == task_id, Task.stage != "done")
                .order_by(Task.card_ref)
            )
        ).scalars()
        return list(rows)

    async def dependencies(self, task_id: uuid.UUID) -> list[Task]:
        rows = (
            await self._session.execute(
                select(Task)
                .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                .where(TaskDependency.task_id == task_id)
                .order_by(Task.card_ref)
            )
        ).scalars()
        return list(rows)

    async def reaches(self, start: uuid.UUID, target: uuid.UUID) -> list[str]:
        """Is `target` reachable from `start` through dependencies? Returns the path.

        A recursive CTE rather than a Python walk: the walk would have to load the
        whole graph first, and it would miss anything another transaction committed in
        between. A project's cards are in the hundreds, so one traversal is enough —
        no scheduling engine required (research/02/03 TK-02).

        Returns the `card_ref` path when a cycle would be created, so the refusal can
        show it, and an empty list when there is none.
        """
        rows = await self._session.execute(
            text(
                """
                -- CAST(...) rather than `:start::uuid`: SQLAlchemy's bind-parameter
                -- parser reads the `::` as the start of another parameter name and
                -- hands PostgreSQL a syntax error.
                WITH RECURSIVE walk(id, path) AS (
                    SELECT CAST(:start AS uuid), ARRAY[CAST(:start AS uuid)]
                  UNION ALL
                    SELECT d.depends_on_task_id, walk.path || d.depends_on_task_id
                    FROM task_dependencies d
                    JOIN walk ON d.task_id = walk.id
                    WHERE NOT d.depends_on_task_id = ANY(walk.path)
                )
                SELECT path FROM walk WHERE id = CAST(:target AS uuid) LIMIT 1
                """
            ),
            {"start": str(start), "target": str(target)},
        )
        path = rows.scalar_one_or_none()
        if not path:
            return []
        refs = (
            await self._session.execute(
                select(Task.id, Task.card_ref).where(Task.id.in_([uuid.UUID(str(x)) for x in path]))
            )
        ).all()
        lookup = {row[0]: row[1] for row in refs}
        return [lookup.get(uuid.UUID(str(node)), str(node)) for node in path]

    async def add_dependency(
        self, *, task_id: uuid.UUID, depends_on: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        self._session.add(
            TaskDependency(task_id=task_id, depends_on_task_id=depends_on, created_by=actor_id)
        )

    async def remove_dependency(self, *, task_id: uuid.UUID, depends_on: uuid.UUID) -> int:
        result = await self._session.execute(
            delete(TaskDependency).where(
                TaskDependency.task_id == task_id,
                TaskDependency.depends_on_task_id == depends_on,
            )
        )
        return int(result.rowcount or 0)

    # --- roadmap ------------------------------------------------------------------

    async def epics(self, project_id: uuid.UUID) -> list[Epic]:
        rows = (
            await self._session.execute(
                select(Epic)
                .where(Epic.project_id == project_id)
                .order_by(Epic.order_index, Epic.card_ref)
            )
        ).scalars()
        return list(rows)

    async def stories(self, project_id: uuid.UUID) -> list[UserStory]:
        rows = (
            await self._session.execute(
                select(UserStory)
                .where(UserStory.project_id == project_id)
                .order_by(UserStory.order_index, UserStory.card_ref)
            )
        ).scalars()
        return list(rows)

    async def tasks(self, project_id: uuid.UUID) -> list[Task]:
        rows = (await self._session.execute(self._board_select(project_id))).scalars()
        return list(rows)

    async def tasks_for_refs(self, project_id: uuid.UUID, refs: list[str]) -> list[Task]:
        rows = (
            await self._session.execute(
                select(Task).where(Task.project_id == project_id, Task.card_ref.in_(refs))
            )
        ).scalars()
        return list(rows)

    # --- writes -------------------------------------------------------------------

    def add(self, entity: Epic | UserStory | Task) -> None:
        self._session.add(entity)

    async def project(self, project_id: uuid.UUID) -> Project | None:
        return await self._session.get(Project, project_id)
