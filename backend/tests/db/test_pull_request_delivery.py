"""Opening the pull request: four outcomes, one request, and no token in any log.

FR-DELIVERY-003/004, ADR 0033 §3.

Two of these are worth more than the rest.

`test_a_timeout_sends_exactly_one_request` — the HTTP convention is to retry, and
creation is not idempotent: a timeout that actually arrived becomes a second pull
request on somebody's repository. The assertion counts requests rather than checking a
flag, because a retry added later would still pass a flag check written today.

`test_the_token_never_appears_in_a_log_record` — the error body is what a person pastes
into a ticket, which makes it a higher-risk place for a credential than a log line
collected by accident.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa

from app.db.models import Project, ProjectRepository, ProjectSecret, Role, Task, TaskRun, User
from app.security import secret_envelope
from app.security.passwords import hash_password
from app.services.deliveries import BRANCH_ONLY, DELIVERED, PENDING, DeliveryService
from app.services.providers import GitHubAdapter, ProviderError, owner_repo
from app.settings import Settings

pytestmark = pytest.mark.asyncio

TEST_MASTER_KEY = "3q2+796tvu/erb7v3q2+796tvu/erb7v3q2+796tvu8="


class FakeProvider:
    """`cmd/fakeprovider`, in-process.

    Four modes and **a request counter**. The counter is the point: "no pull request was
    opened" has to be checked by "the provider was never called", because "no PR exists"
    is trivially true on a machine with no network (plan/21/08-…md §2).
    """

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.requests: list[tuple[str, str]] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.method == "GET":
            if self.mode == "existing":
                return httpx.Response(
                    200, json=[{"number": 7, "html_url": "https://x.invalid/pr/7"}]
                )
            return httpx.Response(200, json=[])
        if self.mode == "forbidden":
            return httpx.Response(403, json={"message": "Resource not accessible"})
        if self.mode == "unprocessable":
            return httpx.Response(422, json={"message": "Field base is invalid"})
        if self.mode == "hang":
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(
            201, json={"number": 12, "html_url": "https://github.invalid/o/r/pull/12"}
        )


def _adapter(fake: FakeProvider, settings: Settings | None = None) -> GitHubAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    return GitHubAdapter(settings or Settings(), client=client)


# --- the adapter's shape -----------------------------------------------------


def test_the_verb_table_is_closed() -> None:
    """Red line 5 as an absence, which is how it is verifiable.

    A check has a second call site; a table that does not contain the word does not.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "backend/app/services/providers.py").read_text(
        encoding="utf-8"
    )
    # Split so the words in this test's own explanation do not match themselves.
    for verb in ("merge", "approve", "review", "close", "delete", "release", "tag"):
        for shape in (f'"{verb}', f"/{verb}", f"def {verb}"):
            assert shape not in source.lower(), (
                f"the provider adapter grew a {verb} action; the platform never merges, "
                "approves its own pull request, closes anyone's, or touches a tag"
            )


def test_owner_and_repo_come_from_the_stored_path_not_a_url() -> None:
    """Parsing an owner out of a free-form URL is how `github.com@evil.example` gets in —
    the same argument that made `ProjectRepository` three columns."""
    assert owner_repo("/Lei-k/Traqora") == ("Lei-k", "Traqora")
    assert owner_repo("Lei-k/Traqora.git") == ("Lei-k", "Traqora")
    for bad in ("", "/", "https://github.com/o/r", "o/r/extra", "../../etc"):
        with pytest.raises(ProviderError):
            owner_repo(bad)


async def test_a_host_outside_the_allowlist_is_refused() -> None:
    fake = FakeProvider()
    settings = Settings(provider_api_base="https://evil.invalid")
    with pytest.raises(ProviderError) as caught:
        await _adapter(fake, settings).create_pull_request(
            repo_path="/o/r", head="cliora/x-1", base="main", title="t", body="b", token="tok"
        )
    assert "does not allow" in caught.value.message
    # Refused **before** the request, not by inspecting the response.
    assert fake.requests == []


async def test_a_timeout_sends_exactly_one_request() -> None:
    """Creation is not idempotent, so a timeout is a failure rather than a retry."""
    fake = FakeProvider("hang")
    with pytest.raises(ProviderError) as caught:
        await _adapter(fake).create_pull_request(
            repo_path="/o/r", head="cliora/x-1", base="main", title="t", body="b", token="tok"
        )
    assert caught.value.code == "PROVIDER_UNREACHABLE"
    creates = [r for r in fake.requests if r[0] == "POST"]
    assert len(creates) == 1, f"a timeout produced {len(creates)} creation attempts"


async def test_the_token_never_appears_in_an_error(caplog: pytest.LogCaptureFixture) -> None:
    """The provider's own words reach the user; the credential does not."""
    token = "ghp_averysecrettokenvalue1234"

    async def echo(request: httpx.Request) -> httpx.Response:
        # A provider that reflects the header back, which is the worst realistic case.
        return httpx.Response(403, text=f"bad credential {token}")

    adapter = GitHubAdapter(
        Settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(echo))
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderError) as caught:
            await adapter.create_pull_request(
                repo_path="/o/r", head="cliora/x-1", base="main", title="t", body="b", token=token
            )

    assert token not in caught.value.message
    assert "***" in caught.value.message
    for record in caplog.records:
        assert token not in record.getMessage()


# --- the worker --------------------------------------------------------------


async def _fixture(maker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        user = User(
            id=uuid.uuid4(),
            username=f"u-{uuid.uuid4().hex[:8]}",
            display_name="u",
            password_hash=hash_password("pw"),
            role_id=role.id,
        )
        session.add(user)
        await session.flush()
        slug = f"p-{uuid.uuid4().hex[:8]}"
        project = Project(
            id=uuid.uuid4(),
            name=slug,
            slug=slug,
            status="active",
            owner_user_id=user.id,
            next_card_seq=1,
        )
        session.add(project)
        await session.flush()
        sealed = secret_envelope.seal("ghp_token_value_for_the_test")
        secret = ProjectSecret(
            id=uuid.uuid4(),
            project_id=project.id,
            name="PROVIDER_TOKEN",
            kind="provider_token",
            value_encrypted=sealed.value_encrypted,
            value_nonce=sealed.value_nonce,
            dek_wrapped=sealed.dek_wrapped,
            dek_nonce=sealed.dek_nonce,
            key_version=sealed.key_version,
            created_by=user.id,
        )
        session.add(secret)
        await session.flush()
        repository = ProjectRepository(
            id=uuid.uuid4(),
            project_id=project.id,
            scheme="https",
            host="github.com",
            path="/Lei-k/Traqora",
            default_branch="main",
            auth_kind="ambient",
            provider_token_secret_id=secret.id,
            created_by=user.id,
        )
        session.add(repository)
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=f"TASK-{uuid.uuid4().hex[:6]}",
            title="a card",
            stage="verify",
            risk="low",
            priority="normal",
            source="repo",
            delivery="pull_request",
            target_branch="main",
        )
        session.add(task)
        await session.flush()
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=project.id,
            repository_id=repository.id,
            seq=1,
            status="succeeded",
            result="succeeded",
            attempt=1,
            finished_at=datetime.now(UTC),
            pushed_branch=f"cliora/{task.card_ref}-1",
            delivery_state=PENDING,
            created_by=user.id,
        )
        session.add(run)
        await session.commit()
        return project.id, task.id, run.id


async def test_a_created_pull_request_is_recorded_and_audited(
    api: tuple, projects_enabled: None
) -> None:
    _client, maker = api
    _project, _task, run_id = await _fixture(maker)
    fake = FakeProvider("ok")

    async with maker() as session:
        service = DeliveryService(session)
        service._settings = Settings()  # noqa: SLF001 - the adapter is injected below
        run = await session.get(TaskRun, run_id)
        assert run is not None
        # Inject the fake at the adapter boundary rather than stubbing the service: the
        # code path under test is the one that composes the body and settles the row.
        import app.services.deliveries as deliveries

        original = deliveries.adapter_for
        deliveries.adapter_for = lambda host, settings: _adapter(fake, settings)  # type: ignore[assignment]
        try:
            outcome = await service.deliver(run)
        finally:
            deliveries.adapter_for = original
        await session.commit()

    assert outcome.state == DELIVERED
    async with maker() as session:
        run = await session.get(TaskRun, run_id)
        assert run is not None
        assert run.delivery_ref == "https://github.invalid/o/r/pull/12"
        # The run's own result is untouched: it succeeded, and delivery is a separate
        # column because "what happened" and "what came of it" are different questions.
        assert run.result == "succeeded"
        audits = (
            await session.execute(
                sa.text(
                    "SELECT metadata FROM audit_logs "
                    "WHERE action = 'pr.create' AND metadata->>'run_id' = :run_id"
                ),
                {"run_id": str(run_id)},
            )
        ).fetchall()
        assert len(audits) == 1
        recorded = audits[0][0]
        assert recorded["number"] == 12
        assert recorded["head"].startswith("cliora/")
        # Repo, number, head and base — and **never the token, nor its length**.
        assert "ghp_" not in str(recorded), "the audit row carried the credential"


@pytest.mark.parametrize("mode", ["forbidden", "unprocessable", "hang"])
async def test_a_refusal_is_branch_only_and_the_run_still_succeeded(
    api: tuple, projects_enabled: None, mode: str
) -> None:
    """The branch is pushed and the work exists; a person can open it by hand."""
    _client, maker = api
    _project, _task, run_id = await _fixture(maker)
    fake = FakeProvider(mode)

    async with maker() as session:
        import app.services.deliveries as deliveries

        run = await session.get(TaskRun, run_id)
        assert run is not None
        original = deliveries.adapter_for
        deliveries.adapter_for = lambda host, settings: _adapter(fake, settings)  # type: ignore[assignment]
        try:
            outcome = await DeliveryService(session).deliver(run)
        finally:
            deliveries.adapter_for = original
        await session.commit()

    assert outcome.state == BRANCH_ONLY
    assert outcome.reason
    async with maker() as session:
        run = await session.get(TaskRun, run_id)
        assert run is not None
        assert run.result == "delivered_branch_only"
        # **Still succeeded.** A failed delivery is not a failed run.
        assert run.status == "succeeded"


async def test_an_existing_pull_request_counts_as_delivered(
    api: tuple, projects_enabled: None
) -> None:
    """One pull request per branch is the provider's rule, not our failure."""
    _client, maker = api
    _project, _task, run_id = await _fixture(maker)
    fake = FakeProvider("existing")

    async with maker() as session:
        import app.services.deliveries as deliveries

        run = await session.get(TaskRun, run_id)
        assert run is not None
        original = deliveries.adapter_for
        deliveries.adapter_for = lambda host, settings: _adapter(fake, settings)  # type: ignore[assignment]
        try:
            outcome = await DeliveryService(session).deliver(run)
        finally:
            deliveries.adapter_for = original
        await session.commit()

    assert outcome.state == DELIVERED
    assert outcome.ref == "https://x.invalid/pr/7"
    # And nothing was created.
    assert [r for r in fake.requests if r[0] == "POST"] == []


def test_nothing_in_the_receive_loop_reaches_a_provider() -> None:
    """`finish()` records the intent; the worker makes the call.

    The static form of `GATE-DV-NO-HTTP-IN-LOOP`. The symptom of a violation — a
    terminal that stutters when an unrelated card finishes — has no obvious connection
    to its cause, which is why this is a test rather than a review note.
    """
    from pathlib import Path

    runs = (Path(__file__).resolve().parents[3] / "backend/app/services/runs.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("httpx", "adapter_for", "create_pull_request", ".deliver("):
        assert forbidden not in runs, (
            f"services/runs.py reached {forbidden}; that module runs on the node receive "
            "loop, which also carries interactive terminal bytes"
        )


async def test_a_run_with_no_pushed_branch_is_never_queued(
    api: tuple, projects_enabled: None
) -> None:
    """A pull request may only be opened on a branch that really exists."""
    _client, maker = api
    async with maker() as session:
        service = DeliveryService(session)
        task = Task(id=uuid.uuid4(), project_id=uuid.uuid4(), card_ref="X", title="t")
        task.delivery = "pull_request"
        assert service.wants_pull_request(task, None) is False
        assert service.wants_pull_request(task, "cliora/X-1") is True
        task.delivery = "branch"
        # `branch` says "push it and stop"; a card wanting more would have said so.
        assert service.wants_pull_request(task, "cliora/X-1") is False
