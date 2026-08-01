"""The release manifest: what counts as an installable release (P4-10, ADR 0017).

The manifest is the *only* definition of an allowlisted release — the update
protocol carries a version and nothing else, so an entry published here is an entry
a daemon will install. Everything below is therefore about the fail-closed rule:
an entry appears only when the filename, the file, the digest and the size all line
up, and a partial match is omitted rather than advertised.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import releases
from app.services.releases import (
    ARTIFACT_PATTERN,
    ReleaseService,
    parse_checksums,
    version_key,
)
from app.settings import Settings


@pytest.fixture(autouse=True)
def _fresh_cache():
    releases.reset_cache()
    yield
    releases.reset_cache()


def publish(
    root: Path,
    version: str,
    *,
    architectures: tuple[str, ...] = ("amd64", "arm64"),
    content: bytes = b"tarball",
    with_checksums: bool = True,
    digest_override: str | None = None,
) -> list[str]:
    """Write artifacts and (optionally) their checksums, the way a release does."""
    names: list[str] = []
    lines: list[str] = []
    existing = root / "checksums.txt"
    if existing.is_file():
        lines = existing.read_text(encoding="utf-8").splitlines()
    for architecture in architectures:
        name = f"agentd_{version}_linux_{architecture}.tar.gz"
        (root / name).write_bytes(content)
        names.append(name)
        digest = digest_override or hashlib.sha256(content).hexdigest()
        lines.append(f"{digest}  {name}")
    if with_checksums:
        (root / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return names


def service(root: Path | None) -> ReleaseService:
    return ReleaseService(settings=Settings(artifacts_dir=str(root) if root else ""))


# --------------------------------------------------------------------------- #
# The empty cases
# --------------------------------------------------------------------------- #


def test_no_artifacts_dir_is_an_empty_manifest_not_an_error() -> None:
    """The daemon must be able to tell "nothing published" from "no such endpoint",
    so this is an empty manifest rather than a 404 or an exception."""
    manifest = service(None).manifest()
    assert manifest.latest is None
    assert manifest.artifacts == ()


def test_a_missing_directory_is_an_empty_manifest(tmp_path: Path) -> None:
    manifest = service(tmp_path / "nope").manifest()
    assert manifest.latest is None


def test_an_empty_directory_is_an_empty_manifest(tmp_path: Path) -> None:
    assert service(tmp_path).manifest().artifacts == ()


# --------------------------------------------------------------------------- #
# Fail closed
# --------------------------------------------------------------------------- #


def test_an_artifact_without_a_recorded_digest_is_not_published(tmp_path: Path) -> None:
    """Publishing it would move the failure from "not offered" to "fails after the
    download" — on the node, mid-update, instead of here."""
    publish(tmp_path, "1.0.0", with_checksums=False)
    assert service(tmp_path).manifest().artifacts == ()


def test_a_digest_without_its_artifact_is_not_published(tmp_path: Path) -> None:
    (tmp_path / "checksums.txt").write_text(
        f"{'a' * 64}  agentd_9.9.9_linux_amd64.tar.gz\n", encoding="utf-8"
    )
    assert service(tmp_path).manifest().artifacts == ()


def test_a_file_that_is_not_an_allowlisted_name_is_ignored(tmp_path: Path) -> None:
    for name in ("evil.sh", "agentd_1.0.0_windows_amd64.tar.gz", "agentd.tar.gz", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "checksums.txt").write_text(
        "\n".join(f"{'a' * 64}  {name}" for name in ("evil.sh", "notes.txt")) + "\n",
        encoding="utf-8",
    )
    assert service(tmp_path).manifest().artifacts == ()


def test_a_directory_named_like_an_artifact_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "agentd_1.0.0_linux_amd64.tar.gz").mkdir()
    (tmp_path / "checksums.txt").write_text(
        f"{'a' * 64}  agentd_1.0.0_linux_amd64.tar.gz\n", encoding="utf-8"
    )
    assert service(tmp_path).manifest().artifacts == ()


def test_a_checksums_line_for_a_disallowed_name_is_dropped(tmp_path: Path) -> None:
    """So a digest for something the download endpoint would refuse cannot reach the
    manifest by way of the checksums file."""
    digests = parse_checksums(
        f"{'a' * 64}  ../../etc/passwd\n"
        f"{'b' * 64}  agentd_1.0.0_linux_amd64.tar.gz\n"
        f"{'c' * 64}  /etc/shadow\n"
    )
    assert set(digests) == {"agentd_1.0.0_linux_amd64.tar.gz"}


def test_malformed_checksum_lines_do_not_break_the_file(tmp_path: Path) -> None:
    """The file is generated, but a blank line or a future header must not take the
    whole manifest down with it."""
    content = b"tarball"
    name = "agentd_1.0.0_linux_amd64.tar.gz"
    (tmp_path / name).write_bytes(content)
    (tmp_path / "checksums.txt").write_text(
        "# generated by goreleaser\n"
        "\n"
        "not a checksum line at all\n"
        f"{hashlib.sha256(content).hexdigest()}  {name}\n",
        encoding="utf-8",
    )
    assert [a.filename for a in service(tmp_path).manifest().artifacts] == [name]


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #


def test_a_published_release_lists_every_architecture_with_its_digest(tmp_path: Path) -> None:
    content = b"the-tarball"
    publish(tmp_path, "1.2.3", content=content)
    manifest = service(tmp_path).manifest()

    assert manifest.latest == "1.2.3"
    assert {a.architecture for a in manifest.artifacts} == {"amd64", "arm64"}
    for artifact in manifest.artifacts:
        assert artifact.sha256 == hashlib.sha256(content).hexdigest()
        assert artifact.size == len(content)
        assert ARTIFACT_PATTERN.match(artifact.filename)


def test_latest_is_the_highest_version_not_the_newest_file(tmp_path: Path) -> None:
    """mtime order is an accident of how the directory was populated; the version is
    the fact."""
    publish(tmp_path, "1.10.0")
    publish(tmp_path, "1.9.0")
    assert service(tmp_path).manifest().latest == "1.10.0"


def test_a_pre_release_is_not_offered_as_latest(tmp_path: Path) -> None:
    """`latest` is what a fleet upgrade defaults to. Ordering a release candidate
    above its final release would push every node onto it."""
    publish(tmp_path, "2.0.0")
    publish(tmp_path, "2.0.0-rc1")
    assert service(tmp_path).manifest().latest == "2.0.0"


def test_a_pre_release_alone_is_still_available(tmp_path: Path) -> None:
    publish(tmp_path, "2.0.0-rc1")
    manifest = service(tmp_path).manifest()
    assert manifest.latest == "2.0.0-rc1"


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.0.0", "1.0.1"),
        ("1.0.9", "1.1.0"),
        ("1.9.0", "1.10.0"),
        ("1.0.0-rc1", "1.0.0"),
        ("1.0.0-rc1", "1.0.0-rc2"),
        ("0.9.0", "1.0.0"),
    ],
)
def test_version_ordering(lower: str, higher: str) -> None:
    assert version_key(lower) < version_key(higher)


def test_an_unparseable_version_does_not_break_ordering(tmp_path: Path) -> None:
    """A stray file must not be able to raise out of the manifest build."""
    publish(tmp_path, "not-a-version")
    publish(tmp_path, "1.0.0")
    assert service(tmp_path).manifest().latest == "1.0.0"


def test_find_answers_per_version_and_architecture(tmp_path: Path) -> None:
    publish(tmp_path, "1.0.0")
    releases_service = service(tmp_path)
    assert releases_service.find("1.0.0", "amd64") is not None
    assert releases_service.find("1.0.0", "riscv64") is None
    assert releases_service.find("2.0.0", "amd64") is None


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


def test_publishing_a_release_is_picked_up_without_a_restart(tmp_path: Path) -> None:
    """The cache is keyed on mtime, not on process lifetime: an operator who
    publishes a release should not have to restart Central for it to appear.

    The two publishes are separated by an explicit mtime bump because the assertion is about
    the *cache key*, not about filesystem timestamp granularity. Two writes inside one mtime
    tick produce the same key, so without this the test failed about two runs in three — a
    flake that made `make check` randomly red and hid real failures behind it.
    """
    publish(tmp_path, "1.0.0")
    releases_service = service(tmp_path)
    assert releases_service.manifest().latest == "1.0.0"

    publish(tmp_path, "1.1.0")
    _age_by_a_tick(tmp_path)
    assert releases_service.manifest().latest == "1.1.0"


def _age_by_a_tick(root: Path) -> None:
    """Move the directory and checksum mtimes a second into the future.

    Forward rather than backward: the cache key is compared for equality, so either direction
    invalidates it, and forward is what a real second publish would look like.
    """
    for path in (root, root / "checksums.txt"):
        if path.exists():
            stamp = path.stat().st_mtime + 1
            os.utime(path, (stamp, stamp))


def test_editing_checksums_in_place_invalidates_the_cache(tmp_path: Path) -> None:
    """Rewriting `checksums.txt` changes neither the directory listing nor any
    tarball, so the file's own mtime has to be part of the key."""
    content = b"tarball"
    name = "agentd_1.0.0_linux_amd64.tar.gz"
    (tmp_path / name).write_bytes(content)
    (tmp_path / "checksums.txt").write_text(f"{'0' * 64}  {name}\n", encoding="utf-8")
    releases_service = service(tmp_path)
    assert releases_service.manifest().artifacts[0].sha256 == "0" * 64

    checksums = tmp_path / "checksums.txt"
    correct = hashlib.sha256(content).hexdigest()
    checksums.write_text(f"{correct}  {name}\n", encoding="utf-8")
    # Nudged forward explicitly: a rewrite inside the same filesystem timestamp tick
    # would leave the mtime unchanged, and the test would pass for the wrong reason.
    stat = checksums.stat()
    os.utime(checksums, (stat.st_atime + 5, stat.st_mtime + 5))

    assert releases_service.manifest().artifacts[0].sha256 == correct


# --------------------------------------------------------------------------- #
# The endpoint
# --------------------------------------------------------------------------- #


def test_the_endpoint_is_public_and_answers_200_when_empty() -> None:
    """Unauthenticated for the same reason /api/downloads is: a daemon needs the
    manifest before it holds a credential. 200-with-empty rather than 404, so
    "nothing published" and "endpoint missing" stay distinguishable."""
    from app.settings import get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(artifacts_dir="")
    try:
        with TestClient(app) as client:
            response = client.get("/api/releases/manifest")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    body = response.json()
    assert body["latest"] is None
    assert body["artifacts"] == []
    assert body["generated_at"]


def test_the_endpoint_publishes_what_is_on_disk(tmp_path: Path) -> None:
    publish(tmp_path, "1.4.0")
    from app.settings import get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(artifacts_dir=str(tmp_path))
    try:
        with TestClient(app) as client:
            body = client.get("/api/releases/manifest").json()
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert body["latest"] == "1.4.0"
    assert {item["architecture"] for item in body["artifacts"]} == {"amd64", "arm64"}
    for item in body["artifacts"]:
        assert len(item["sha256"]) == 64
        assert item["size"] > 0


def test_the_download_endpoint_and_the_manifest_share_one_allowlist() -> None:
    """Two copies of the pattern would eventually disagree, and the direction of that
    disagreement decides whether a node can be updated at all — or whether something
    unserviceable gets advertised."""
    from app.api.http import downloads

    assert downloads.ARTIFACT_PATTERN is ARTIFACT_PATTERN
