"""Plans, reports and evidence: append-only, and provenance decided by the write path.

FR-PLAN-001, FR-VERIFY-001/002, FR-EVIDENCE-001/002, ADR 0033 §3b.

Two tests here are worth more than the rest.

`test_a_claimed_source_is_ignored_and_recorded` — only *ignoring* a claimed credibility
level would make an agent overstating its evidence and an agent with a typo leave
identical traces, and those need different responses.

`test_kind_decides_source_and_an_agent_cannot_claim_a_machine_one` — the mapping is a
table rather than a check, so an agent-written machine fact is unrepresentable rather
than merely refused. A check has a second call site; a mapping does not.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.db.models import EvidenceItem, Project, Role, Task, User, VerificationReport
from app.security.passwords import hash_password
from app.services.evidence import (
    _SOURCE_FOR_KIND,
    AGENT_WRITABLE_KINDS,
    MACHINE_VERIFIED,
    EvidenceService,
    VerificationService,
)

pytestmark = pytest.mark.asyncio


async def _actor(client, maker, role_name: str = "Admin") -> tuple[uuid.UUID, dict]:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        username = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}"
        user = User(
            id=uuid.uuid4(),
            username=username,
            display_name=username,
            password_hash=hash_password("pw"),
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        user_id = user.id
    tokens = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    return user_id, {"authorization": f"Bearer {tokens.json()['tokens']['access_token']}"}


async def _card(maker, owner_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        slug = f"p-{uuid.uuid4().hex[:8]}"
        project = Project(
            id=uuid.uuid4(),
            name=slug,
            slug=slug,
            status="active",
            owner_user_id=owner_id,
            next_card_seq=1,
        )
        session.add(project)
        await session.flush()
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=f"TASK-{uuid.uuid4().hex[:6]}",
            title="a card",
            stage="implementing",
            risk="low",
            priority="normal",
            source="none",
            delivery="none",
        )
        session.add(task)
        await session.commit()
        return project.id, task.id


# --- execution plans ----------------------------------------------------------


async def test_a_plan_is_appended_and_a_revision_must_say_why(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    _project, task_id = await _card(maker, owner)

    first = await client.post(
        f"/api/tasks/{task_id}/plans",
        json={"steps": [{"title": "read the code", "status": "completed"}]},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["seq"] == 1

    # A revision with no reason is refused: *why* the plan changed is the reason this is
    # a version row rather than a mutable column.
    silent = await client.post(
        f"/api/tasks/{task_id}/plans",
        json={"steps": [{"title": "read the code", "status": "completed"}]},
        headers=headers,
    )
    assert silent.status_code == 400
    assert silent.json()["error"]["code"] == "PLAN_NOTE_REQUIRED"

    second = await client.post(
        f"/api/tasks/{task_id}/plans",
        json={"steps": [], "note": "the API turned out to be paginated"},
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["seq"] == 2

    listed = await client.get(f"/api/tasks/{task_id}/plans", headers=headers)
    assert [item["seq"] for item in listed.json()] == [2, 1]


async def test_an_unknown_step_status_is_refused(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    _project, task_id = await _card(maker, owner)

    resp = await client.post(
        f"/api/tasks/{task_id}/plans",
        json={"steps": [{"title": "x", "status": "nearly"}]},
        headers=headers,
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PLAN_STEPS_INVALID"


async def test_the_three_tables_have_no_third_verb(api: tuple, projects_enabled: None) -> None:
    """Append-only, expressed in REST as the absence of PUT, PATCH and DELETE."""
    from app.main import app

    for resource in ("plans", "verification", "evidence"):
        path = f"/api/tasks/{{task_id}}/{resource}"
        methods: set[str] = set()
        for route in app.routes:
            if getattr(route, "path", None) == path:
                methods |= set(getattr(route, "methods", set()))
        assert methods <= {"GET", "POST", "HEAD", "OPTIONS"}, (
            f"{resource} grew a mutating verb: {sorted(methods)}"
        )


# --- verification reports -----------------------------------------------------


async def test_a_claimed_source_is_ignored_and_recorded(api: tuple, projects_enabled: None) -> None:
    """Only ignoring it would make an overstatement and a typo indistinguishable."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project_id, task_id = await _card(maker, owner)

    resp = await client.post(
        f"/api/tasks/{task_id}/verification",
        json={"result": "passed", "source": "machine_verified"},
        headers=headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["source"] == "agent_reported"

    timeline = await client.get(f"/api/projects/{project_id}/activity", headers=headers)
    kinds = [item["kind"] for item in timeline.json()["items"]]
    assert "verification.source_ignored" in kinds


async def test_a_person_submitting_a_report_is_still_agent_reported(
    api: tuple, projects_enabled: None
) -> None:
    """The level answers "who observed this", and a person typing into a form is not
    the platform observing it."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    _project, task_id = await _card(maker, owner)

    resp = await client.post(
        f"/api/tasks/{task_id}/verification",
        json={"result": "passed", "completion_summary": "checked by hand"},
        headers=headers,
    )

    assert resp.json()["source"] == "agent_reported"


async def test_machine_verified_keeps_both_origins_and_the_real_exit_codes(
    api: tuple, projects_enabled: None
) -> None:
    """Both stores produce machine facts — neither was chosen by the agent — and the
    report still says which one named each command (ADR 0033 §3b)."""
    client, maker = api
    owner, _headers = await _actor(client, maker)
    _project, task_id = await _card(maker, owner)

    async with maker() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        report = await VerificationService(session).record_machine_verified(
            task=task,
            run_id=None,  # type: ignore[arg-type]
            checks=[
                {"name": "unit tests", "origin": "project", "exit_code": 0},
                {"name": "e2e", "origin": "card", "exit_code": 3},
            ],
            summary="ran the checks",
            runner_id=None,
        )
        await session.commit()
        stored = await session.get(VerificationReport, report.id)
        assert stored is not None
        assert stored.source == MACHINE_VERIFIED
        # A failing check makes the report failed, whatever anything says about itself.
        assert stored.result == "failed"
        origins = {check["origin"] for check in stored.checks}
        assert origins == {"project", "card"}
        assert [check["exit_code"] for check in stored.checks] == [0, 3]


def test_machine_verified_has_exactly_one_writer() -> None:
    """A second writer would let an agent's self-report become a machine fact.

    The static form of `GATE-DV-MACHINE-VERIFIED-ONE-WRITER`, asserted here too because
    a gate that only runs in one script is a gate somebody forgets to run.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "backend/app"
    writers = []
    for path in root.rglob("*.py"):
        body = path.read_text(encoding="utf-8")
        # The constant's *definition* and its use as a comparison are fine; what may
        # exist once is a call that stores it.
        if "record_machine_verified" in body and "def record_machine_verified" not in body:
            writers.append(str(path.relative_to(root)))
    assert len(writers) <= 1, f"machine_verified is written from {writers}"


# --- evidence -----------------------------------------------------------------


def test_kind_decides_source_and_never_the_other_way_round() -> None:
    for kind, source in _SOURCE_FOR_KIND.items():
        assert source in {"agent_reported", "platform_observed", "machine_verified"}
        if kind.startswith("agent_"):
            assert source == "agent_reported", f"{kind} would be an agent-written {source}"
            assert kind in AGENT_WRITABLE_KINDS
        else:
            assert kind not in AGENT_WRITABLE_KINDS, (
                f"{kind} is writable by an agent but stores {source}"
            )


async def test_an_agent_cannot_claim_a_machine_kind(api: tuple, projects_enabled: None) -> None:
    """Refused rather than downgraded: a downgraded row still asserts something nobody
    observed."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    _project, task_id = await _card(maker, owner)

    resp = await client.post(
        f"/api/tasks/{task_id}/evidence",
        json={"kind": "git_state", "payload": {"branch": "main"}},
        headers=headers,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "EVIDENCE_KIND_NOT_WRITABLE"


async def test_a_contradiction_is_stored_twice_and_not_resolved(
    api: tuple, projects_enabled: None
) -> None:
    """The agent's account and git's disagree, and the platform does not adjudicate.

    Implementing this costs nothing; the test exists because adding a reconciliation
    rule is the natural instinct, and its verdict would be a judgement with nobody
    accountable for it.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    _project, task_id = await _card(maker, owner)

    await client.post(
        f"/api/tasks/{task_id}/evidence",
        json={"kind": "agent_finding", "payload": {"changed_files": ["a.py"]}},
        headers=headers,
    )
    async with maker() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        await EvidenceService(session).add(
            task=task,
            kind="changed_files",
            payload={"changed_files": ["a.py", "b.py"]},
            run_id=None,
            actor_kind="system",
            user_id=None,
            runner_id=None,
            agent_written=False,
        )
        await session.commit()

    listed = await client.get(f"/api/tasks/{task_id}/evidence", headers=headers)
    items = listed.json()

    assert len(items) == 2
    assert {item["source"] for item in items} == {"agent_reported", "machine_verified"}
    # Both survive with their own accounts; nothing merged or dropped them.
    payloads = sorted(len(item["payload"]["changed_files"]) for item in items)
    assert payloads == [1, 2]


async def test_an_oversized_payload_points_at_artifacts(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    _project, task_id = await _card(maker, owner)

    resp = await client.post(
        f"/api/tasks/{task_id}/evidence",
        json={"kind": "agent_finding", "payload": {"log": "x" * 20000}},
        headers=headers,
    )

    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "EVIDENCE_PAYLOAD_TOO_LARGE"


async def test_evidence_rows_carry_their_project_for_aggregation(
    api: tuple, projects_enabled: None
) -> None:
    """`project_id` is redundant and deliberate: five cross-project metrics read these
    tables, and without it every one of them joins `tasks`."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project_id, task_id = await _card(maker, owner)

    await client.post(
        f"/api/tasks/{task_id}/evidence",
        json={"kind": "agent_risk", "payload": {"text": "untested on Windows"}},
        headers=headers,
    )

    async with maker() as session:
        row = (
            await session.execute(sa.select(EvidenceItem).where(EvidenceItem.task_id == task_id))
        ).scalar_one()
        assert row.project_id == project_id
