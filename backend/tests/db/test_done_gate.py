"""The Done Gate, its one exit, and the process override that must not reach it.

FR-VERIFY-003, FR-AGENTTOOL-002, ADR 0033 §5.

The most valuable test here is `test_a_run_never_advances_a_card_into_done`: the gate
has exactly one entrance, and the failure it guards against is not a wrong answer but a
**second door** somebody adds later out of helpfulness. `GATE-DV-SINGLE-DONE-PATH` scans
for the same thing statically.

Note what that test does *not* say. A run legitimately moves a card to `blocked` when
its attempts are exhausted (V2.2) — that is a report, not a completion claim. Writing the
invariant as "a run never assigns `stage`" would have been wrong in a way that looks
stricter, and it would have had to be relaxed the first time somebody read it, which is
how a guard gets deleted rather than fixed.

Second most valuable is `test_the_gate_does_not_apply_without_the_runner_layer`. All six
conditions ask for evidence the agent-runner layer produces, so on a board-only
deployment every card would be unable to reach `done` — which is V2.1 broken for people
who never asked for V2.2. An existing V2.1 test caught that during implementation, and
this pins it so it cannot come back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from app.db.models import (
    Project,
    Role,
    Task,
    TaskArtifact,
    TaskRun,
    User,
    VerificationReport,
)
from app.security.passwords import hash_password

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


async def _project(maker, owner_id: uuid.UUID, **fields) -> uuid.UUID:
    async with maker() as session:
        slug = f"p-{uuid.uuid4().hex[:8]}"
        project = Project(
            id=uuid.uuid4(),
            name=slug,
            slug=slug,
            status="active",
            owner_user_id=owner_id,
            next_card_seq=1,
            **fields,
        )
        session.add(project)
        await session.commit()
        return project.id


async def _card(maker, project_id: uuid.UUID, **fields) -> tuple[uuid.UUID, int]:
    async with maker() as session:
        task = Task(
            id=uuid.uuid4(),
            project_id=project_id,
            card_ref=f"TASK-{uuid.uuid4().hex[:6]}",
            title="a card",
            stage=fields.pop("stage", "verify"),
            risk="low",
            priority="normal",
            delivery=fields.pop("delivery", "none"),
            source=fields.pop("source", "none"),
            **fields,
        )
        session.add(task)
        await session.commit()
        return task.id, task.version


async def _report(maker, project_id: uuid.UUID, task_id: uuid.UUID, **fields) -> None:
    async with maker() as session:
        session.add(
            VerificationReport(
                id=uuid.uuid4(),
                task_id=task_id,
                project_id=project_id,
                result=fields.pop("result", "passed"),
                completion_summary=fields.pop("completion_summary", "did the thing"),
                source=fields.pop("source", "machine_verified"),
                reported_by_kind="user",
                **fields,
            )
        )
        await session.commit()


async def _finished_run(maker, project_id: uuid.UUID, task_id: uuid.UUID, **fields) -> uuid.UUID:
    async with maker() as session:
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task_id,
            project_id=project_id,
            seq=1,
            status="succeeded",
            attempt=1,
            finished_at=datetime.now(UTC),
            **fields,
        )
        session.add(run)
        await session.commit()
        return run.id


async def _move(client, headers, task_id, version, stage="done", **body):
    return await client.patch(
        f"/api/tasks/{task_id}",
        json={"version": version, "stage": stage, **body},
        headers=headers,
    )


# --- the six conditions ------------------------------------------------------


async def test_the_refusal_names_every_missing_item(api: tuple, projects_enabled: None) -> None:
    """Not the first one. A missing summary and a missing report send a person to two
    different places, and one sentence would send half of them to the wrong one."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(
        maker, project, acceptance_criteria=[{"text": "reject traversal"}]
    )

    resp = await _move(client, headers, task_id, version)

    assert resp.status_code == 409, resp.text
    body = resp.json()["error"]
    assert body["code"] == "TASK_DONE_GATE_UNMET"
    keys = {item["key"] for item in body["details"]["missing"]}
    assert keys == {"completion_summary", "acceptance_criteria", "verification_report"}
    # The criterion is named, not counted: "1 criterion is unverified" is not actionable.
    criteria = next(i for i in body["details"]["missing"] if i["key"] == "acceptance_criteria")
    assert "reject traversal" in criteria["text"]


async def test_a_card_with_its_evidence_passes(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(
        maker, project, acceptance_criteria=[{"text": "a", "result": "passed"}]
    )
    await _report(maker, project, task_id)

    resp = await _move(client, headers, task_id, version)

    assert resp.status_code == 200, resp.text
    assert resp.json()["task"]["stage"] == "done"


async def test_a_failed_check_blocks_until_it_is_accepted_as_a_risk(
    api: tuple, projects_enabled: None
) -> None:
    """ "Handled" means somebody said they accept it, not that it was fixed. Defining it
    as "fixed" would block every card behind a known environment problem, and people
    would route around the gate."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(maker, project)
    await _report(
        maker,
        project,
        task_id,
        result="partial",
        checks=[{"name": "lint", "origin": "project", "exit_code": 1}],
    )

    blocked = await _move(client, headers, task_id, version)
    assert blocked.status_code == 409
    assert any(
        item["key"] == "critical_failure" for item in blocked.json()["error"]["details"]["missing"]
    )

    await _report(
        maker,
        project,
        task_id,
        result="partial",
        checks=[{"name": "lint", "origin": "project", "exit_code": 1}],
        remaining_risks=[{"check": "lint", "text": "known, tracked separately"}],
    )
    assert (await _move(client, headers, task_id, version)).status_code == 200


# --- the delivery evidence, one branch per mode ------------------------------


@pytest.mark.parametrize(
    ("delivery", "run_fields", "artifacts", "expected"),
    [
        ("none", {}, 0, 200),
        ("artifact", {}, 1, 200),
        ("artifact", {}, 0, 409),
        ("branch", {"pushed_branch": "cliora/TASK-1-1"}, 0, 200),
        ("branch", {}, 0, 409),
        ("pull_request", {"delivery_ref": "https://example.invalid/pr/1"}, 0, 200),
        # No changes means no pull request — so it must not then be blocked for
        # lacking one. Honesty rule 2's other half (ADR 0033 §2).
        ("pull_request", {"result": "no_changes"}, 0, 200),
        # A pull request that could not be created is not the card's fault: the branch
        # is pushed and the work exists.
        ("pull_request", {"delivery_state": "branch_only"}, 0, 200),
        ("pull_request", {}, 0, 409),
        ("existing_pr", {"pushed_branch": "cliora/TASK-1-1"}, 0, 200),
    ],
)
async def test_each_delivery_mode_asks_for_its_own_evidence(
    api: tuple,
    projects_enabled: None,
    delivery: str,
    run_fields: dict,
    artifacts: int,
    expected: int,
) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(maker, project, delivery=delivery)
    await _report(maker, project, task_id)
    run_id = await _finished_run(maker, project, task_id, **run_fields)
    if artifacts:
        async with maker() as session:
            session.add(
                TaskArtifact(
                    id=uuid.uuid4(),
                    task_id=task_id,
                    project_id=project,
                    run_id=run_id,
                    filename="report.md",
                    content_type="text/markdown",
                    size=3,
                    sha256="0" * 64,
                    storage_ref="db:x",
                    uploaded_by_kind="agent",
                )
            )
            await session.commit()

    resp = await _move(client, headers, task_id, version)

    assert resp.status_code == expected, resp.text


async def test_a_card_that_was_never_dispatched_has_no_delivery_to_evidence(
    api: tuple, projects_enabled: None
) -> None:
    """`tasks.delivery` defaults to `pull_request`, so without this every hand-managed
    card on the board would need a pull request it was never going to have."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(maker, project, delivery="pull_request")
    await _report(maker, project, task_id)
    # No run at all.

    resp = await _move(client, headers, task_id, version)

    assert resp.status_code == 200, resp.text


# --- the one exit ------------------------------------------------------------


async def test_forcing_requires_its_own_action_a_reason_and_leaves_a_mark(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    owner, admin = await _actor(client, maker, "Admin")
    _, developer = await _actor(client, maker, "Developer")
    project = await _project(maker, owner)
    task_id, version = await _card(maker, project)

    # A Developer holds `task.update` and may patch the card — and still cannot force.
    refused = await _move(client, developer, task_id, version, force=True, force_reason="because")
    assert refused.status_code == 403, refused.text

    # An Admin without a reason is refused too: the reason is what makes the exit
    # visible rather than silent.
    no_reason = await _move(client, admin, task_id, version, force=True, force_reason="  ")
    assert no_reason.status_code == 400
    assert no_reason.json()["error"]["code"] == "TASK_FORCE_REASON_REQUIRED"

    forced = await _move(
        client, admin, task_id, version, force=True, force_reason="verification host is down"
    )
    assert forced.status_code == 200, forced.text

    async with maker() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        assert task.stage == "done"
        assert task.force_done_reason == "verification host is down"
        assert task.force_done_by == owner
        assert task.force_done_at is not None

    timeline = await client.get(f"/api/projects/{project}/activity", headers=admin)
    kinds = [item["kind"] for item in timeline.json()["items"]]
    assert "task.forced_done" in kinds


async def test_leaving_done_is_the_only_way_the_mark_clears(
    api: tuple, projects_enabled: None
) -> None:
    """There is no endpoint that clears the three columns on their own: a record that
    can be erased by itself is not a record."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(maker, project)
    forced = await _move(client, headers, task_id, version, force=True, force_reason="a reason")
    assert forced.status_code == 200

    back = await _move(client, headers, task_id, forced.json()["task"]["version"], stage="verify")
    assert back.status_code == 200

    async with maker() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        assert task.force_done_reason is None
        assert task.force_done_at is None


def test_an_agent_cannot_force() -> None:
    """The CLI has no such subcommand, and the API refuses the field anyway.

    A run credential holds `task.update` — which is exactly why this refusal is
    explicit rather than left to `AGENT_FORBIDDEN_FIELDS`: that set covers the card's
    own columns, and `force` is not a column.
    """
    from pathlib import Path

    from app.api.http.schemas import UpdateTaskRequest

    assert "force" in UpdateTaskRequest.model_fields
    routes = Path(__file__).resolve().parents[3] / "backend/app/api/http/tasks.py"
    assert "An agent may not force a card into done" in routes.read_text(encoding="utf-8")

    # And the agent-facing CLI does not offer the verb at all, for the reason the
    # absent `approve` subcommand already records: a subcommand that exists invites an
    # agent to try it, and what comes back is a 403 it then has to interpret.
    #
    # **Asserted against declarations, not against the substring.** The first version
    # forbade "force" anywhere in the file, which also forbade the comment explaining
    # why the verb is absent — and a guard that punishes documenting the rule is a
    # guard somebody deletes.
    import re

    cli = Path(__file__).resolve().parents[3] / "daemon/internal/cli/command.go"
    body = cli.read_text(encoding="utf-8")
    declarations = re.findall(r'Use:\s*"([^"]+)"', body) + re.findall(
        r'Flags\(\)\.\w+Var\([^,]+,\s*"([^"]+)"', body
    )
    offenders = [name for name in declarations if "force" in name.lower()]
    assert offenders == [], f"the CLI grew a force verb: {offenders}"


# --- the flag, and the door that must not exist ------------------------------


async def test_the_gate_does_not_apply_without_the_runner_layer(
    api: tuple, agent_runs_disabled: None
) -> None:
    """A board-only deployment produces no runs, therefore no reports — so applying the
    gate there would mean no card could ever reach `done` (ADR 0033 §5)."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(maker, project, acceptance_criteria=[{"text": "unverified"}])

    resp = await _move(client, headers, task_id, version)

    assert resp.status_code == 200, resp.text


def test_a_run_never_advances_a_card_into_done() -> None:
    """The gate has one entrance, and the risk is a second one added out of helpfulness.

    **The invariant is about `done`, not about `stage`.** V2.2 already moves a card to
    `blocked` when its attempts are exhausted, and that is legitimate: it is a report
    that the work could not proceed, not a claim that it finished. Writing this as "a
    run never assigns `stage`" would have been wrong in a way that looks stricter — and
    it would have had to be relaxed the first time somebody read it, which is how a
    guard gets deleted.

    Asserted as absence in the module that would host it, the same shape
    `GATE-DV-SINGLE-DONE-PATH` uses: a behavioural test cannot prove a path does not
    exist, only that one particular path does not take it.
    """
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "backend/app/services/runs.py"
    body = source.read_text(encoding="utf-8")
    assignments = re.findall(r"""\.stage\s*=\s*["']([a-z_]+)["']""", body)
    assert "done" not in assignments, (
        "a run advanced a card into done; the Done Gate has exactly one entrance and "
        f"this is the second door (ADR 0033 §5). Assignments found: {assignments}"
    )
    # And the ones that do exist are the V2.2 report, not a completion claim.
    assert set(assignments) <= {"blocked"}, (
        f"a run assigned an unexpected stage: {sorted(set(assignments))}"
    )


# --- process overrides -------------------------------------------------------


async def test_an_unknown_override_key_is_named(api: tuple, projects_enabled: None) -> None:
    """A mistyped key stored is silently ineffective, and the person who typed it
    believes it worked — until it blocks a card weeks later."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)

    resp = await client.put(
        f"/api/projects/{project}/process/overrides",
        json={"readiness_disabled": ["no_such_item"], "gates_disabled": [], "wip": {}},
        headers=headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "PROCESS_OVERRIDE_UNKNOWN_KEY"
    assert "no_such_item" in resp.json()["error"]["details"]["unknown"]


async def test_a_disabled_gate_says_who_disabled_it(api: tuple, projects_enabled: None) -> None:
    """ "this deployment has no tunnel integration" and "this project switched it off"
    send a person to two different people."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    process = (await client.get(f"/api/projects/{project}/process", headers=headers)).json()
    target = next(gate["key"] for gate in process["gates"] if gate["enabled"])

    resp = await client.put(
        f"/api/projects/{project}/process/overrides",
        json={"readiness_disabled": [], "gates_disabled": [target], "wip": {}},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    gate = next(g for g in resp.json()["gates"] if g["key"] == target)
    assert gate["enabled"] is False
    assert gate["disabled_reason"] == "disabled_by_project"


async def test_overrides_cannot_reach_the_done_gate(api: tuple, projects_enabled: None) -> None:
    """The six conditions are service-layer constants, deliberately absent from the
    process definition — otherwise the first person who finds the gate inconvenient
    disables it, and that leaves no trace while `--force` leaves three."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    process = (await client.get(f"/api/projects/{project}/process", headers=headers)).json()

    rendered = repr(process)
    for condition in ("completion_summary", "verification_report", "critical_failure", "delivery"):
        assert condition not in rendered, (
            f"{condition} is reachable through the process definition; the Done Gate "
            "must not be configurable"
        )

    # And the switch that *is* allowed does not weaken it: a card still needs its
    # evidence after every gate is turned off.
    await client.put(
        f"/api/projects/{project}/process/overrides",
        json={
            "readiness_disabled": [],
            "gates_disabled": [g["key"] for g in process["gates"]],
            "wip": {},
        },
        headers=headers,
    )
    task_id, version = await _card(maker, project)
    assert (await _move(client, headers, task_id, version)).status_code == 409


async def test_the_project_level_requirement_is_off_by_default(
    api: tuple, projects_enabled: None
) -> None:
    """A card verified only by its own declared checks passes by default, and is blocked
    once the project asks for a project-level one (ADR 0033 §3b)."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task_id, version = await _card(maker, project)
    await _report(
        maker,
        project,
        task_id,
        checks=[{"name": "card check", "origin": "card", "exit_code": 0}],
    )

    assert (await _move(client, headers, task_id, version)).status_code == 200

    async with maker() as session:
        row = await session.get(Project, project)
        assert row is not None
        row.require_project_verification = True
        await session.commit()

    task_id2, version2 = await _card(maker, project)
    await _report(
        maker,
        project,
        task_id2,
        checks=[{"name": "card check", "origin": "card", "exit_code": 0}],
    )
    blocked = await _move(client, headers, task_id2, version2)
    assert blocked.status_code == 409
    assert any(
        item["key"] == "project_verification"
        for item in blocked.json()["error"]["details"]["missing"]
    )
