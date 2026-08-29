"""What provider data may and may not claim, and what the reader may and may not do.

`HD-02`/`HD-14`, ADR 0043. Four groups, and each one guards a rule whose breach is quiet:

* provider content **cannot reach above `reviewed`** — the ceiling is a value domain, so
  the negative tests are the ones that matter;
* the reader issues **GET and nothing else**, asserted against the source text rather than
  by mocking, because a mock proves what the test author expected;
* a token never reaches an error string;
* the two new source types are declared everywhere the eight existing ones are — four
  places, and the fourth fails silently.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from app.services import provider_reads
from app.services.knowledge import provider_sources
from app.services.knowledge.provider_sources import (
    PROVIDER_AUTHORITIES,
    published_version_source,
    pull_request_source,
)
from app.settings import Settings

pytestmark = pytest.mark.asyncio


class _Repo:
    """Just the id: these two functions read one field and constructing a real row would
    make the test about `ProjectRepository`'s required columns instead."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


# --- the ceiling ------------------------------------------------------------ #


async def test_an_unmerged_pull_request_is_only_discussion() -> None:
    source = pull_request_source(
        repository=_Repo(),
        number=12,
        title="加一個 provider reader",
        body="草案",
        merged=False,
        merged_at=None,
        head_ref="cliora/HD-01",
        base_ref="main",
        url="https://github.com/x/y/pull/12",
        updated_at=NOW,
    )
    assert source.authority == "discussion"


async def test_a_merged_pull_request_reaches_reviewed_and_stops_there() -> None:
    """`reviewed`'s first writer since `alpha.3` gave it a weight and no source."""
    source = pull_request_source(
        repository=_Repo(),
        number=12,
        title="加一個 provider reader",
        body="已合併",
        merged=True,
        merged_at=NOW,
        head_ref="cliora/HD-01",
        base_ref="main",
        url="https://github.com/x/y/pull/12",
        updated_at=NOW,
    )
    assert source.authority == "reviewed"
    assert source.occurred_at == NOW


async def test_a_published_version_is_reviewed() -> None:
    source = published_version_source(
        repository=_Repo(),
        tag="v2.0.0-beta.2",
        name="Ecosystem and Hardening",
        body="說明",
        published_at=NOW,
        prerelease=True,
        url="https://github.com/x/y/rel/1",
    )
    assert source.authority == "reviewed"
    assert "預發行" in source.text


@pytest.mark.parametrize("forbidden", ["accepted", "authoritative", "canonical", "verified"])
async def test_provider_data_cannot_claim_a_level_above_reviewed(forbidden: str) -> None:
    """The four levels ADR 0043 §4 puts out of reach, one test each.

    `verified` is the least obvious and the most important: in this system it means
    *Cliora's* verification ran and passed (`sources.py` reads
    `report.source == "machine_verified"`). A provider's green CI is somebody else's
    verification, and a ladder whose levels each mean one thing is the entire value of
    having ten of them.
    """
    assert forbidden not in PROVIDER_AUTHORITIES
    with pytest.raises(ValueError, match="ADR 0043"):
        provider_sources._assert_ceiling(forbidden)


async def test_the_ceiling_is_enforced_by_value_as_well_as_by_grep() -> None:
    """`GATE-HD-PROVIDER-AUTHORITY-CEILING` reads the file's text; this reads the value.

    The two fail on different mistakes. A gate catches somebody *typing* `"accepted"`; it
    cannot catch a value assembled from a variable, and this can. Either alone leaves a
    way through.
    """
    source = inspect.getsource(provider_sources)
    for forbidden in ("accepted", "authoritative", "canonical", "verified"):
        # **The whole file, prose included** — the same text the gate reads. Exempting
        # comments would make the rule unenforceable exactly where somebody explains why
        # they are about to break it.
        assert f'"{forbidden}"' not in source, (
            f"{forbidden} appears as a quoted string in provider_sources.py; "
            "the gate reads this file's text and so does this test"
        )


# --- the reader is a reader ------------------------------------------------- #


async def test_the_provider_reader_contains_no_method_other_than_get() -> None:
    """Asserted against the module's own source, not against a mocked client.

    A mock proves the call the test author wrote; the source proves there is no other one.
    `GATE-HD-READS-ARE-GETS` says the same thing in the gate suite — this is here so it
    also fails in a plain `pytest` run, because a gate that only CI runs is a gate a
    contributor discovers late.
    """
    from app.services import provider_reads

    source = inspect.getsource(provider_reads)
    for method in ('"POST"', '"PUT"', '"PATCH"', '"DELETE"'):
        assert method not in source, f"{method} appears in the read-only provider module"
    assert '"GET"' in source


async def test_the_reader_cannot_reach_a_write_verb() -> None:
    from app.services import provider_reads

    source = inspect.getsource(provider_reads)
    for verb in ("create_pull_request", "comment_on_pull_request", "adapter_for"):
        assert verb not in source


async def test_a_token_never_reaches_an_error_string() -> None:
    """The provider's error body is what a person pastes into a ticket.

    Higher risk than a log line, and for a reason worth stating: a log is collected by
    accident, a quoted error is republished on purpose.
    """
    import httpx

    from app.services.provider_reads import _safe_detail

    token = "ghp_thisisasecrettokenvalue"
    response = httpx.Response(
        403,
        text=f'{{"message":"Bad credentials for {token}"}}',
        request=httpx.Request("GET", "https://x"),
    )
    detail = _safe_detail(response, token)
    assert token not in detail
    assert "***" in detail


# --- the two new types are declared in all four places ---------------------- #


async def test_the_two_provider_types_are_declared_everywhere() -> None:
    """Four places, and the fourth is the one that fails silently.

    `plan/27/02` §4 named them before any of this was written: the two CHECK constraints
    (which raise), `store.SOURCE_TYPES` (which raises through an assert in `upsert`), and
    `search._HALF_LIFE_DAYS` — which does **not** raise, because it is read with a
    default. A `release` missing from it decays at 90 days instead of 365 and nothing
    anywhere says so.
    """
    from app.services.knowledge.search import _HALF_LIFE_DAYS
    from app.services.knowledge.store import EXTERNALLY_TRIGGERED, SOURCE_TYPES

    for source_type in ("pull_request", "release"):
        assert source_type in SOURCE_TYPES
        assert source_type in EXTERNALLY_TRIGGERED
        assert source_type in _HALF_LIFE_DAYS

    assert _HALF_LIFE_DAYS["release"] == 365.0, "a version is not an artifact"
    assert _HALF_LIFE_DAYS["pull_request"] == 90.0


# --- the pass itself, end to end -------------------------------------------- #


class _FakeReader:
    """A reader with canned answers, injected in place of `GitHubReader`.

    Injected rather than intercepting httpx: the thing under test is the *pass* — which
    repositories it visits, what it writes, what it does after a failure — and a fake HTTP
    layer would add a second thing that can be wrong.
    """

    def __init__(self, pulls=(), versions=(), fail: bool = False) -> None:
        self._pulls = list(pulls)
        self._versions = list(versions)
        self._fail = fail
        self.calls = 0

    async def list_pull_requests(self, *, repo_path, token, since=None):
        self.calls += 1
        if self._fail:
            raise provider_reads.ProviderReadError("PROVIDER_READ_FAILED", "401: Bad credentials")
        return self._pulls

    async def list_published_versions(self, *, repo_path, token):
        self.calls += 1
        if self._fail:
            raise provider_reads.ProviderReadError("PROVIDER_READ_FAILED", "401: Bad credentials")
        return self._versions


async def _repo_project(session, *, enabled: bool = True, with_token: bool = True):
    from app.db.models import Project, ProjectRepository, ProjectSecret, Role, User
    from app.security.passwords import hash_password

    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    name = f"prov-{uuid.uuid4().hex[:8]}"
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
        provider_sync_enabled=enabled,
    )
    session.add(project)
    await session.flush()

    # A real row, because `project_repositories.provider_token_secret_id` carries a real
    # foreign key. The **ciphertext is not real** — `_token` is monkeypatched in the tests
    # that need a value, so nothing here decrypts. Building a genuinely encrypted secret
    # would make these tests depend on the envelope scheme, which `test_secrets.py` covers
    # and which is not what a sync pass is about.
    secret_id = None
    if with_token:
        secret = ProjectSecret(
            id=uuid.uuid4(),
            project_id=project.id,
            name="GITHUB_TOKEN",
            kind="provider_token",
            value_encrypted=b"x",
            value_nonce=b"y",
            dek_wrapped=b"z",
            dek_nonce=b"w",
            key_version=1,
            created_by=user.id,
        )
        session.add(secret)
        await session.flush()
        secret_id = secret.id

    repository = ProjectRepository(
        id=uuid.uuid4(),
        project_id=project.id,
        scheme="https",
        host="github.com",
        path="cliora/demo",
        default_branch="main",
        auth_kind="ambient",
        provider_token_secret_id=secret_id,
        created_by=user.id,
    )
    session.add(repository)
    await session.flush()
    return project, repository


async def test_a_disabled_project_makes_no_call_at_all(session, monkeypatch) -> None:
    """The flag is checked **before** anything reaches the network.

    `FR-PROV-001.AC-03`, and it is the assertion J16 extends: a deployment that has not
    asked for provider sync must not be visible in anybody's API logs.
    """
    from app.services.knowledge import provider_sync

    project, _repository = await _repo_project(session, enabled=False)
    reader = _FakeReader()
    monkeypatch.setattr(provider_reads, "reader_for", lambda host, settings: reader)

    outcome = await provider_sync.sync_project(session, project_id=project.id, settings=Settings())
    assert outcome == provider_sync.SyncOutcome()
    assert reader.calls == 0


async def test_a_repository_with_no_token_is_skipped_and_says_so(session, monkeypatch) -> None:
    """Skipped, not failed — and the difference is the stored reason.

    A missing token will still be missing next round, so counting it as a failure would
    eventually "stop" a repository that never started. But silence here is the exact
    failure `provider_sync_error` exists to prevent: on screen, a repository that cannot
    be read looks like one where nothing has been merged.
    """
    from app.services.knowledge import provider_sync

    project, repository = await _repo_project(session, with_token=False)
    reader = _FakeReader()
    monkeypatch.setattr(provider_reads, "reader_for", lambda host, settings: reader)

    outcome = await provider_sync.sync_project(session, project_id=project.id, settings=Settings())
    assert outcome.skipped == 1
    assert reader.calls == 0
    assert repository.provider_sync_error is not None
    assert "token" in repository.provider_sync_error


async def test_three_consecutive_failures_stop_the_repository(session, monkeypatch) -> None:
    """`FR-PROV-003.AC-02`, and J18's assertion.

    An un-revoked token would otherwise burn quota every five minutes for ever. The count
    resets on success, so a transient outage does not accumulate towards a stop.
    """
    from app.services.knowledge import provider_sync

    project, repository = await _repo_project(session)
    failing = _FakeReader(fail=True)
    monkeypatch.setattr(provider_reads, "reader_for", lambda host, settings: failing)
    monkeypatch.setattr(
        provider_sync, "_token", lambda secrets, project, repository: _resolved("t")
    )

    for expected in (1, 2, 3):
        outcome = await provider_sync.sync_project(
            session, project_id=project.id, settings=Settings()
        )
        assert outcome.failures == 1
        assert repository.provider_sync_failures == expected

    calls_before = failing.calls
    outcome = await provider_sync.sync_project(session, project_id=project.id, settings=Settings())
    assert outcome.skipped == 1
    assert failing.calls == calls_before, "a stopped repository was read again"
    assert "Bad credentials" in (repository.provider_sync_error or "")


def _resolved(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner()
