"""`blocked` stops being a stage, and the three writers that made it a lie (`HD-06`).

ADR 0040's amendment, migrations `0045`/`0046`. Three groups:

* **the value set is closed**, in the database and in the ORM — they disagreed for three
  phases and nothing said so;
* **no writer sets the stage any more** — asserted over the whole package, because the
  gate that watched one file is precisely how two of the three survived;
* **`is_blocked` can be read directly now**, which is the sentence `models.py` carried a
  warning against since `beta.1`.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
import sqlalchemy as sa

from app.db.models import Project, Role, Task, User
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


async def _project(session) -> tuple[uuid.UUID, uuid.UUID]:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    name = f"sunset-{uuid.uuid4().hex[:8]}"
    user = User(
        id=uuid.uuid4(),
        username=name,
        display_name=name,
        password_hash=hash_password("pw-12345678"),
        role_id=role.id,
    )
    session.add(user)
    await session.flush()
    project = Project(id=uuid.uuid4(), name=name, slug=name, owner_user_id=user.id)
    session.add(project)
    await session.flush()
    return user.id, project.id


# --- the value set is closed, on both sides -------------------------------- #


async def test_the_database_refuses_stage_blocked(session) -> None:
    """`0046`, asserted where it matters: at the write.

    Not "the constraint exists" — a constraint whose definition drifted would still exist.
    """
    _user, project_id = await _project(session)
    session.add(
        Task(
            id=uuid.uuid4(),
            project_id=project_id,
            card_ref="SUN-1",
            title="a card",
            stage="blocked",
            source="none",
            delivery="none",
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        await session.flush()


async def test_the_model_and_the_database_agree_about_the_value_set(session) -> None:
    """They did **not**, from `0023` until now.

    `ck_tasks_stage` lived only in a migration, so "which values may `stage` hold" was a
    question you answered by reading `0023`. The read model, the process definition and
    every future `WHERE stage = ...` each carried their own copy of the answer.
    """
    from app.db.models import Task as TaskModel

    declared = [
        str(item.sqltext)
        for item in TaskModel.__table__.constraints
        if isinstance(item, sa.CheckConstraint)
    ]
    stage_check = next(text for text in declared if "stage IN" in text)
    assert "'blocked'" not in stage_check

    live = (
        await session.execute(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'tasks'::regclass AND conname = 'ck_tasks_stage'"
            )
        )
    ).scalar_one()
    assert "blocked" not in live
    for stage in ("backlog", "ready", "implementing", "verify", "done"):
        assert stage in live
        assert stage in stage_check


# --- nobody writes the stage any more --------------------------------------- #


async def test_no_module_in_the_package_sets_stage_to_blocked() -> None:
    """**The whole package**, which is the difference that matters.

    `GATE-DV-SINGLE-DONE-PATH` scans `services/runs.py` for `'done'`. Two of the three
    writers this replaces were in `services/run_reaper.py`, outside its view, and they sat
    there through V2.4, V2.5 and `beta.1`. A gate scoped to one file protects that file,
    not the invariant.
    """
    import pathlib

    import app

    root = pathlib.Path(app.__file__).parent
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if '.stage = "blocked"' in path.read_text(encoding="utf-8")
        or ".stage = 'blocked'" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"these still write stage='blocked': {offenders}"


async def test_the_three_former_writers_now_say_why() -> None:
    """Replacing the stage with a boolean is only half of it.

    A card that is blocked with `blocking_reason = NULL` is worse than one on a `blocked`
    stage: the stage at least said *something*. Each of the three writers knows its own
    reason, so each supplies one.
    """
    from app.services import run_reaper, runs
    from app.services.work.projection import BLOCKING_REASONS

    for module in (run_reaper, runs):
        source = inspect.getsource(module)
        assert "is_blocked = True" in source
        for line in source.splitlines():
            if "blocking_reason = " in line and "COALESCE" not in line:
                value = line.split("=", 1)[1].strip().strip('"')
                assert value in BLOCKING_REASONS, f"{value} is not a blocking reason"


async def test_run_failed_is_a_real_reason_rather_than_unknown() -> None:
    """`unknown` means *the derivation could not tell*, and here it could.

    Collapsing a known cause into `unknown` lengthens the ambiguous report for a reason
    nothing records — the exact defect `plan/26/02` §5.2 removed two derivation rules to
    avoid.
    """
    from app.services.work.projection import BLOCKING_REASONS

    assert "run_failed" in BLOCKING_REASONS


# --- the column can be read again ------------------------------------------- #


async def test_is_blocked_is_now_the_whole_truth(session) -> None:
    """The sentence `models.py` warned against since `beta.1`.

    Its comment read: "**Anyone reading this column directly is wrong** about the cards
    the reaper touched." That was true while three writers set a stage instead. It is the
    thing `HD-06` repays, so it is asserted rather than assumed.
    """
    _user, project_id = await _project(session)
    card = Task(
        id=uuid.uuid4(),
        project_id=project_id,
        card_ref="SUN-2",
        title="a card",
        stage="ready",
        source="none",
        delivery="none",
        is_blocked=True,
        blocking_reason="run_failed",
    )
    session.add(card)
    await session.flush()

    direct = (
        await session.execute(
            sa.select(Task.is_blocked, Task.blocking_reason).where(Task.id == card.id)
        )
    ).one()
    assert direct.is_blocked is True
    assert direct.blocking_reason == "run_failed"

    from app.services.work.projection import project_is_blocked

    assert project_is_blocked(card.stage, card.is_blocked) is True
