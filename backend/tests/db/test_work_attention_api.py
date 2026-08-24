"""Phase A's query, phase B's snapshot, and the one pairing that has to hold (PX-24).

Three properties, and the third is the reason this file exists rather than the other
two:

* **phase A produces the six database-answerable levels** from one page of cards, with
  the effective process resolved once for the project rather than once per card;
* **the board and the console agree about every queued run.** `resolve_runtime_signals`
  and `RunService.resolve_waiting_reason` are two implementations of the same four
  predicates — one for a page, one for a card — and the failure they exist to prevent is
  the console saying "no machine has `docker`" next to a card the board calls "waiting".

The pure half — the priority order and the four state faces — is in
`tests/test_work_attention.py` and needs no database.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_utc
from app.db.models import (
    AgentRunner,
    Node,
    Project,
    Role,
    Task,
    TaskDependency,
    TaskRun,
    User,
    VerificationReport,
)
from app.security.passwords import hash_password
from app.services.runs import RunService
from app.services.work.attention import (
    ASSIGNED_RUNNER_OFFLINE,
    DEPENDENCY_BLOCKED,
    NO_ELIGIBLE_RUNNER,
    RUN_FAILED,
    VERIFICATION_FAILED,
    WAITING_FOR_YOUR_INPUT,
    derive_attention,
    level_for_waiting_kind,
)
from app.services.work.rows import WorkRowReader
from app.settings import Settings

pytestmark = pytest.mark.asyncio

# The same fixed key `conftest.projects_enabled` installs. Imported by value rather than
# from the module, because `tests/db` is not a package and a relative import fails.
TEST_MASTER_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


async def _owner(session: AsyncSession) -> User:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    username = f"work-{uuid.uuid4().hex[:8]}"
    user = User(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        password_hash=hash_password("pw"),
        role_id=role.id,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User) -> Project:
    slug = f"work-{uuid.uuid4().hex[:8]}"
    project = Project(
        id=uuid.uuid4(),
        name=slug,
        slug=slug,
        status="active",
        owner_user_id=owner.id,
        next_card_seq=1,
    )
    session.add(project)
    await session.flush()
    return project


async def _card(session: AsyncSession, project: Project, ref: str, **fields: object) -> Task:
    defaults: dict[str, object] = {"stage": "ready", "source": "none", "delivery": "none"}
    defaults.update(fields)
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref=ref,
        title=ref,
        **defaults,  # type: ignore[arg-type]
    )
    session.add(task)
    await session.flush()
    return task


async def _runner(
    session: AsyncSession,
    *,
    runtimes: list[str] | None = None,
    labels: list[str] | None = None,
    run_untagged: bool = True,
    accept_secrets: bool = True,
) -> AgentRunner:
    name = f"runner-{uuid.uuid4().hex[:8]}"
    node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
    session.add(node)
    await session.flush()
    runner = AgentRunner(
        id=uuid.uuid4(),
        node_id=node.id,
        name=name,
        runtimes=["claude"] if runtimes is None else runtimes,
        labels=labels or [],
        run_untagged=run_untagged,
        accept_secrets=accept_secrets,
    )
    session.add(runner)
    await session.flush()
    return runner


async def _run(session: AsyncSession, task: Task, *, status: str, **fields: object) -> TaskRun:
    defaults: dict[str, object] = {"seq": 1, "attempt": 1, "source_kind": "none"}
    defaults.update(fields)
    run = TaskRun(
        id=uuid.uuid4(),
        task_id=task.id,
        project_id=task.project_id,
        status=status,
        **defaults,  # type: ignore[arg-type]
    )
    session.add(run)
    await session.flush()
    return run


def _by_ref(rows: list, ref: str):
    return next(row for row in rows if row.card_ref == ref)


# --- phase A ------------------------------------------------------------------ #


async def test_phase_a_answers_the_six_database_levels_in_one_page(session: AsyncSession) -> None:
    """One reader call, six cards, six different reasons a person is needed."""
    owner = await _owner(session)
    project = await _project(session, owner)

    stalled = await _card(
        session,
        project,
        "TK-1",
        stage="implementing",
        open_question_count=1,
        waiting_for_actor="human",
    )
    await _run(session, stalled, status="waiting_for_input")

    await _card(session, project, "TK-2", stage="verify")

    bad_report = await _card(session, project, "TK-3", stage="implementing")
    session.add(
        VerificationReport(
            id=uuid.uuid4(),
            task_id=bad_report.id,
            project_id=project.id,
            result="failed",
            source="machine_verified",
            reported_by_kind="agent",
            reported_at=now_utc(),
        )
    )

    failed = await _card(session, project, "TK-4", stage="implementing")
    await _run(session, failed, status="failed")

    blocker = await _card(session, project, "TK-5", stage="ready")
    blocked = await _card(session, project, "TK-6", stage="ready")
    session.add(TaskDependency(task_id=blocked.id, depends_on_task_id=blocker.id))
    await session.flush()

    rows, runtime = await WorkRowReader(session).for_project(project)
    assert runtime is None, "no registry was offered, so phase B must not claim an answer"
    attention = {row.card_ref: derive_attention(row, runtime) for row in rows}

    assert attention["TK-1"].primary == WAITING_FOR_YOUR_INPUT
    assert attention["TK-2"].primary == "pending_human_approval"
    assert attention["TK-3"].primary == VERIFICATION_FAILED
    assert attention["TK-4"].primary == RUN_FAILED
    assert attention["TK-6"].primary == DEPENDENCY_BLOCKED
    assert attention["TK-5"].primary is None
    # Levels 5 and 6 are absent rather than false when nobody consulted the registry.
    assert all(not dto.runtime_available for dto in attention.values())


async def test_blocking_refs_are_capped_and_name_the_cards(session: AsyncSession) -> None:
    """Three references, not the count and not all of them (D108).

    The cap is on the row rather than on the renderer: at 200 cards an uncapped array is
    the item that makes the size budget unpredictable.
    """
    owner = await _owner(session)
    project = await _project(session, owner)
    blocked = await _card(session, project, "TK-1")
    for index in range(5):
        blocker = await _card(session, project, f"TK-1{index}")
        session.add(TaskDependency(task_id=blocked.id, depends_on_task_id=blocker.id))
    await session.flush()

    rows, _ = await WorkRowReader(session).for_project(project)
    row = _by_ref(rows, "TK-1")
    assert row.blocking_count == 5
    assert len(row.blocking_refs) == 3
    assert set(row.blocking_refs) <= {f"TK-1{index}" for index in range(5)}


async def test_a_finished_blocker_stops_blocking(session: AsyncSession) -> None:
    owner = await _owner(session)
    project = await _project(session, owner)
    blocked = await _card(session, project, "TK-1")
    blocker = await _card(session, project, "TK-2", stage="done")
    session.add(TaskDependency(task_id=blocked.id, depends_on_task_id=blocker.id))
    await session.flush()

    rows, _ = await WorkRowReader(session).for_project(project)
    row = _by_ref(rows, "TK-1")
    assert row.blocking_count == 0
    assert row.blocking_refs == ()
    assert derive_attention(row, None).primary is None


async def test_the_newest_run_and_the_newest_report_are_the_ones_that_count(
    session: AsyncSession,
) -> None:
    """A retry that succeeded clears a failure; a passing report clears a failing one."""
    owner = await _owner(session)
    project = await _project(session, owner)
    card = await _card(session, project, "TK-1", stage="implementing")
    # Explicit timestamps on both: `queued_at`'s server default is the *transaction*
    # clock, so two rows inserted in one transaction get the same value and the
    # tiebreak would decide the test.
    earlier = now_utc() - timedelta(hours=1)
    later = now_utc()
    await _run(session, card, status="failed", seq=1, queued_at=earlier)
    await _run(session, card, status="succeeded", seq=2, queued_at=later)
    session.add(
        VerificationReport(
            id=uuid.uuid4(),
            task_id=card.id,
            project_id=project.id,
            result="failed",
            source="machine_verified",
            reported_by_kind="agent",
            reported_at=earlier,
        )
    )
    session.add(
        VerificationReport(
            id=uuid.uuid4(),
            task_id=card.id,
            project_id=project.id,
            result="passed",
            source="machine_verified",
            reported_by_kind="agent",
            reported_at=later,
        )
    )
    await session.flush()

    rows, _ = await WorkRowReader(session).for_project(project)
    row = _by_ref(rows, "TK-1")
    assert row.latest_run_status == "succeeded"
    assert row.latest_verification_result == "passed"
    assert derive_attention(row, None).signals == ()


async def test_the_legacy_blocked_stage_projects_onto_ready_and_blocked(
    session: AsyncSession,
) -> None:
    """Wave 0 has no `is_blocked` column, so the stage carries the whole answer (D102)."""
    owner = await _owner(session)
    project = await _project(session, owner)
    await _card(session, project, "TK-1", stage="blocked")
    rows, _ = await WorkRowReader(session).for_project(project)
    row = _by_ref(rows, "TK-1")
    assert (row.lifecycle, row.is_blocked, row.stage) == ("ready", True, "blocked")


# --- phase B, and the pairing --------------------------------------------------- #


async def test_board_and_console_agree_on_every_queued_run(session: AsyncSession) -> None:
    """**The most important consistency test in this phase** (plan/26/03 §2).

    Four queued runs covering the four shapes phase B can produce, each resolved twice:
    once for the whole page (`resolve_runtime_signals`) and once per card
    (`RunService.resolve_waiting_reason`). The two must map to the same attention level.

    Written as a comparison of *levels* rather than of the console's `kind` strings, so
    the mapping between the two vocabularies is exercised rather than restated.
    """
    owner = await _owner(session)
    project = await _project(session, owner)
    online = await _runner(session, labels=["docker"])
    offline = await _runner(session)
    tagged_only = await _runner(session, labels=["gpu"], run_untagged=False)

    # 1. Nothing wrong: an online untagged runner can take it.
    plain = await _card(session, project, "TK-1")
    await _run(session, plain, status="queued", runtime="claude")

    # 2. Assigned to a machine that is not connected.
    assigned = await _card(session, project, "TK-2")
    await _run(session, assigned, status="queued", runtime="claude", assigned_runner_id=offline.id)

    # 3. Asks for a tag no online machine has.
    tagged = await _card(session, project, "TK-3", required_labels=["arm64"])
    await _run(session, tagged, status="queued", runtime="claude")

    # 4. Asks for a runtime nobody offers.
    exotic = await _card(session, project, "TK-4")
    await _run(session, exotic, status="queued", runtime="codex")
    await session.flush()

    connected = {online.node_id, tagged_only.node_id}

    def is_online(node_id: uuid.UUID) -> bool:
        return node_id in connected

    reader = WorkRowReader(session)
    rows, runtime = await reader.for_project(project, is_online=is_online)
    assert runtime is not None

    runs = (
        await session.execute(
            sa.select(TaskRun).where(TaskRun.project_id == project.id, TaskRun.status == "queued")
        )
    ).scalars()
    service = RunService(
        session,
        settings=Settings(
            projects_enabled=True,
            agent_runs_enabled=True,
            secret_master_key=TEST_MASTER_KEY,
        ),
    )
    for run in runs:
        console = await service.resolve_waiting_reason(run, is_online=is_online)
        assert runtime.level_for(run.task_id) == level_for_waiting_kind(console.kind), (
            f"board and console disagree about {run.task_id}: "
            f"{runtime.level_for(run.task_id)} vs {console.kind}"
        )

    by_ref = {row.card_ref: row for row in rows}
    assert derive_attention(by_ref["TK-1"], runtime).primary is None
    assert derive_attention(by_ref["TK-2"], runtime).primary == ASSIGNED_RUNNER_OFFLINE
    assert derive_attention(by_ref["TK-3"], runtime).primary == NO_ELIGIBLE_RUNNER
    assert derive_attention(by_ref["TK-4"], runtime).primary == NO_ELIGIBLE_RUNNER


async def test_phase_b_only_looks_at_the_queued_set(session: AsyncSession) -> None:
    """D92's cost claim: the work tracks the dispatch queue, not the board.

    A card that is running, finished or never dispatched is not in `resolved` at all —
    absence is what makes "we did not look at this one" representable.
    """
    owner = await _owner(session)
    project = await _project(session, owner)
    for index in range(20):
        await _card(session, project, f"TK-{index}")
    queued_card = await _card(session, project, "TK-Q")
    await _run(session, queued_card, status="queued", runtime="claude")
    running_card = await _card(session, project, "TK-R")
    await _run(session, running_card, status="running", runtime="claude")
    await session.flush()

    _, runtime = await WorkRowReader(session).for_project(project, is_online=lambda _: False)
    assert runtime is not None
    assert set(runtime.resolved) == {queued_card.id}
