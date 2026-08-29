"""What migration `0041`/`0042` promised, asserted against a real PostgreSQL (`KN-02`).

These are constraint tests, not feature tests. Every one of them guards a property that
the service layer is *also* going to enforce, and that is the point: the service layer
is where the next contributor writes a new code path, and a constraint is what makes a
forgotten check fail loudly instead of producing a row that no query can explain.

Three of them assert something the database does **not** do, which is the harder kind
to remember to write: a stale version must not overwrite a newer one, a chunk must not
exist without a search document, and deleting a run must take its context packs while
leaving the card's conversation alone.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.clock import now_utc
from app.db.models import (
    ContextPack,
    KnowledgeChunk,
    KnowledgeJob,
    KnowledgeSource,
    Project,
    Role,
    Task,
    TaskKnowledgePin,
    TaskMessage,
    TaskRun,
    User,
)
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


async def _project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """A user and a project, committed to the session's open transaction."""
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    name = f"kn-{uuid.uuid4().hex[:8]}"
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


def _source(project_id: uuid.UUID, **over) -> KnowledgeSource:
    now = now_utc()
    fields = {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "source_type": "ticket",
        "source_external_id": f"task:{uuid.uuid4()}",
        "source_version": "v1",
        "authority": "discussion",
        "checksum": "0" * 64,
        "title": "a card",
        "occurred_at": now,
        "source_updated_at": now,
    }
    fields.update(over)
    return KnowledgeSource(**fields)


async def test_pg_trgm_is_installed(session):
    """`0041`'s one non-additive line, asserted rather than assumed.

    Without it `ix_knowledge_chunks_trgm` cannot exist, and the trigram channel — the
    half of retrieval that finds `CV-05`, a commit SHA and a typo — silently is not
    there.
    """
    assert (await session.execute(sa.text("SELECT 'cliora' % 'clora'"))).scalar() is not None
    installed = (
        await session.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
    ).scalar()
    assert installed == 1


async def test_pg_trgm_is_a_trusted_extension(session):
    """Which is what decides whether a managed database can run `0041` at all.

    `plan/25` carried "Railway usually gives a non-superuser, **必須實測**" as an open exit
    condition for six weeks, on the assumption that `CREATE EXTENSION` needs a superuser.
    **It does not, for this extension.** `pg_trgm` is marked `trusted` in its control file,
    and since PostgreSQL 13 a trusted extension may be installed by any role holding
    `CREATE` **on the database** — superuser is not the predicate.

    Measured on 2026-08-28 (`plan/27` `HD-00`) against three roles: the database owner,
    who is not a superuser, installs it successfully; a role without `CREATE` on the
    database gets `0041`'s second refusal and the documented one-line remedy fixes it
    (`docs/deployment-railway.md`).

    Asserted here rather than left in prose because it is the sentence a future reader
    would otherwise re-derive under deployment pressure. If a PostgreSQL upgrade ever
    un-trusts it, the deployment guide's advice becomes wrong and this is what says so.
    """
    # `pg_available_extension_versions`, not `pg_available_extensions` — only the former
    # carries `trusted`, and the latter is the one whose name suggests it would.
    trusted = (
        await session.execute(
            sa.text(
                "SELECT bool_and(trusted) FROM pg_catalog.pg_available_extension_versions "
                "WHERE name = 'pg_trgm'"
            )
        )
    ).scalar()
    assert trusted is True


async def test_knowledge_is_off_by_default(session):
    _user, project_id = await _project(session)
    project = await session.get(Project, project_id)
    assert project.knowledge_enabled is False
    assert project.knowledge_settings == {}


async def test_a_source_version_is_unique_within_a_project(session):
    _user, project_id = await _project(session)
    first = _source(project_id)
    session.add(first)
    await session.flush()
    session.add(
        _source(
            project_id,
            source_external_id=first.source_external_id,
            source_version=first.source_version,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_the_same_external_id_may_have_several_versions(session):
    _user, project_id = await _project(session)
    external = f"task:{uuid.uuid4()}"
    for version in ("v1", "v2", "v3"):
        session.add(_source(project_id, source_external_id=external, source_version=version))
    await session.flush()
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeSource)
            .where(KnowledgeSource.source_external_id == external)
        )
    ).scalar()
    assert count == 3


async def test_a_mistyped_source_type_is_refused(session):
    """The reason `ActivityService.record` refuses an unknown kind, one layer down."""
    _user, project_id = await _project(session)
    session.add(_source(project_id, source_type="tickets"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_mistyped_authority_is_refused(session):
    _user, project_id = await _project(session)
    session.add(_source(project_id, authority="trusted"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_an_older_version_does_not_overwrite_a_newer_one(session):
    """The upsert's `WHERE excluded.source_updated_at > …`, at the SQL level.

    Also asserts the trap that goes with it: when the comparison is false the statement
    updates nothing and `RETURNING` yields **no row**, which reads at the call site like
    a failed insert. Any caller that treats an empty `RETURNING` as an error will
    misreport every out-of-order delivery.
    """
    _user, project_id = await _project(session)
    external = f"task:{uuid.uuid4()}"
    newer = now_utc()
    older = newer - timedelta(hours=1)
    session.add(
        _source(
            project_id,
            source_external_id=external,
            source_updated_at=newer,
            title="the newer one",
        )
    )
    await session.flush()

    stmt = pg_insert(KnowledgeSource.__table__).values(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type="ticket",
        source_external_id=external,
        source_version="v1",
        authority="discussion",
        checksum="1" * 64,
        title="the older one",
        occurred_at=older,
        source_updated_at=older,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_knowledge_sources_identity",
        set_={"title": stmt.excluded.title, "source_updated_at": stmt.excluded.source_updated_at},
        where=KnowledgeSource.__table__.c.source_updated_at < stmt.excluded.source_updated_at,
    ).returning(KnowledgeSource.__table__.c.id)
    returned = (await session.execute(stmt)).scalars().all()

    assert returned == [], "an out-of-order delivery must return no row, not raise"
    title = (
        await session.execute(
            sa.select(KnowledgeSource.title).where(KnowledgeSource.source_external_id == external)
        )
    ).scalar_one()
    assert title == "the newer one"


async def test_a_chunk_cannot_exist_without_a_search_document(session):
    """`NOT NULL` on a column nothing in the database computes.

    It is what makes "insert a chunk without going through `services/knowledge/`" fail
    rather than produce a row that no query will ever match.
    """
    _user, project_id = await _project(session)
    source = _source(project_id)
    session.add(source)
    await session.flush()
    session.add(
        KnowledgeChunk(
            id=uuid.uuid4(),
            source_id=source.id,
            project_id=project_id,
            chunk_key="0000",
            content="anything",
            content_hash="2" * 64,
            token_count=1,
            valid_from=now_utc(),
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_one_pending_job_per_entity(session):
    """The partial unique index: five edits in one second are one job.

    Safe only because a job holds an entity key rather than content — the worker
    re-reads, so collapsing duplicates loses nothing (ADR 0038 sec 3.2).
    """
    _user, project_id = await _project(session)
    values = {
        "project_id": project_id,
        "source_type": "ticket",
        "external_id": "task:abc",
        "state": "pending",
    }
    for _ in range(5):
        # `index_where` is required, not optional: the index is partial, and without the
        # predicate PostgreSQL cannot tell which index the conflict target names.
        stmt = pg_insert(KnowledgeJob.__table__).values(id=uuid.uuid4(), **values)
        await session.execute(
            stmt.on_conflict_do_nothing(
                index_elements=["project_id", "source_type", "external_id"],
                index_where=sa.text("state = 'pending'"),
            )
        )
    pending = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeJob)
            .where(KnowledgeJob.project_id == project_id, KnowledgeJob.state == "pending")
        )
    ).scalar()
    assert pending == 1


async def test_a_done_job_does_not_block_the_next_pending_one(session):
    """The index is partial, so history does not stop the same entity being queued again."""
    _user, project_id = await _project(session)
    session.add(
        KnowledgeJob(
            id=uuid.uuid4(),
            project_id=project_id,
            source_type="ticket",
            external_id="task:abc",
            state="done",
        )
    )
    await session.flush()
    session.add(
        KnowledgeJob(
            id=uuid.uuid4(),
            project_id=project_id,
            source_type="ticket",
            external_id="task:abc",
            state="pending",
        )
    )
    await session.flush()


async def test_deleting_a_project_removes_every_knowledge_row(session):
    """ADR 0038 sec 6's cascade, asserted as a constraint.

    `projects` has no delete path today — only archival — so this exercises the
    constraint directly. It is written now so that it is already true on the day a
    delete path exists.
    """
    _user, project_id = await _project(session)
    source = _source(project_id)
    session.add(source)
    await session.flush()
    session.add(
        KnowledgeChunk(
            id=uuid.uuid4(),
            source_id=source.id,
            project_id=project_id,
            chunk_key="0000",
            content="text",
            content_hash="3" * 64,
            token_count=1,
            search_document=sa.func.to_tsvector("simple", "text"),
            valid_from=now_utc(),
        )
    )
    session.add(
        KnowledgeJob(
            id=uuid.uuid4(),
            project_id=project_id,
            source_type="ticket",
            external_id="task:x",
            state="pending",
        )
    )
    await session.flush()

    await session.execute(sa.delete(Project).where(Project.id == project_id))
    await session.flush()

    for model in (KnowledgeSource, KnowledgeChunk, KnowledgeJob):
        remaining = (
            await session.execute(
                sa.select(sa.func.count()).select_from(model).where(model.project_id == project_id)
            )
        ).scalar()
        assert remaining == 0, model.__tablename__


async def test_deleting_a_run_takes_its_context_packs_and_leaves_the_conversation(session):
    """The two halves of ADR 0038 sec 6's taxonomy, in one assertion.

    A context pack is a diagnostic and shares the run's lifetime; a message is product
    data and outlives every execution that produced it. If these ever cascade the same
    way, one of the two is wrong.
    """
    user_id, project_id = await _project(session)
    task = Task(
        id=uuid.uuid4(),
        project_id=project_id,
        card_ref="KN-1",
        title="a card",
        created_by=user_id,
    )
    session.add(task)
    await session.flush()
    run = TaskRun(id=uuid.uuid4(), task_id=task.id, project_id=project_id, seq=1, status="queued")
    session.add(run)
    await session.flush()
    session.add(
        TaskMessage(
            id=uuid.uuid4(),
            task_id=task.id,
            run_id=run.id,
            author_kind="user",
            author_user_id=user_id,
            body="said something",
            kind="comment",
            conversation_seq=1,
        )
    )
    session.add(
        ContextPack(
            id=uuid.uuid4(),
            run_id=run.id,
            task_id=task.id,
            project_id=project_id,
            source_manifest=[],
            budget_json={},
            omitted_json=[],
        )
    )
    await session.flush()

    await session.execute(sa.delete(TaskRun).where(TaskRun.id == run.id))
    await session.flush()

    packs = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(ContextPack)
            .where(ContextPack.task_id == task.id)
        )
    ).scalar()
    messages = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(TaskMessage)
            .where(TaskMessage.task_id == task.id)
        )
    ).scalar()
    assert packs == 0
    assert messages == 1


async def test_two_fetches_write_two_context_packs(session):
    """No unique key on `(run_id, turn_seq)` — deliberately (ADR 0039).

    Two fetches returning different content is exactly the thing that has to stay
    visible, so a second fetch must be a second row rather than an overwrite.
    """
    user_id, project_id = await _project(session)
    task = Task(
        id=uuid.uuid4(), project_id=project_id, card_ref="KN-2", title="c", created_by=user_id
    )
    session.add(task)
    await session.flush()
    run = TaskRun(id=uuid.uuid4(), task_id=task.id, project_id=project_id, seq=1, status="running")
    session.add(run)
    await session.flush()
    for _ in range(2):
        session.add(
            ContextPack(
                id=uuid.uuid4(),
                run_id=run.id,
                task_id=task.id,
                project_id=project_id,
                turn_seq=1,
                source_manifest=[],
                budget_json={},
                omitted_json=[],
            )
        )
    await session.flush()
    count = (
        await session.execute(
            sa.select(sa.func.count()).select_from(ContextPack).where(ContextPack.run_id == run.id)
        )
    ).scalar()
    assert count == 2


async def test_a_pin_survives_its_author(session):
    """`created_by` is SET NULL: a pin is the project's decision, not a person's setting."""
    owner_id, project_id = await _project(session)
    # A second person, who owns nothing: `projects.owner_user_id` is ON DELETE RESTRICT,
    # so the project's owner cannot be removed and would test the wrong constraint.
    role = (await session.execute(sa.select(Role).where(Role.name == "Developer"))).scalar_one()
    name = f"kn-{uuid.uuid4().hex[:8]}"
    author = User(
        id=uuid.uuid4(),
        username=name,
        display_name=name,
        password_hash=hash_password("pw-12345678"),
        role_id=role.id,
    )
    session.add(author)
    await session.flush()

    task = Task(
        id=uuid.uuid4(), project_id=project_id, card_ref="KN-3", title="c", created_by=owner_id
    )
    source = _source(project_id)
    session.add_all([task, source])
    await session.flush()
    session.add(
        TaskKnowledgePin(task_id=task.id, source_id=source.id, mode="pin", created_by=author.id)
    )
    await session.flush()

    await session.execute(sa.delete(User).where(User.id == author.id))
    await session.flush()

    pin = (
        await session.execute(
            sa.select(TaskKnowledgePin).where(TaskKnowledgePin.task_id == task.id)
        )
    ).scalar_one()
    assert pin.created_by is None
    assert pin.mode == "pin"


async def test_a_mistyped_pin_mode_is_refused(session):
    user_id, project_id = await _project(session)
    task = Task(
        id=uuid.uuid4(), project_id=project_id, card_ref="KN-4", title="c", created_by=user_id
    )
    source = _source(project_id)
    session.add_all([task, source])
    await session.flush()
    session.add(TaskKnowledgePin(task_id=task.id, source_id=source.id, mode="hide"))
    with pytest.raises(IntegrityError):
        await session.flush()
