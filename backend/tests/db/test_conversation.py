"""The properties V2-C1 exists to establish (`FR-CONV-001`…`-010`, ADR 0035/0036/0037).

Almost every failure this phase can produce is either **something that did not happen**
or **something that happened twice**, and neither leaves a stack trace. So the tests
here are shaped as three kinds of assertion rather than as feature walk-throughs:

* uniqueness — one answer produces one message and one turn, however many times it is
  sent;
* atomicity — the answer, the closed question and the queued turn arrive together or
  not at all;
* impossibility — a run credential cannot write a decision, and a comment cannot wake
  an agent.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa

from app.db.models import (
    AgentRunner,
    Node,
    Role,
    Task,
    TaskMessage,
    TaskQuestion,
    TaskRun,
    User,
)
from app.security.passwords import hash_password
from app.services.agent_auth import RunTokenService, RunTokenSubject

pytestmark = pytest.mark.asyncio


async def _actor(client, maker, role_name: str = "Admin") -> tuple[uuid.UUID, dict[str, str]]:
    name = f"cv-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        user = User(
            id=uuid.uuid4(),
            username=name,
            display_name=name,
            password_hash=hash_password("pw-12345678"),
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        user_id = user.id
    login = await client.post("/api/auth/login", json={"username": name, "password": "pw-12345678"})
    assert login.status_code == 200, login.text
    access = login.json()["tokens"]["access_token"]
    return user_id, {"authorization": f"Bearer {access}"}


async def _card(client, headers, *, stage: str = "ready") -> tuple[dict, dict]:
    name = f"cv-{uuid.uuid4().hex[:8]}"
    project = await client.post("/api/projects", json={"name": name, "slug": name}, headers=headers)
    assert project.status_code == 201, project.text
    body = {"title": "支援 SAML SSO", "source": "none", "delivery": "none"}
    card = await client.post(
        f"/api/projects/{project.json()['id']}/tasks", json=body, headers=headers
    )
    assert card.status_code == 201, card.text
    task = card.json()["task"]
    if stage != task["stage"]:
        await client.patch(
            f"/api/tasks/{task['id']}",
            json={"stage": stage, "version": task["version"]},
            headers=headers,
        )
    return project.json(), task


async def _run(
    maker, project_id: str, task_id: str, *, status: str = "running"
) -> tuple[str, uuid.UUID]:
    """A claimed run on this card, plus its credential."""
    async with maker() as session:
        node = Node(
            id=uuid.uuid4(),
            name=f"n-{uuid.uuid4().hex[:6]}",
            hostname=f"{uuid.uuid4().hex[:6]}.invalid",
            status="online",
        )
        session.add(node)
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(), node_id=node.id, name=node.name, runtimes=["claude"], labels=[]
        )
        session.add(runner)
        await session.flush()
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=uuid.UUID(task_id),
            project_id=uuid.UUID(project_id),
            seq=1,
            status=status,
            runner_id=runner.id,
            source_kind="none",
            root_run_id=None,
        )
        session.add(run)
        await session.flush()
        run.root_run_id = run.id
        issued = await RunTokenService(session).issue(
            run=RunTokenSubject(
                run_id=run.id,
                project_id=uuid.UUID(project_id),
                task_id=uuid.UUID(task_id),
                timeout_seconds=3600,
            )
        )
        await session.commit()
        return issued.value, run.id


# --- uniqueness -----------------------------------------------------------


async def test_the_sequence_is_gapless_under_concurrent_writers(
    api: tuple, projects_enabled: None
) -> None:
    """Twenty writers on one card produce 1..20, each exactly once.

    The counter lives on the card and is taken with `UPDATE … RETURNING`, so the card's
    row lock serialises writers to *that* card. A `SEQUENCE` would be gapless globally
    and holed here; `max(seq)+1` would duplicate.
    """
    client, maker = api
    _user, headers = await _actor(client, maker)
    _project, task = await _card(client, headers)

    async def post(index: int):
        return await client.post(
            f"/api/tasks/{task['id']}/messages",
            json={"body": f"訊息 {index}", "kind": "comment"},
            headers=headers,
        )

    responses = await asyncio.gather(*(post(i) for i in range(20)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]

    async with maker() as session:
        seqs = sorted(
            (
                await session.execute(
                    sa.select(TaskMessage.conversation_seq).where(
                        TaskMessage.task_id == uuid.UUID(task["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
    assert seqs == list(range(1, 21))


async def test_the_same_idempotency_key_writes_one_message(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _user, headers = await _actor(client, maker)
    _project, task = await _card(client, headers)
    payload = {"body": "同一句話", "kind": "comment", "idempotency_key": "k-1"}

    first = await client.post(f"/api/tasks/{task['id']}/messages", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    for _ in range(9):
        again = await client.post(
            f"/api/tasks/{task['id']}/messages", json=payload, headers=headers
        )
        # 200, not 201: a retry that reports "created" teaches a client to distrust the
        # status it gets.
        assert again.status_code == 200, again.text
        assert again.json()["id"] == first.json()["id"]

    async with maker() as session:
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskMessage)
                .where(TaskMessage.task_id == uuid.UUID(task["id"]))
            )
        ).scalar()
    assert count == 1


async def test_the_same_key_with_different_content_is_refused(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _user, headers = await _actor(client, maker)
    _project, task = await _card(client, headers)
    await client.post(
        f"/api/tasks/{task['id']}/messages",
        json={"body": "A", "kind": "comment", "idempotency_key": "k-2"},
        headers=headers,
    )
    clash = await client.post(
        f"/api/tasks/{task['id']}/messages",
        json={"body": "B", "kind": "comment", "idempotency_key": "k-2"},
        headers=headers,
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "MESSAGE_IDEMPOTENCY_CONFLICT"


# --- atomicity ------------------------------------------------------------


async def test_answering_closes_the_question_and_queues_exactly_one_turn(
    api: tuple, projects_enabled: None
) -> None:
    """The main path: an agent asks, exits, a person answers, and one turn is queued."""
    client, maker = api
    _user, headers = await _actor(client, maker)
    project, task = await _card(client, headers)
    token, run_id = await _run(maker, project["id"], task["id"])
    agent = {"authorization": f"Bearer {token}"}

    asked = await client.post(
        "/api/cli/runs/messages",
        json={"body": "SP metadata 要放哪個路徑？", "kind": "question"},
        headers=agent,
    )
    assert asked.status_code == 201, asked.text

    # The agent's process ends. Before V2-C1 this closed the conversation.
    async with maker() as session:
        run = await session.get(TaskRun, run_id)
        run.status = "succeeded"
        run.result = "awaiting_input"
        await session.commit()

    questions = await client.get(f"/api/tasks/{task['id']}/questions?state=open", headers=headers)
    assert questions.status_code == 200
    assert len(questions.json()) == 1
    question_id = questions.json()[0]["id"]

    answered = await client.post(
        f"/api/tasks/{task['id']}/questions/{question_id}/answer",
        json={"body": "/saml/metadata", "resume": True},
        headers=headers,
    )
    assert answered.status_code == 201, answered.text
    assert answered.json()["mode"] == "new_turn"
    continuation = answered.json()["continuation_run_id"]
    assert continuation is not None

    async with maker() as session:
        children = list(
            (
                await session.execute(sa.select(TaskRun).where(TaskRun.parent_run_id == run_id))
            ).scalars()
        )
        question = await session.get(TaskQuestion, uuid.UUID(question_id))
        card = await session.get(Task, uuid.UUID(task["id"]))
    assert len(children) == 1
    assert children[0].turn_seq == 2
    assert children[0].root_run_id == run_id
    assert children[0].input_to_seq == answered.json()["message"]["conversation_seq"]
    assert question.state == "answered"
    # The card stops saying it is waiting for a person the moment the answer lands.
    assert card.waiting_for_actor == "agent"
    assert card.open_question_count == 0


async def test_two_people_answering_one_question_produce_one_turn(
    api: tuple, projects_enabled: None
) -> None:
    """One 201 and one recoverable 409 — and the loser can read the answer."""
    client, maker = api
    _user, headers = await _actor(client, maker)
    project, task = await _card(client, headers)
    token, run_id = await _run(maker, project["id"], task["id"])
    await client.post(
        "/api/cli/runs/messages",
        json={"body": "要支援 IdP-initiated 嗎？", "kind": "question"},
        headers={"authorization": f"Bearer {token}"},
    )
    async with maker() as session:
        run = await session.get(TaskRun, run_id)
        run.status = "succeeded"
        await session.commit()
    question_id = (
        await client.get(f"/api/tasks/{task['id']}/questions?state=open", headers=headers)
    ).json()[0]["id"]

    url = f"/api/tasks/{task['id']}/questions/{question_id}/answer"
    both = await asyncio.gather(
        client.post(url, json={"body": "要", "resume": True}, headers=headers),
        client.post(url, json={"body": "不要", "resume": True}, headers=headers),
    )
    codes = sorted(r.status_code for r in both)
    assert codes == [201, 409], [r.text for r in both]
    loser = next(r for r in both if r.status_code == 409)
    assert loser.json()["error"]["code"] == "QUESTION_ALREADY_ANSWERED"
    # Enough to show "陳小美 answered at 14:32" and offer a jump to the reply.
    assert loser.json()["error"]["details"]["answered_message_id"]

    async with maker() as session:
        children = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskRun)
                .where(TaskRun.parent_run_id == run_id)
            )
        ).scalar()
    assert children == 1


async def test_a_comment_does_not_wake_an_agent(api: tuple, projects_enabled: None) -> None:
    """Twenty comments create no turn and change no run state (E2E-J6, in miniature)."""
    client, maker = api
    _user, headers = await _actor(client, maker)
    project, task = await _card(client, headers)
    token, run_id = await _run(maker, project["id"], task["id"])
    await client.post(
        "/api/cli/runs/messages",
        json={"body": "要用哪個雜湊？", "kind": "question"},
        headers={"authorization": f"Bearer {token}"},
    )
    async with maker() as session:
        run = await session.get(TaskRun, run_id)
        run.status = "succeeded"
        await session.commit()

    for index in range(20):
        posted = await client.post(
            f"/api/tasks/{task['id']}/messages",
            json={"body": f"補充 {index}", "kind": "comment"},
            headers=headers,
        )
        assert posted.status_code == 201, posted.text

    async with maker() as session:
        runs = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskRun)
                .where(TaskRun.task_id == uuid.UUID(task["id"]))
            )
        ).scalar()
        card = await session.get(Task, uuid.UUID(task["id"]))
    assert runs == 1, "a comment must not queue a turn"
    # And the question is still open: the asking run has ended, so a comment does not
    # close it either — closing it would leave a card that looks idle while nobody is
    # working on it.
    assert card.open_question_count == 1
    assert card.waiting_for_actor == "human"


async def test_a_comment_unblocks_an_agent_that_is_still_running(
    api: tuple, projects_enabled: None
) -> None:
    """V2.5's rule, kept for the case V2.5 covered.

    A person who replies without pressing "回覆並繼續" must not leave a live agent
    unable to ask anything ever again. So a comment closes the question **while the
    asking run is still up** — which is exactly when the agent will read it on its next
    poll — and still creates no turn.
    """
    client, maker = api
    _user, headers = await _actor(client, maker)
    project, task = await _card(client, headers)
    token, _run_id = await _run(maker, project["id"], task["id"])
    agent = {"authorization": f"Bearer {token}"}
    await client.post(
        "/api/cli/runs/messages", json={"body": "第一題？", "kind": "question"}, headers=agent
    )
    blocked = await client.post(
        "/api/cli/runs/messages", json={"body": "第二題？", "kind": "question"}, headers=agent
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "QUESTION_ALREADY_PENDING"

    await client.post(
        f"/api/tasks/{task['id']}/messages",
        json={"body": "先照你想的做", "kind": "comment"},
        headers=headers,
    )
    unblocked = await client.post(
        "/api/cli/runs/messages", json={"body": "第二題？", "kind": "question"}, headers=agent
    )
    assert unblocked.status_code == 201, unblocked.text


# --- impossibility --------------------------------------------------------


async def test_a_run_credential_cannot_write_a_decision(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _user, headers = await _actor(client, maker)
    project, task = await _card(client, headers)
    token, _run_id = await _run(maker, project["id"], task["id"])
    refused = await client.post(
        "/api/cli/runs/messages",
        json={"body": "我接受這份規格", "kind": "decision"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "AGENT_CANNOT_DECIDE"


async def test_a_viewer_reads_the_thread_and_cannot_write(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _owner, owner_headers = await _actor(client, maker)
    _project, task = await _card(client, owner_headers)
    _viewer, viewer_headers = await _actor(client, maker, role_name="Viewer")

    readable = await client.get(f"/api/tasks/{task['id']}/messages", headers=viewer_headers)
    assert readable.status_code == 200
    refused = await client.post(
        f"/api/tasks/{task['id']}/messages",
        json={"body": "我也想說話", "kind": "comment"},
        headers=viewer_headers,
    )
    assert refused.status_code == 403


async def test_a_decision_is_gated_on_task_approve_which_only_a_token_lacks(
    api: tuple, projects_enabled: None
) -> None:
    """A Developer writes a decision; a run credential does not — and that is the point.

    `task.approve` and `task.update` have **deliberately identical human holders**
    (ADR 0028, `rbac.py:103`). Splitting them separates nothing at the role layer; the
    entire effect is that a credential's scope can exclude approval, and an action that
    does not exist cannot be excluded from a scope.

    So the assertion worth making is not "some role is refused" — it is that the gate
    is `task.approve` at all, which is what makes `RUN_TOKEN_SCOPES` able to omit it.
    """
    client, maker = api
    _owner, owner_headers = await _actor(client, maker)
    project, task = await _card(client, owner_headers)
    _dev, dev_headers = await _actor(client, maker, role_name="Developer")

    decision = await client.post(
        f"/api/tasks/{task['id']}/messages",
        json={"body": "接受", "kind": "decision"},
        headers=dev_headers,
    )
    assert decision.status_code == 201, decision.text
    assert decision.json()["kind"] == "decision"

    token, _run_id = await _run(maker, project["id"], task["id"])
    refused = await client.post(
        "/api/cli/runs/messages",
        json={"body": "接受", "kind": "decision"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "AGENT_CANNOT_DECIDE"


async def test_a_cursor_beyond_the_card_is_refused(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _user, headers = await _actor(client, maker)
    _project, task = await _card(client, headers)
    ahead = await client.get(f"/api/tasks/{task['id']}/messages?after_seq=9999", headers=headers)
    assert ahead.status_code == 409
    assert ahead.json()["error"]["code"] == "CONVERSATION_CURSOR_AHEAD"


async def test_the_cursor_page_is_stable_across_identical_timestamps(
    api: tuple, projects_enabled: None
) -> None:
    """The defect `--since` had: two messages, one timestamp, and a page that lies."""
    client, maker = api
    _user, headers = await _actor(client, maker)
    _project, task = await _card(client, headers)
    for index in range(5):
        await client.post(
            f"/api/tasks/{task['id']}/messages",
            json={"body": f"m{index}", "kind": "comment"},
            headers=headers,
        )
    async with maker() as session:
        # Force the tie the old pagination could not break.
        rows = list(
            (
                await session.execute(
                    sa.select(TaskMessage).where(TaskMessage.task_id == uuid.UUID(task["id"]))
                )
            ).scalars()
        )
        stamp = rows[0].created_at
        for row in rows:
            row.created_at = stamp
        await session.commit()

    seen: list[int] = []
    cursor = 0
    while True:
        page = await client.get(
            f"/api/tasks/{task['id']}/messages?after_seq={cursor}&limit=2", headers=headers
        )
        assert page.status_code == 200, page.text
        body = page.json()
        seen.extend(item["conversation_seq"] for item in body["items"])
        if not body["has_more"]:
            break
        cursor = body["next_after_seq"]
    assert seen == [1, 2, 3, 4, 5]


async def test_message_too_large_is_a_machine_code(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _user, headers = await _actor(client, maker)
    _project, task = await _card(client, headers)
    too_long = await client.post(
        f"/api/tasks/{task['id']}/messages",
        json={"body": "字" * 20_001, "kind": "comment"},
        headers=headers,
    )
    assert too_long.status_code == 400
    assert too_long.json()["error"]["code"] == "MESSAGE_TOO_LARGE"
    assert too_long.json()["error"]["details"]["limit"] == 20_000


async def test_deleting_every_run_log_leaves_the_conversation_intact(
    api: tuple, projects_enabled: None
) -> None:
    """The sentence "a log is a diagnostic, a message is product data", as an assertion."""
    from app.db.models import RunLog

    client, maker = api
    _user, headers = await _actor(client, maker)
    project, task = await _card(client, headers)
    token, run_id = await _run(maker, project["id"], task["id"])
    await client.post(
        "/api/cli/runs/messages",
        json={"body": "這裡有兩種做法，要選哪一個？", "kind": "question"},
        headers={"authorization": f"Bearer {token}"},
    )
    async with maker() as session:
        session.add(RunLog(id=uuid.uuid4(), run_id=run_id, seq=1, data="noisy diagnostics"))
        await session.commit()
    async with maker() as session:
        await session.execute(sa.delete(RunLog).where(RunLog.run_id == run_id))
        await session.commit()

    thread = await client.get(f"/api/tasks/{task['id']}/messages", headers=headers)
    assert thread.status_code == 200
    assert [m["kind"] for m in thread.json()["items"]] == ["question"]
    questions = await client.get(f"/api/tasks/{task['id']}/questions?state=open", headers=headers)
    assert len(questions.json()) == 1


async def test_a_secret_value_is_redacted_before_it_is_stored(
    api: tuple, projects_enabled: None
) -> None:
    """The channel the daemon's redactor cannot see (ADR 0037 §3).

    That one wraps the protocol `send`, so it covers `run.failed`'s stderr and
    `run.complete`'s summary. `cliora task say` is an HTTPS request to Central and never
    passes through it — so the one channel an agent uses to write prose was the one
    channel the redaction did not cover.

    Asserted on the **stored row**, not on the response: storing the value is the thing
    being prevented, so checking anything downstream of the insert would pass even if
    the value were on disk.
    """
    from app.db.models import Project as ProjectModel
    from app.db.models import ProjectSecret
    from app.services.secrets import SecretService

    client, maker = api
    user_id, headers = await _actor(client, maker)
    project, task = await _card(client, headers)
    value = "ghp_thisisasecrettokenvalue"

    async with maker() as session:
        row = await session.get(ProjectModel, uuid.UUID(project["id"]))
        row.allowed_secret_names = ["GITHUB_TOKEN"]
        await session.flush()
        await SecretService(session).create(
            project=row, name="GITHUB_TOKEN", kind="env", value=value, actor_id=user_id
        )
        card = await session.get(Task, uuid.UUID(task["id"]))
        card.required_secrets = ["GITHUB_TOKEN"]
        await session.commit()

    token, _run_id = await _run(maker, project["id"], task["id"])
    posted = await client.post(
        "/api/cli/runs/messages",
        json={"body": f"用這個 token 打的：{value}", "kind": "comment"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert posted.status_code == 201, posted.text

    async with maker() as session:
        stored = (
            await session.execute(
                sa.select(TaskMessage.body).where(
                    TaskMessage.task_id == uuid.UUID(task["id"]),
                    TaskMessage.author_kind == "agent",
                )
            )
        ).scalar_one()
    assert value not in stored
    assert "[redacted:GITHUB_TOKEN]" in stored

    # And nothing was recorded as a delivery: reading the value in order to *avoid*
    # storing it is not the same act as handing it to a node.
    async with maker() as session:
        secret = (
            await session.execute(
                sa.select(ProjectSecret).where(ProjectSecret.name == "GITHUB_TOKEN")
            )
        ).scalar_one()
    assert secret.last_used_at is None
