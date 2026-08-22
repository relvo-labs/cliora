"""Repository content, pushed from inside a run (`KN-06`, `FR-KNOW-011`, ADR 0038 §3.4).

The design under test is an inversion: **Central never fetches a repository.** So these
assertions are about the two properties that inversion has to buy back — that an
unchanged repository costs nothing, and that a deleted file actually disappears — plus
the four bounds that stop one agent's checkout from becoming everyone's problem.

The deletion test is the one that matters most. It is half of journey J12, and it asserts
that the tombstone happens at **manifest** time: the content call may be cut short by a
byte ceiling, and a repository whose deletions only land when the upload happens to fit
is one where "I deleted that document" is sometimes true.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
import sqlalchemy as sa

from app.api.errors import ApiError
from app.db.models import KnowledgeChunk, KnowledgeSource, Project, ProjectRepository, Role, User
from app.security.passwords import hash_password
from app.services.knowledge.outbox import invalidate_enabled_cache
from app.services.knowledge.repo import (
    MAX_FILES,
    ManifestEntry,
    RepoSyncService,
    live_repo_paths,
)

pytestmark = pytest.mark.asyncio


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _entry(path: str, text: str) -> ManifestEntry:
    return ManifestEntry(path=path, sha256=_digest(text), size=len(text.encode()))


async def _seed(session, *, knowledge: bool = True):
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
        id=uuid.uuid4(), name=name, slug=name, owner_user_id=user.id, knowledge_enabled=knowledge
    )
    session.add(project)
    await session.flush()
    repository = ProjectRepository(
        id=uuid.uuid4(),
        project_id=project.id,
        scheme="https",
        host="github.com",
        path=f"acme/{name}",
        default_branch="main",
        created_by=user.id,
    )
    session.add(repository)
    await session.flush()
    invalidate_enabled_cache()
    return project, repository


async def _sync(session, project, repository, commit: str, files: dict[str, str]):
    service = RepoSyncService(session)
    manifest = await service.manifest(
        project_id=project.id,
        repository_id=repository.id,
        commit=commit,
        entries=[_entry(path, text) for path, text in files.items()],
    )
    if manifest.want:
        await service.content(
            project_id=project.id,
            repository_id=repository.id,
            commit=commit,
            files=[(path, files[path]) for path in manifest.want],
        )
    await session.flush()
    return manifest


async def test_a_first_sync_wants_everything_and_indexes_it(session):
    project, repository = await _seed(session)
    manifest = await _sync(
        session, project, repository, "aaa111", {"README.md": "# 專案", "docs/x.md": "決策"}
    )
    assert manifest.want == ["README.md", "docs/x.md"]
    assert await live_repo_paths(session, project.id, repository.id) == [
        "README.md",
        "docs/x.md",
    ]
    authorities = {
        row.authority
        for row in (
            await session.execute(
                sa.select(KnowledgeSource).where(
                    KnowledgeSource.project_id == project.id,
                    KnowledgeSource.source_type == "repo_doc",
                )
            )
        )
        .scalars()
        .all()
    }
    assert authorities == {"canonical"}


async def test_an_unchanged_repository_costs_nothing(session):
    """The economy the whole protocol rests on: same bytes, no upload."""
    project, repository = await _seed(session)
    files = {"README.md": "# 專案", "docs/x.md": "決策"}
    await _sync(session, project, repository, "aaa111", files)
    second = await _sync(session, project, repository, "bbb222", files)
    assert second.want == []
    assert second.unchanged == 2
    assert second.removed == 0


async def test_a_removed_path_is_tombstoned_at_manifest_time(session):
    """J12's first half. Deletion must not wait for the content call, which may be cut
    short by a byte ceiling."""
    project, repository = await _seed(session)
    await _sync(session, project, repository, "aaa111", {"a.md": "keep", "docs/b.md": "drop"})
    assert len(await live_repo_paths(session, project.id, repository.id)) == 2

    manifest = await RepoSyncService(session).manifest(
        project_id=project.id,
        repository_id=repository.id,
        commit="bbb222",
        entries=[_entry("a.md", "keep")],
    )
    await session.flush()
    assert manifest.removed == 1
    assert await live_repo_paths(session, project.id, repository.id) == ["a.md"]

    gone = (
        await session.execute(
            sa.select(KnowledgeSource).where(
                KnowledgeSource.project_id == project.id,
                KnowledgeSource.source_external_id == f"{repository.id}:docs/b.md",
            )
        )
    ).scalar_one()
    assert gone.active is False
    assert gone.deleted_at is not None
    # The row survives so a manifest citing it can still say what happened to it.
    closed = (
        await session.execute(
            sa.select(KnowledgeChunk.valid_to).where(KnowledgeChunk.source_id == gone.id)
        )
    ).scalar_one()
    assert closed is not None


async def test_changed_content_at_a_new_commit_is_re_uploaded(session):
    project, repository = await _seed(session)
    await _sync(session, project, repository, "aaa111", {"a.md": "版本一"})
    manifest = await _sync(session, project, repository, "bbb222", {"a.md": "版本二"})
    assert manifest.want == ["a.md"]
    # Scoped to the *active* source: the superseded version's chunk is still open,
    # because it remains an accurate record of what that version said (see
    # `KnowledgeStore._supersede_older`).
    content = (
        await session.execute(
            sa.select(KnowledgeChunk.content)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeChunk.source_id)
            .where(
                KnowledgeChunk.project_id == project.id,
                KnowledgeChunk.valid_to.is_(None),
                KnowledgeSource.active.is_(True),
            )
        )
    ).scalar_one()
    assert content == "版本二"


async def test_a_sensitive_filename_is_refused_before_collection(session):
    """Refused rather than redacted: a file never read cannot be partly leaked by a
    pattern that did not quite match."""
    project, repository = await _seed(session)
    manifest = await RepoSyncService(session).manifest(
        project_id=project.id,
        repository_id=repository.id,
        commit="aaa111",
        entries=[_entry(".env.production", "TOKEN=abc"), _entry("a.md", "fine")],
    )
    assert manifest.want == ["a.md"]
    assert manifest.skipped == [{"path": ".env.production", "reason": "sensitive"}]


async def test_a_sensitive_path_uploaded_anyway_is_still_not_stored(session):
    """The content call re-checks. A client that ignores the manifest's answer must not
    be able to put a credential in the index by asking twice."""
    project, repository = await _seed(session)
    ingested, _bytes = await RepoSyncService(session).content(
        project_id=project.id,
        repository_id=repository.id,
        commit="aaa111",
        files=[(".env", "TOKEN=abc")],
    )
    await session.flush()
    assert ingested == 0
    assert await live_repo_paths(session, project.id, repository.id) == []


async def test_an_oversized_file_is_skipped_rather_than_fatal(session):
    """D88's asymmetry: one 5 MB CHANGELOG must not cost a project its whole memory."""
    project, repository = await _seed(session)
    big = ManifestEntry(path="huge.md", sha256=_digest("x"), size=999_999)
    manifest = await RepoSyncService(session).manifest(
        project_id=project.id,
        repository_id=repository.id,
        commit="aaa111",
        entries=[big, _entry("a.md", "fine")],
    )
    assert manifest.want == ["a.md"]
    assert manifest.skipped == [{"path": "huge.md", "reason": "too_large"}]


async def test_too_many_files_refuses_and_names_the_limit(session):
    project, repository = await _seed(session)
    entries = [_entry(f"docs/{index}.md", "x") for index in range(MAX_FILES + 1)]
    with pytest.raises(ApiError) as raised:
        await RepoSyncService(session).manifest(
            project_id=project.id,
            repository_id=repository.id,
            commit="aaa111",
            entries=entries,
        )
    assert raised.value.code == "KNOWLEDGE_SYNC_TOO_LARGE"
    assert raised.value.details == {
        "limit": "files",
        "count": MAX_FILES + 1,
        "ceiling": MAX_FILES,
    }


async def test_an_oversized_upload_refuses_and_names_bytes(session):
    project, repository = await _seed(session)
    big = "x" * (9 * 1024 * 1024)
    with pytest.raises(ApiError) as raised:
        await RepoSyncService(session).content(
            project_id=project.id,
            repository_id=repository.id,
            commit="aaa111",
            files=[("a.md", big)],
        )
    assert raised.value.code == "KNOWLEDGE_SYNC_TOO_LARGE"
    assert raised.value.details["limit"] == "bytes"


async def test_another_projects_repository_is_a_404_not_a_403(session):
    """A 403 would confirm the repository exists. Isolation is answered by absence."""
    project_a, _repository_a = await _seed(session)
    _project_b, repository_b = await _seed(session)
    with pytest.raises(ApiError) as raised:
        await RepoSyncService(session).manifest(
            project_id=project_a.id,
            repository_id=repository_b.id,
            commit="aaa111",
            entries=[_entry("a.md", "x")],
        )
    assert raised.value.code == "SOURCE_NOT_FOUND"
    assert raised.value.status_code == 404


async def test_a_sole_repository_is_resolved_without_naming_it(session):
    """An agent should not have to know a platform uuid to describe the directory it is
    standing in. One registered repository is unambiguous, so Central resolves it."""
    project, repository = await _seed(session)
    manifest = await RepoSyncService(session).manifest(
        project_id=project.id, repository_id=None, commit="aaa111", entries=[_entry("a.md", "x")]
    )
    assert manifest.want == ["a.md"]
    await RepoSyncService(session).content(
        project_id=project.id, repository_id=None, commit="aaa111", files=[("a.md", "x")]
    )
    await session.flush()
    assert await live_repo_paths(session, project.id, repository.id) == ["a.md"]


async def test_an_ambiguous_repository_refuses_rather_than_guessing(session):
    """Two registered repositories and a card that names neither.

    Guessing which one a checkout is would attribute documents to the wrong repository
    **silently**, and a wrong attribution is worse than a refusal a person can read.
    """
    project, _repository = await _seed(session)
    role_free_second = ProjectRepository(
        id=uuid.uuid4(),
        project_id=project.id,
        scheme="https",
        host="github.com",
        path=f"acme/{uuid.uuid4().hex[:8]}",
        default_branch="main",
        created_by=project.owner_user_id,
    )
    session.add(role_free_second)
    await session.flush()
    with pytest.raises(ApiError) as raised:
        await RepoSyncService(session).manifest(
            project_id=project.id, repository_id=None, commit="aaa111", entries=[]
        )
    assert raised.value.code == "SOURCE_NOT_FOUND"
    assert "2" in raised.value.message


async def test_a_project_with_no_repository_at_all_says_so(session):
    project, repository = await _seed(session)
    await session.delete(repository)
    await session.flush()
    with pytest.raises(ApiError) as raised:
        await RepoSyncService(session).manifest(
            project_id=project.id, repository_id=None, commit="aaa111", entries=[]
        )
    assert raised.value.code == "SOURCE_NOT_FOUND"


async def test_a_disabled_project_refuses_with_404(session):
    project, repository = await _seed(session, knowledge=False)
    with pytest.raises(ApiError) as raised:
        await RepoSyncService(session).manifest(
            project_id=project.id,
            repository_id=repository.id,
            commit="aaa111",
            entries=[_entry("a.md", "x")],
        )
    assert raised.value.code == "KNOWLEDGE_DISABLED"
    assert raised.value.status_code == 404


async def test_the_citation_uri_is_a_repo_scheme_not_a_link(session):
    """Cliora has no repository browser. A link that pretends to work is worse than
    text, so the URI is a scheme the frontend renders as a copyable string."""
    project, repository = await _seed(session)
    await _sync(session, project, repository, "139f143", {"docs/x.md": "決策"})
    uri = (
        await session.execute(
            sa.select(KnowledgeSource.source_uri).where(
                KnowledgeSource.project_id == project.id,
                KnowledgeSource.source_type == "repo_doc",
            )
        )
    ).scalar_one()
    assert uri == "repo://github.com/acme/" + repository.path.split("/")[-1] + "/docs/x.md@139f143"
