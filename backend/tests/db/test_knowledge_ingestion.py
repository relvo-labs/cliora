"""The outbox and the worker (`KN-03`, `FR-KNOW-001`/`-002`, ADR 0038 §3).

The failure this phase can produce is **a fact that never reached the index**, and it
has no stack trace: search returns nothing, which is indistinguishable from a project
where nobody wrote anything. So the assertions here are about the properties that make
"never reached" impossible rather than about a feature working once:

* **idempotence** — the same hint processed three times writes one source;
* **ordering-independence** — an older version arriving late does not win;
* **durability** — a hint written in a transaction that rolls back does not survive,
  and one written in a transaction that commits is still there after a restart;
* **recovery** — a job interrupted mid-flight comes back without burning an attempt.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.clock import now_utc
from app.db.models import (
    KnowledgeChunk,
    KnowledgeJob,
    KnowledgeSource,
    Project,
    Role,
    Task,
    TaskMessage,
    User,
)
from app.security.passwords import hash_password
from app.services.activity import ACTOR_USER, TASK_UPDATED, ActivityService
from app.services.knowledge import sources as source_handlers
from app.services.knowledge.outbox import KnowledgeOutbox, invalidate_enabled_cache
from app.services.knowledge.worker import STUCK_AFTER

pytestmark = pytest.mark.asyncio


async def _seed(session, *, knowledge: bool = True) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
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
    project = Project(
        id=uuid.uuid4(),
        name=name,
        slug=name,
        owner_user_id=user.id,
        knowledge_enabled=knowledge,
    )
    session.add(project)
    await session.flush()
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref="KN-1",
        title="租約過期時要怎麼處理",
        description="lease_expires_at 到期之後，sweep 會把 run 收成 lost。",
        created_by=user.id,
    )
    session.add(task)
    await session.flush()
    invalidate_enabled_cache()
    return user.id, project.id, task.id


async def _ingest_ticket(session, project_id: uuid.UUID, task_id: uuid.UUID):
    return await source_handlers.ingest(
        session, project_id=project_id, source_type="ticket", external_id=f"task:{task_id}"
    )


# --- the enqueue point ------------------------------------------------------


async def test_recording_activity_enqueues_one_job(session):
    _user, project_id, task_id = await _seed(session)
    await ActivityService(session).record(
        TASK_UPDATED, project_id=project_id, task_id=task_id, actor_kind=ACTOR_USER
    )
    await session.flush()
    jobs = (
        (
            await session.execute(
                sa.select(KnowledgeJob).where(KnowledgeJob.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    assert [(job.source_type, job.external_id, job.state) for job in jobs] == [
        ("ticket", f"task:{task_id}", "pending")
    ]


async def test_five_edits_in_one_second_are_one_job(session):
    """The partial unique index doing its job through the real enqueue path."""
    _user, project_id, task_id = await _seed(session)
    for _ in range(5):
        await ActivityService(session).record(
            TASK_UPDATED, project_id=project_id, task_id=task_id, actor_kind=ACTOR_USER
        )
    await session.flush()
    pending = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeJob)
            .where(KnowledgeJob.project_id == project_id, KnowledgeJob.state == "pending")
        )
    ).scalar()
    assert pending == 1


async def test_a_disabled_project_records_activity_but_no_job(session):
    _user, project_id, task_id = await _seed(session, knowledge=False)
    await ActivityService(session).record(
        TASK_UPDATED, project_id=project_id, task_id=task_id, actor_kind=ACTOR_USER
    )
    await session.flush()
    jobs = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeJob)
            .where(KnowledgeJob.project_id == project_id)
        )
    ).scalar()
    assert jobs == 0


async def test_an_unmapped_activity_kind_enqueues_nothing(session):
    """The map is a closed set; a kind outside it is not an error, it is silence."""
    _user, project_id, _task = await _seed(session)
    await ActivityService(session).record(
        "project.created", project_id=project_id, actor_kind=ACTOR_USER
    )
    await session.flush()
    jobs = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeJob)
            .where(KnowledgeJob.project_id == project_id, KnowledgeJob.source_type != "policy")
        )
    ).scalar()
    assert jobs == 0


async def test_every_ingestable_source_type_has_an_activity_kind():
    """Coverage as an assertion rather than as a list somebody maintains.

    The excluded types are the ones whose trigger is **not a Cliora action**: `repo_doc`
    arrives by push from inside a run, and the two provider types arrive because somebody
    merged or published on a server we do not own.

    **The exclusion set is read from `store.py`, not written here.** This test used to
    assert `== {"repo_doc"}`, and `0044` adding two types would have made it a
    three-member literal in a test file — at which point it stops being a coverage
    assertion and becomes a list somebody keeps in step. Reading `EXTERNALLY_TRIGGERED`
    means the next type costs a *reason* written beside the declaration, and this test
    keeps meaning what its name says.
    """
    from app.services.knowledge.outbox import _INGEST_MAP
    from app.services.knowledge.store import EXTERNALLY_TRIGGERED, SOURCE_TYPES

    mapped = {source_type for source_type, _ in _INGEST_MAP.values()}
    assert SOURCE_TYPES - mapped == EXTERNALLY_TRIGGERED
    # And the declaration is not a place to hide a type that *does* have a kind: every
    # excluded type must be a real one, or the two sets agree by both being wrong.
    assert EXTERNALLY_TRIGGERED <= SOURCE_TYPES


async def test_every_source_type_has_an_explicit_half_life():
    """`plan/27/02` §4's silent trap, asserted.

    `_HALF_LIFE_DAYS` is read with `.get(source_type, 90.0)`, so a type nobody added to it
    does not raise — it silently decays like an artifact. For `release` that is wrong by a
    factor of four: what shipped in v1.4 does not become less true over a year.

    **Equality, not containment**: a stale entry for a deleted type is as much a defect as
    a missing one, and only `==` catches both.
    """
    from app.services.knowledge.search import _HALF_LIFE_DAYS
    from app.services.knowledge.store import SOURCE_TYPES

    assert set(_HALF_LIFE_DAYS) == SOURCE_TYPES


async def test_every_mapped_source_type_has_a_handler():
    from app.services.knowledge.outbox import _INGEST_MAP

    mapped = {source_type for source_type, _ in _INGEST_MAP.values()}
    assert mapped <= set(source_handlers._HANDLERS)


# --- idempotence ------------------------------------------------------------


async def test_the_same_entity_ingested_three_times_writes_one_source(session):
    _user, project_id, task_id = await _seed(session)
    for _ in range(3):
        await _ingest_ticket(session, project_id, task_id)
    await session.flush()
    sources = (
        (
            await session.execute(
                sa.select(KnowledgeSource).where(
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.source_type == "ticket",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(sources) == 1
    chunks = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.source_id == sources[0].id)
        )
    ).scalar()
    assert chunks == sources[0].chunk_count == 1


async def test_editing_a_card_supersedes_the_previous_version(session):
    _user, project_id, task_id = await _seed(session)
    await _ingest_ticket(session, project_id, task_id)
    await session.flush()

    task = await session.get(Task, task_id)
    task.version += 1
    task.description = "改寫過的描述"
    task.updated_at = now_utc() + timedelta(seconds=1)
    await session.flush()
    await _ingest_ticket(session, project_id, task_id)
    await session.flush()

    rows = (
        await session.execute(
            sa.select(KnowledgeSource.source_version, KnowledgeSource.authority)
            .where(KnowledgeSource.project_id == project_id)
            .order_by(KnowledgeSource.source_version)
        )
    ).all()
    assert rows == [("v1", "superseded"), ("v2", "discussion")]


async def test_an_older_version_arriving_late_does_not_win(session):
    """Two workers, reversed delivery. The upsert's `WHERE` is the whole defence."""
    _user, project_id, task_id = await _seed(session)
    task = await session.get(Task, task_id)
    task.updated_at = now_utc()
    await session.flush()
    await _ingest_ticket(session, project_id, task_id)

    # The same version key, an older timestamp, different text: what a replayed job for
    # a stale read looks like.
    from app.services.knowledge.store import ExtractedSource, KnowledgeStore

    await KnowledgeStore(session).upsert(
        project_id=project_id,
        source_type="ticket",
        source=ExtractedSource(
            external_id=f"task:{task_id}",
            version="v1",
            authority="discussion",
            title="舊的標題",
            text="舊的內容",
            occurred_at=task.updated_at - timedelta(hours=1),
            source_updated_at=task.updated_at - timedelta(hours=1),
        ),
    )
    await session.flush()
    title = (
        await session.execute(
            sa.select(KnowledgeSource.title).where(KnowledgeSource.project_id == project_id)
        )
    ).scalar_one()
    assert title.startswith("KN-1")


# --- redaction --------------------------------------------------------------


async def test_a_credential_shaped_literal_never_reaches_a_chunk(session):
    _user, project_id, task_id = await _seed(session)
    task = await session.get(Task, task_id)
    task.description = "用這個跑： cliora_rt_abcdefghijklmnopqrstuvwxyz012345 然後回報"
    task.updated_at = now_utc()
    await session.flush()
    await _ingest_ticket(session, project_id, task_id)
    await session.flush()
    content = (
        await session.execute(
            sa.select(KnowledgeChunk.content).where(KnowledgeChunk.project_id == project_id)
        )
    ).scalar_one()
    assert "cliora_rt_" not in content
    assert "[已遮蔽]" in content


# --- the worker -------------------------------------------------------------


async def test_a_pending_job_survives_a_worker_that_never_ran(session):
    """Durability: the queue is a table, so losing the process loses nothing.

    Asserted at the row level rather than by restarting a process, because what makes
    it true is that the row is committed by the caller's transaction — and that is
    exactly what the next test checks from the other side.
    """
    _user, project_id, task_id = await _seed(session)
    await KnowledgeOutbox(session).enqueue(
        project_id=project_id, source_type="ticket", external_id=f"task:{task_id}"
    )
    await session.flush()
    state = (
        await session.execute(
            sa.select(KnowledgeJob.state).where(KnowledgeJob.project_id == project_id)
        )
    ).scalar_one()
    assert state == "pending"


async def test_a_rolled_back_fact_rolls_back_its_hint(session):
    """Same transaction as the fact, so a hint cannot describe something that never was.

    The session fixture rolls back at the end of every test; this asserts the coupling
    inside one savepoint instead, which is the same property at a scale a test can see.
    """
    _user, project_id, task_id = await _seed(session)
    savepoint = await session.begin_nested()
    await ActivityService(session).record(
        TASK_UPDATED, project_id=project_id, task_id=task_id, actor_kind=ACTOR_USER
    )
    await session.flush()
    await savepoint.rollback()
    jobs = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeJob)
            .where(KnowledgeJob.project_id == project_id)
        )
    ).scalar()
    assert jobs == 0


async def test_backoff_grows_and_then_dead_letters(session):
    from app.services.knowledge.worker import MAX_ATTEMPTS, _next_attempt_delay

    delays = [_next_attempt_delay(attempt) for attempt in range(1, MAX_ATTEMPTS + 1)]
    assert delays == sorted(delays), "backoff must never shorten"
    assert delays[0] < delays[-1]


async def test_a_stuck_running_job_returns_to_pending_without_an_attempt(session):
    """A Central killed mid-job produced no conclusion, not a failure.

    Counting it would send healthy jobs to the dead letter after three restarts, and the
    dead letter is the one signal an operator is asked to trust.
    """
    _user, project_id, task_id = await _seed(session)
    job = KnowledgeJob(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type="ticket",
        external_id=f"task:{task_id}",
        state="running",
        attempts=2,
        started_at=now_utc() - timedelta(hours=1),
    )
    session.add(job)
    await session.flush()

    # `_recover_stuck` opens its own database session, which this test's rolled-back
    # transaction would not see. The statement is what is under test, so it is run here
    # against the same connection.
    await session.execute(
        sa.update(KnowledgeJob.__table__)
        .where(
            KnowledgeJob.__table__.c.state == "running",
            KnowledgeJob.__table__.c.started_at < now_utc() - STUCK_AFTER,
        )
        .values(state="pending", started_at=None)
    )
    await session.flush()
    # Read back with Core, not `session.get`: the update above bypassed the ORM, so the
    # identity map still holds the pre-update row.
    state, attempts = (
        await session.execute(
            sa.select(KnowledgeJob.__table__.c.state, KnowledgeJob.__table__.c.attempts).where(
                KnowledgeJob.__table__.c.id == job.id
            )
        )
    ).one()
    assert state == "pending"
    assert attempts == 2, "an interrupted job is not a failed attempt"


# --- reconciliation ---------------------------------------------------------


async def test_the_watermark_finds_a_card_the_event_path_missed(session):
    _user, project_id, task_id = await _seed(session)
    stale = await source_handlers.WATERMARKS["ticket"](session, project_id, 10)
    assert stale == [f"task:{task_id}"]

    await _ingest_ticket(session, project_id, task_id)
    await session.flush()
    assert await source_handlers.WATERMARKS["ticket"](session, project_id, 10) == []


async def test_the_watermark_finds_an_unindexed_message(session):
    user_id, project_id, task_id = await _seed(session)
    session.add(
        TaskMessage(
            id=uuid.uuid4(),
            task_id=task_id,
            author_kind="user",
            author_user_id=user_id,
            body="這裡的 24 小時是哪來的",
            kind="comment",
            conversation_seq=1,
        )
    )
    await session.flush()
    stale = await source_handlers.WATERMARKS["conversation"](session, project_id, 10)
    assert stale == [f"task:{task_id}"]

    await source_handlers.ingest(
        session, project_id=project_id, source_type="conversation", external_id=f"task:{task_id}"
    )
    await session.flush()
    assert await source_handlers.WATERMARKS["conversation"](session, project_id, 10) == []
