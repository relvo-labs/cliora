"""What each source type becomes, and what it is trusted as (`KN-04`/`KN-05`).

The assertions here are almost all about **authority**, because that is the column the
whole ranking rests on and it is the one a caller may never set. Three of them are the
same shape from three directions: an agent's draft is `generated` however good it is, an
artifact is `verified` only if a run that passed verification produced it, and a
requirement is `accepted` only once a person approved it.

The rest assert the two things a version key has to do: identify a version (so the same
fact ingested twice is one row) and order versions (so a later one supersedes an
earlier one).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.clock import now_utc
from app.db.models import (
    ActivityEvent,
    EvidenceItem,
    FeatureSpec,
    KnowledgeSource,
    Project,
    Requirement,
    Role,
    Task,
    TaskArtifact,
    TaskMessage,
    TaskRun,
    User,
    VerificationReport,
)
from app.security.passwords import hash_password
from app.services.knowledge import sources as handlers
from app.services.knowledge.outbox import invalidate_enabled_cache

pytestmark = pytest.mark.asyncio


async def _seed(session):
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
        knowledge_enabled=True,
        description="交付一律走 PR，不直接推 main。",
    )
    session.add(project)
    await session.flush()
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref="KN-9",
        title="租約過期",
        description="說明",
        created_by=user.id,
    )
    session.add(task)
    await session.flush()
    invalidate_enabled_cache()
    return user, project, task


async def _sources(session, project_id, source_type: str):
    return (
        (
            await session.execute(
                sa.select(KnowledgeSource)
                .where(
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.source_type == source_type,
                )
                .order_by(KnowledgeSource.source_external_id)
            )
        )
        .scalars()
        .all()
    )


# --- policy -----------------------------------------------------------------


async def test_the_project_becomes_an_authoritative_policy_source(session):
    _user, project, _task = await _seed(session)
    await handlers.ingest(
        session,
        project_id=project.id,
        source_type="policy",
        external_id=f"project:{project.id}",
    )
    await session.flush()
    rows = await _sources(session, project.id, "policy")
    assert len(rows) == 1
    assert rows[0].authority == "authoritative"
    assert "PR" in (
        await session.scalar(
            sa.text(
                "SELECT content FROM knowledge_chunks WHERE source_id = :sid LIMIT 1"
            ).bindparams(sid=rows[0].id)
        )
    )


# --- ticket -----------------------------------------------------------------


async def test_a_card_is_discussion_and_versioned_by_its_optimistic_lock(session):
    _user, project, task = await _seed(session)
    await handlers.ingest(
        session, project_id=project.id, source_type="ticket", external_id=f"task:{task.id}"
    )
    await session.flush()
    rows = await _sources(session, project.id, "ticket")
    assert (rows[0].authority, rows[0].source_version) == ("discussion", "v1")
    assert rows[0].source_uri == f"/projects/{project.id}/tasks/{task.id}"


# --- conversation -----------------------------------------------------------


async def test_message_kinds_map_to_three_different_authorities(session):
    """A proposal is the agent's; a decision is a person's; a comment is neither."""
    user, project, task = await _seed(session)
    for seq, (kind, body) in enumerate(
        [("comment", "一般留言"), ("proposal", "我建議這樣做"), ("decision", "接受")], start=1
    ):
        session.add(
            TaskMessage(
                id=uuid.uuid4(),
                task_id=task.id,
                author_kind="user",
                author_user_id=user.id,
                body=body,
                kind=kind,
                conversation_seq=seq,
            )
        )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="conversation", external_id=f"task:{task.id}"
    )
    await session.flush()
    rows = await _sources(session, project.id, "conversation")
    assert {row.authority for row in rows} == {"discussion", "generated", "accepted"}
    assert all(row.source_version.startswith("seq:") for row in rows)


async def test_a_system_message_is_not_indexed(session):
    """Platform events are already `activity`; indexing them twice doubles every one."""
    user, project, task = await _seed(session)
    session.add(
        TaskMessage(
            id=uuid.uuid4(),
            task_id=task.id,
            author_kind="user",
            author_user_id=user.id,
            body="卡片移動到 ready",
            kind="system",
            conversation_seq=1,
        )
    )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="conversation", external_id=f"task:{task.id}"
    )
    await session.flush()
    assert await _sources(session, project.id, "conversation") == []


async def test_a_citation_anchor_points_at_the_sequence_number(session):
    """`?seq=` is what makes a citation land on the message rather than on the card."""
    user, project, task = await _seed(session)
    session.add(
        TaskMessage(
            id=uuid.uuid4(),
            task_id=task.id,
            author_kind="user",
            author_user_id=user.id,
            body="這裡的 24 小時是哪來的",
            kind="comment",
            conversation_seq=18,
        )
    )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="conversation", external_id=f"task:{task.id}"
    )
    await session.flush()
    row = (await _sources(session, project.id, "conversation"))[0]
    assert row.source_uri.endswith("?seq=18")


# --- decision ---------------------------------------------------------------


async def _requirement(session, project, *, approved: bool):
    requirement = Requirement(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref="REQ-1",
        raw_text="要有一個可以搜尋專案記憶的地方",
        status="approved" if approved else "intake",
        approved_at=now_utc() if approved else None,
    )
    session.add(requirement)
    await session.flush()
    return requirement


async def test_an_unapproved_requirement_is_discussion(session):
    _user, project, _task = await _seed(session)
    requirement = await _requirement(session, project, approved=False)
    await handlers.ingest(
        session,
        project_id=project.id,
        source_type="decision",
        external_id=f"requirement:{requirement.id}",
    )
    await session.flush()
    rows = await _sources(session, project.id, "decision")
    assert [row.authority for row in rows] == ["discussion"]


async def test_an_agents_spec_stays_generated_even_under_an_approved_requirement(session):
    """The sharpest of the authority rules: approval is a person's act, on the
    requirement. An agent's draft never becomes an instruction by being nearby."""
    _user, project, _task = await _seed(session)
    requirement = await _requirement(session, project, approved=True)
    session.add(
        FeatureSpec(
            id=uuid.uuid4(),
            requirement_id=requirement.id,
            seq=1,
            objective="讓 Agent 讀得到專案決策",
            authored_by_kind="runner",
        )
    )
    await session.flush()
    await handlers.ingest(
        session,
        project_id=project.id,
        source_type="decision",
        external_id=f"requirement:{requirement.id}",
    )
    await session.flush()
    rows = {
        row.source_external_id.split(":")[0]: row.authority
        for row in await _sources(session, project.id, "decision")
    }
    assert rows["requirement"] == "accepted"
    assert rows["spec"] == "generated"


async def test_a_humans_spec_under_an_approved_requirement_is_accepted(session):
    _user, project, _task = await _seed(session)
    requirement = await _requirement(session, project, approved=True)
    session.add(
        FeatureSpec(
            id=uuid.uuid4(),
            requirement_id=requirement.id,
            seq=1,
            objective="人寫的規格",
            authored_by_kind="user",
        )
    )
    await session.flush()
    await handlers.ingest(
        session,
        project_id=project.id,
        source_type="decision",
        external_id=f"requirement:{requirement.id}",
    )
    await session.flush()
    rows = {
        row.source_external_id.split(":")[0]: row.authority
        for row in await _sources(session, project.id, "decision")
    }
    assert rows["spec"] == "accepted"


# --- artifact ---------------------------------------------------------------


async def _run(session, project, task, *, verified: bool):
    run = TaskRun(
        id=uuid.uuid4(), task_id=task.id, project_id=project.id, seq=1, status="succeeded"
    )
    session.add(run)
    await session.flush()
    if verified:
        session.add(
            VerificationReport(
                id=uuid.uuid4(),
                task_id=task.id,
                run_id=run.id,
                project_id=project.id,
                result="passed",
                source="machine_verified",
                reported_by_kind="runner",
            )
        )
        await session.flush()
    return run


async def test_an_artifact_from_a_passing_run_is_verified(session):
    _user, project, task = await _seed(session)
    run = await _run(session, project, task, verified=True)
    session.add(
        TaskArtifact(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=project.id,
            run_id=run.id,
            filename="report.txt",
            content_type="text/plain",
            size=12,
            sha256="a" * 64,
            storage_ref="db",
            uploaded_by_kind="agent",
        )
    )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="artifact", external_id=f"task:{task.id}"
    )
    await session.flush()
    rows = await _sources(session, project.id, "artifact")
    assert [row.authority for row in rows] == ["verified"]
    assert rows[0].source_version.startswith("sha256:")


async def test_an_artifact_from_an_unverified_run_is_only_generated(session):
    _user, project, task = await _seed(session)
    run = await _run(session, project, task, verified=False)
    session.add(
        TaskArtifact(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=project.id,
            run_id=run.id,
            filename="notes.txt",
            content_type="text/plain",
            size=3,
            sha256="b" * 64,
            storage_ref="db",
            uploaded_by_kind="agent",
        )
    )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="artifact", external_id=f"task:{task.id}"
    )
    await session.flush()
    assert [row.authority for row in await _sources(session, project.id, "artifact")] == [
        "generated"
    ]


async def test_a_deleted_artifact_produces_no_source(session):
    _user, project, task = await _seed(session)
    run = await _run(session, project, task, verified=True)
    session.add(
        TaskArtifact(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=project.id,
            run_id=run.id,
            filename="gone.txt",
            content_type="text/plain",
            size=1,
            sha256="c" * 64,
            storage_ref="db",
            uploaded_by_kind="agent",
            deleted_at=now_utc(),
        )
    )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="artifact", external_id=f"task:{task.id}"
    )
    await session.flush()
    assert await _sources(session, project.id, "artifact") == []


# --- verification -----------------------------------------------------------


async def test_two_contradicting_evidence_items_are_both_kept(session):
    """`EvidenceItem`'s own rule, carried into the index: contradictions are stored,
    not resolved. Nothing here picks a winner, and both name their provenance."""
    _user, project, task = await _seed(session)
    run = await _run(session, project, task, verified=False)
    # `kind` decides `source`, never the other way round (`EvidenceItem`'s own rule),
    # so the two rows differ by kind and their sources follow.
    for kind, source, files in (
        ("git_state", "machine_verified", "a.py"),
        ("agent_finding", "agent_reported", "b.py"),
    ):
        session.add(
            EvidenceItem(
                id=uuid.uuid4(),
                task_id=task.id,
                run_id=run.id,
                project_id=project.id,
                kind=kind,
                source=source,
                written_by_kind="runner",
                payload={"changed": files},
            )
        )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="verification", external_id=f"task:{task.id}"
    )
    await session.flush()
    rows = await _sources(session, project.id, "verification")
    assert sorted(row.authority for row in rows) == ["generated", "verified"]


# --- activity ---------------------------------------------------------------


async def test_only_the_three_decisive_timeline_kinds_are_indexed(session):
    """A card dragged between lanes forty times would outweigh the approval recorded
    once, so the indexed set is explicit rather than "every activity kind"."""
    _user, project, task = await _seed(session)
    for kind in ("task.gate_approved", "task.stage_changed", "run.finished"):
        session.add(
            ActivityEvent(
                id=uuid.uuid4(),
                project_id=project.id,
                task_id=task.id,
                actor_kind="user",
                kind=kind,
                activity_payload={"gate": "review"},
            )
        )
    await session.flush()
    await handlers.ingest(
        session, project_id=project.id, source_type="activity", external_id=f"task:{task.id}"
    )
    await session.flush()
    rows = await _sources(session, project.id, "activity")
    assert sorted(row.title for row in rows) == ["run.finished", "task.gate_approved"]
    assert {row.authority for row in rows} == {"verified"}


# --- isolation --------------------------------------------------------------


async def test_a_handler_refuses_an_entity_from_another_project(session):
    """The predicate is inside the handler, not applied to its output."""
    _user_a, project_a, task_a = await _seed(session)
    _user_b, project_b, _task_b = await _seed(session)
    result = await handlers.ingest(
        session, project_id=project_b.id, source_type="ticket", external_id=f"task:{task_a.id}"
    )
    assert result.sources == 0
    assert await _sources(session, project_b.id, "ticket") == []


async def test_a_second_ingest_after_an_edit_supersedes_only_within_the_project(session):
    _user_a, project_a, task_a = await _seed(session)
    _user_b, project_b, task_b = await _seed(session)
    for project, task in ((project_a, task_a), (project_b, task_b)):
        await handlers.ingest(
            session, project_id=project.id, source_type="ticket", external_id=f"task:{task.id}"
        )
    await session.flush()

    task_a.version += 1
    task_a.updated_at = now_utc() + timedelta(seconds=1)
    await session.flush()
    await handlers.ingest(
        session, project_id=project_a.id, source_type="ticket", external_id=f"task:{task_a.id}"
    )
    await session.flush()

    assert sorted(row.authority for row in await _sources(session, project_a.id, "ticket")) == [
        "discussion",
        "superseded",
    ]
    assert [row.authority for row in await _sources(session, project_b.id, "ticket")] == [
        "discussion"
    ]
