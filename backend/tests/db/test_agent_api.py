"""Dispatch refusals, artifact serving, and the two waiting states (AR-04/AR-09).

These three groups had no tests at all until now, and the reason each one needs its own
is the same: they are the places where the phase's decisions live in a *string* or a
*header* rather than in a type, so nothing else would notice them changing.

* **Dispatch's refusals name the thing to fix.** The whole point of nine distinct 409s
  is that "could not dispatch" is useless to the person reading it.
* **The two waiting states read differently.** "The agent you named is offline" and "no
  agent is eligible" lead to different actions; the exit condition asks for two
  assertions on two strings for exactly that reason.
* **An artifact is always a download.** Four headers, and none of them optional.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.db.models import AgentRunner, Node, Project, Role, Task, TaskRun, User
from app.security.passwords import hash_password
from app.services.registry import NodeConnectionRegistry

pytestmark = pytest.mark.asyncio


class _Registry(NodeConnectionRegistry):
    """A registry with a fixed answer to "is this node connected".

    Injected rather than mocked at the call site: `online` is derived from this one
    predicate everywhere, and a test that patched the service instead would stop
    exercising the derivation.
    """

    def __init__(self, online: set[uuid.UUID] | None = None) -> None:
        super().__init__()
        self._online = online or set()

    def is_connected(self, node_id: uuid.UUID) -> bool:  # type: ignore[override]
        return node_id in self._online


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
    tokens = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    access = tokens.json()["tokens"]["access_token"]
    return user.id, {"authorization": f"Bearer {access}"}


async def _project(maker, owner_id: uuid.UUID) -> uuid.UUID:
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
        await session.commit()
        return project.id


async def _card(maker, project_id: uuid.UUID, **fields) -> uuid.UUID:
    async with maker() as session:
        task = Task(
            id=uuid.uuid4(),
            project_id=project_id,
            card_ref=f"TASK-{uuid.uuid4().hex[:4]}",
            title="a card",
            stage=fields.pop("stage", "ready"),
            source=fields.pop("source", "none"),
            delivery=fields.pop("delivery", "none"),
            **fields,
        )
        session.add(task)
        await session.commit()
        return task.id


async def _runner(maker, **fields) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        name = f"r-{uuid.uuid4().hex[:8]}"
        node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
        session.add(node)
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(),
            node_id=node.id,
            name=name,
            runtimes=fields.pop("runtimes", ["claude"]),
            labels=[],
            **fields,
        )
        session.add(runner)
        await session.commit()
        return runner.id, node.id


# --- dispatch refuses in a fixed order, and each refusal names its cause ---- #


async def test_a_card_outside_ready_is_refused(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, stage="backlog")

    response = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_NOT_READY"


async def test_a_card_that_needs_secrets_is_refused_and_names_the_version(
    api: tuple, projects_enabled: None
) -> None:
    """Refused rather than accepted-and-ignored.

    Accepting it would run the card **without** the secrets it says it needs, which
    looks like a broken agent instead of a missing feature.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, required_secrets=["GITHUB_TOKEN"])

    response = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "TASK_REQUIRES_SECRETS"
    # The message says when it starts working, not merely that it does not.
    assert "V2.3" in body["error"]["message"]


async def test_an_unsupported_delivery_names_the_version_it_starts_in(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, delivery="pull_request")

    response = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "TASK_DELIVERY_UNSUPPORTED"
    assert body["error"]["details"]["phase"] == "V2.4"


async def test_a_card_needing_code_without_a_repository_points_at_the_settings_page(
    api: tuple, projects_enabled: None
) -> None:
    """The refusal a person hits first, after the ruling.

    It is a *configuration* problem, so the response carries where to fix it: "missing
    configuration" without saying where is a message nobody can act on.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, source="repo")

    response = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "PROJECT_NO_REPOSITORY"
    assert str(project) in body["error"]["details"]["settings_hint"]


async def test_a_disabled_agent_is_refused_by_name(api: tuple, projects_enabled: None) -> None:
    """Refused at dispatch rather than queued: a disabled agent is a decision somebody
    made, not a machine that will come back."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    runner, _node = await _runner(maker, enabled=False)

    response = await client.post(
        f"/api/tasks/{task}/dispatch", json={"assigned_runner_id": str(runner)}, headers=headers
    )
    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "AGENT_DISABLED"
    # Named, so the person knows which one to enable.
    assert body["error"]["details"]["runner_name"]


async def test_a_card_with_a_run_in_flight_is_refused(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    first = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    assert first.status_code == 202
    second = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "RUN_ALREADY_ACTIVE"


# --- the two waiting states, word for word --------------------------------- #


async def test_an_offline_named_agent_queues_with_its_own_reason(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 4. The two reasons must differ, because the actions differ.

    A named agent that is *ineligible* is refused (above); a named agent that is merely
    **offline** is queued, and the board says which of the two situations it is.
    """
    from app.api.http import agents as agents_api
    from app.main import app

    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    runner, _node = await _runner(maker)

    app.dependency_overrides[agents_api.get_registry] = lambda: _Registry(online=set())
    try:
        response = await client.post(
            f"/api/tasks/{task}/dispatch",
            json={"assigned_runner_id": str(runner)},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(agents_api.get_registry, None)

    assert response.status_code == 202
    assert response.json()["waiting_reason"] == "assigned_offline"


async def test_no_eligible_agent_is_a_different_reason(api: tuple, projects_enabled: None) -> None:
    from app.api.http import agents as agents_api
    from app.main import app

    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    await _runner(maker)

    app.dependency_overrides[agents_api.get_registry] = lambda: _Registry(online=set())
    try:
        response = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    finally:
        app.dependency_overrides.pop(agents_api.get_registry, None)

    assert response.status_code == 202
    reason = response.json()["waiting_reason"]
    assert reason == "no_eligible_runner"
    # And it is genuinely a different value from the one above — the assertion the exit
    # condition actually asks for.
    assert reason != "assigned_offline"


# --- repositories: three fields, never a URL ------------------------------- #


async def test_a_repository_body_cannot_carry_a_url(api: tuple, projects_enabled: None) -> None:
    """The shape *is* the control (ADR 0031 §5).

    A `url` field would receive `https://user:token@host/…` on its first day. Here it
    is not filtered — it does not exist, so the request is unprocessable.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)

    response = await client.post(
        f"/api/projects/{project}/repositories",
        json={"url": "https://user:token@github.com/a/b"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_a_host_outside_the_deployment_allowlist_is_refused(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)

    response = await client.post(
        f"/api/projects/{project}/repositories",
        json={
            "scheme": "https",
            "host": "evil.example",
            "path": "a/b",
            "default_branch": "main",
        },
        headers=headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "REPOSITORY_HOST_NOT_ALLOWED"
    # The empty default allows nothing, which is the right default for a deployment
    # that has not decided yet — so the message has to name the host.
    assert "evil.example" in body["error"]["message"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "../../etc/passwd"),
        ("path", "/absolute"),
        # A branch beginning with `-` would be read by git as a flag, and a closed argv
        # table cannot protect a value that *is* one.
        ("default_branch", "--upload-pack=touch /tmp/x"),
    ],
    ids=["traversal", "absolute", "flag-shaped-branch"],
)
async def test_repository_fields_are_validated(
    api: tuple, projects_enabled: None, field: str, value: str
) -> None:
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    body = {"scheme": "https", "host": "github.com", "path": "a/b", "default_branch": "main"}
    body[field] = value

    response = await client.post(
        f"/api/projects/{project}/repositories", json=body, headers=headers
    )
    assert response.status_code == 400


# --- artifacts are always a download --------------------------------------- #


async def _attach(client, headers, task: uuid.UUID, filename: str, data: bytes):
    return await client.post(
        f"/api/tasks/{task}/artifacts",
        files={"file": (filename, data, "text/html")},
        headers=headers,
    )


async def test_an_html_artifact_is_stored_as_binary_and_served_as_a_download(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 19, at the response level.

    The uploader's declared `text/html` is discarded; the extension is not on the
    allowlist, so the content type becomes binary. And the download carries four
    headers, none of them optional — a single-origin deployment has nowhere safe to
    render an uploaded file.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    created = await _attach(client, headers, task, "report.html", b"<script>alert(1)</script>")
    assert created.status_code == 201
    artifact = created.json()
    assert artifact["content_type"] == "application/octet-stream"
    assert artifact["previewable"] is False

    download = await client.get(f"/api/artifacts/{artifact['id']}", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/octet-stream")
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in download.headers["content-security-policy"]

    # And there is no preview for it at all — 404 rather than 403, because whether a
    # preview exists should not itself be a signal.
    preview = await client.get(f"/api/artifacts/{artifact['id']}/preview", headers=headers)
    assert preview.status_code == 404


async def test_a_markdown_file_containing_html_is_previewed_as_plain_text(
    api: tuple, projects_enabled: None
) -> None:
    """The case the allowlist is really for. `report.md` passes every text check there
    is, and rendering it would execute the HTML inside."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    created = await _attach(client, headers, task, "report.md", b"<script>alert(1)</script>")
    artifact = created.json()
    assert artifact["content_type"] == "text/markdown"

    preview = await client.get(f"/api/artifacts/{artifact['id']}/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("text/plain")
    assert preview.headers["x-content-type-options"] == "nosniff"


async def test_a_patch_stays_previewable(api: tuple, projects_enabled: None) -> None:
    """The commonest artifact a run produces. Making it download-only would quietly
    train people to stop attaching diffs."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    created = await _attach(client, headers, task, "changes.patch", b"--- a\n+++ b\n")
    artifact = created.json()
    assert artifact["content_type"] == "text/plain"
    assert artifact["previewable"] is True


async def test_a_filename_cannot_inject_a_header(api: tuple, projects_enabled: None) -> None:
    """RFC 5987 percent-encoding, so quotes and CRLF are unrepresentable rather than
    filtered."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    created = await _attach(client, headers, task, 'a"b\r\nX-Evil: 1.txt', b"x")
    artifact = created.json()
    download = await client.get(f"/api/artifacts/{artifact['id']}", headers=headers)
    disposition = download.headers["content-disposition"]
    assert "\r" not in disposition and '"' not in disposition
    assert "x-evil" not in {key.lower() for key in download.headers}


async def test_a_truncated_upload_is_refused_rather_than_stored(
    api: tuple, projects_enabled: None
) -> None:
    """Not tamper protection — the connection is TLS. It catches a cut-off upload,
    which should fail rather than become a broken artifact nobody can open."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    response = await client.post(
        f"/api/tasks/{task}/artifacts",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"sha256": "00" * 32},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ARTIFACT_DIGEST_MISMATCH"


async def test_deleting_an_artifact_keeps_the_record_and_frees_the_bytes(
    api: tuple, projects_enabled: None
) -> None:
    """The asymmetry, asserted. Requiring a reason is pointless if the delete erases
    who gave it; a quota that cannot be freed by deleting something is not a quota."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    artifact = (await _attach(client, headers, task, "a.txt", b"hello")).json()

    refused = await client.request(
        "DELETE", f"/api/artifacts/{artifact['id']}", json={"reason": ""}, headers=headers
    )
    assert refused.status_code == 422

    deleted = await client.request(
        "DELETE",
        f"/api/artifacts/{artifact['id']}",
        json={"reason": "含有一段不該外流的輸出"},
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert deleted.json()["delete_reason"] == "含有一段不該外流的輸出"

    # Metadata stays and is still listed; the bytes are gone.
    listing = await client.get(f"/api/tasks/{task}/artifacts", headers=headers)
    assert [row["id"] for row in listing.json()] == [artifact["id"]]
    gone = await client.get(f"/api/artifacts/{artifact['id']}", headers=headers)
    assert gone.status_code == 410
    assert gone.json()["error"]["code"] == "ARTIFACT_DELETED"


async def test_an_artifact_outlives_its_run_and_its_logs(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 17. Artifacts follow the card; a run's record does not.

    Simulated by deleting the run outright, which is stronger than the retention sweep:
    if the artifact survives its run row disappearing, it survives the sweep.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    artifact = (await _attach(client, headers, task, "a.txt", b"hello")).json()

    async with maker() as session:
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task,
            project_id=project,
            seq=1,
            status="succeeded",
            source_kind="none",
        )
        session.add(run)
        await session.commit()
        await session.execute(sa.delete(TaskRun).where(TaskRun.id == run.id))
        await session.commit()

    still_there = await client.get(f"/api/artifacts/{artifact['id']}", headers=headers)
    assert still_there.status_code == 200
    assert still_there.content == b"hello"


# --- both flags off ---------------------------------------------------------- #


async def test_every_agent_route_is_absent_when_the_inner_flag_is_off(
    api: tuple, agent_runs_disabled: None
) -> None:
    """404, never 403. A 403 confirms the route exists, which is what the bare 404
    withholds — and the project layer being on makes this the interesting case."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    for method, path in [
        ("GET", "/api/agents"),
        ("GET", f"/api/projects/{project}/repositories"),
        ("POST", f"/api/tasks/{task}/dispatch"),
        ("GET", f"/api/tasks/{task}/runs"),
        ("GET", f"/api/tasks/{task}/messages"),
        ("GET", f"/api/tasks/{task}/artifacts"),
        ("GET", f"/api/artifacts/{uuid.uuid4()}"),
    ]:
        response = await client.request(method, path, json={}, headers=headers)
        assert response.status_code == 404, f"{method} {path} answered {response.status_code}"


# --- quotas, and what a refusal must not leave behind ----------------------- #


@pytest.fixture
def tiny_artifact_quota():
    """A project quota small enough to hit with two small files.

    Overridden rather than approached with a megabyte of uploads: the property under
    test is the *refusal*, and a test that has to move real data to reach it is one
    somebody eventually marks slow and skips.
    """
    from app.main import app
    from app.settings import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        projects_enabled=True,
        agent_runs_enabled=True,
        # Rounded to whole MB by the setting's unit, so the first upload fits and the
        # second does not.
        artifact_project_quota_mb=1,
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_a_full_project_quota_refuses_and_writes_nothing(
    api: tuple, tiny_artifact_quota: None
) -> None:
    """Exit condition 20, and the half that is easy to miss.

    413 with `details`, so the CLI can say "this project's artifact space is full
    (1.0 / 1.0 MB)" rather than "upload failed" — the numbers are what tell somebody
    whether to delete one file or ask for more space.

    And **nothing is half-written.** The quota is checked before the row, so a refused
    upload must not leave a metadata row pointing at a blob that was never stored: the
    artifact list would then show a file that 404s on download, which is worse than the
    refusal it came from.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)

    first = await _attach(client, headers, task, "big.txt", b"x" * (900 * 1024))
    assert first.status_code == 201

    before = (await client.get(f"/api/tasks/{task}/artifacts", headers=headers)).json()

    refused = await _attach(client, headers, task, "over.txt", b"y" * (400 * 1024))
    assert refused.status_code == 413
    body = refused.json()["error"]
    assert body["code"] == "ARTIFACT_PROJECT_QUOTA"
    # Both numbers. "Full" without them cannot be acted on.
    assert body["details"]["used"] > 0
    assert body["details"]["limit"] == 1024 * 1024

    after = (await client.get(f"/api/tasks/{task}/artifacts", headers=headers)).json()
    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert not any(row["filename"] == "over.txt" for row in after)
    # The blob table too: a row-less blob is the same bug from the other side.
    async with maker() as session:
        stored = (
            await session.execute(
                sa.text(
                    "select count(*) from task_artifact_blobs b "
                    "join task_artifacts a on a.id = b.artifact_id "
                    "where a.task_id = :task_id"
                ),
                {"task_id": task},
            )
        ).scalar_one()
    assert stored == len(after)


async def test_a_run_may_not_bury_a_card_under_artifacts(
    api: tuple, projects_enabled: None
) -> None:
    """The per-run count limit, which is a different guard from the byte quota.

    A loop that attaches one file per iteration satisfies every byte check for a long
    time while making the card unreadable, so the count is capped separately and the
    refusal names the count — the reader can tell this from running out of space.

    Driven with the **run credential**, because that is the only way to attach to a run:
    the human upload route passes `run_id=None` on purpose, so a person's file is a
    card's attachment rather than some run's output.
    """
    from app.services.agent_auth import RunTokenService, RunTokenSubject
    from app.settings import get_settings

    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    limit = get_settings().artifact_run_max_count

    async with maker() as session:
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task,
            project_id=project,
            seq=1,
            status="running",
            source_kind="none",
        )
        session.add(run)
        await session.flush()
        issued = await RunTokenService(session).issue(
            run=RunTokenSubject(
                run_id=run.id, project_id=project, task_id=task, timeout_seconds=3600
            )
        )
        await session.commit()
    agent_headers = {"authorization": f"Bearer {issued.value}"}

    for index in range(limit):
        created = await client.post(
            "/api/cli/runs/artifacts",
            files={"file": (f"a{index}.txt", b"x", "text/plain")},
            headers=agent_headers,
        )
        assert created.status_code == 201, created.text

    refused = await client.post(
        "/api/cli/runs/artifacts",
        files={"file": ("one-too-many.txt", b"x", "text/plain")},
        headers=agent_headers,
    )
    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "ARTIFACT_RUN_LIMIT"
    assert refused.json()["error"]["details"]["limit"] == limit


# --- the interactive half of the product, untouched ------------------------- #


async def test_a_run_does_not_create_or_disturb_a_terminal_session(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 16, as a row count.

    A run and an interactive session share a node, a daemon and a WebSocket, and the
    cheapest way for the run path to break V1 would be to reuse the session machinery —
    open a session to run the agent in, or recycle one that exists. Either would show up
    here and nowhere else, because both would still *work*.

    The count is taken across the whole table rather than per project: a run leaking a
    session on some other project's node is the same defect and would pass a narrower
    assertion.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    runner_id, node_id = await _runner(maker)

    async def sessions() -> int:
        async with maker() as session:
            return (
                await session.execute(sa.text("select count(*) from terminal_sessions"))
            ).scalar_one()

    before = await sessions()

    from app.api.http import agents as agents_module

    registry = _Registry(online={node_id})
    app = client._transport.app  # noqa: SLF001 - the app under test
    app.dependency_overrides[agents_module.get_registry] = lambda: registry
    try:
        dispatched = await client.post(
            f"/api/tasks/{task}/dispatch",
            json={"assigned_runner_id": str(runner_id)},
            headers=headers,
        )
        assert dispatched.status_code == 202, dispatched.text

        # And on through the claim, which is the step that would reach for a session if
        # anything were going to.
        async with maker() as session:
            run_id = uuid.UUID(dispatched.json()["run_id"])
            run = await session.get(TaskRun, run_id)
            assert run is not None
            run.status = "running"
            run.runner_id = runner_id
            await session.commit()

        assert await sessions() == before, "dispatching a run created a terminal session"
    finally:
        app.dependency_overrides.pop(agents_module.get_registry, None)

    assert await sessions() == before
