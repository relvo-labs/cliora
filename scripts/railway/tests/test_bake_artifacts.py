"""Tests for the artifact baker (RW-08).

The interesting cases are all failures. A baker that writes whatever it downloaded is
indistinguishable from a working one until the day a node updates to a truncated binary,
so each negative case below is a property of the deployment rather than a unit-test
formality.

`file://` base URLs keep this hermetic: no network, no fixture server.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "bake_artifacts.py"
_spec = importlib.util.spec_from_file_location("bake_artifacts", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
bake_artifacts = importlib.util.module_from_spec(_spec)
sys.modules["bake_artifacts"] = bake_artifacts
_spec.loader.exec_module(bake_artifacts)

VERSION = "1.2.3"


def _release(tmp_path: Path, *, corrupt: str | None = None, omit: str | None = None) -> str:
    """Write a GoReleaser-shaped release directory and return its file:// URL."""
    source = tmp_path / "release"
    source.mkdir()
    lines = []
    for architecture in ("amd64", "arm64"):
        name = bake_artifacts.tarball_name(VERSION, architecture)
        payload = f"tarball for {architecture}".encode()
        digest = hashlib.sha256(payload).hexdigest()
        if corrupt == name:
            # The digest still names the honest bytes; the file on disk differs. This is
            # what a truncated or tampered download looks like.
            payload = payload + b"extra"
        if omit != name:
            (source / name).write_bytes(payload)
            lines.append(f"{digest}  {name}")
    (source / "checksums.txt").write_text("\n".join(lines) + "\n")
    return source.as_uri()


def test_a_good_release_is_written_with_its_checksums_and_install_script(tmp_path: Path) -> None:
    dest = tmp_path / "artifacts"
    script = tmp_path / "install.sh"
    script.write_text("#!/usr/bin/env bash\n")
    written = bake_artifacts.bake(
        version=VERSION,
        base_url=_release(tmp_path),
        dest=dest,
        install_script=script,
    )
    assert sorted(written) == [
        "agentd_1.2.3_linux_amd64.tar.gz",
        "agentd_1.2.3_linux_arm64.tar.gz",
        "checksums.txt",
        "install.sh",
    ]
    # checksums.txt is copied verbatim: the daemon verifies against this exact file.
    assert (dest / "checksums.txt").read_text() == (
        Path(tmp_path / "release" / "checksums.txt").read_text()
    )


def test_every_name_it_writes_is_accepted_by_the_server_side_allowlist(tmp_path: Path) -> None:
    """Two copies of an artifact allowlist eventually disagree. This pins them together:
    a name this script can produce but `/api/downloads` will not serve is an artifact
    that exists and cannot be fetched."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
    from app.services.releases import ARTIFACT_PATTERN

    written = bake_artifacts.bake(
        version=VERSION, base_url=_release(tmp_path), dest=tmp_path / "artifacts"
    )
    for name in written:
        if name == "install.sh":
            continue
        assert ARTIFACT_PATTERN.match(name), name


def test_a_checksum_mismatch_fails_and_writes_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "artifacts"
    corrupt = bake_artifacts.tarball_name(VERSION, "arm64")
    with pytest.raises(bake_artifacts.BakeError, match="checksum mismatch"):
        bake_artifacts.bake(
            version=VERSION, base_url=_release(tmp_path, corrupt=corrupt), dest=dest
        )
    # Not even the architecture that verified: a directory holding one good tarball and
    # one bad one would publish a manifest entry that fails after the download.
    assert not dest.exists() or list(dest.iterdir()) == []


def test_a_missing_digest_fails(tmp_path: Path) -> None:
    source = tmp_path / "release"
    source.mkdir()
    name = bake_artifacts.tarball_name(VERSION, "amd64")
    (source / name).write_bytes(b"payload")
    (source / "checksums.txt").write_text(f"{'0' * 64}  something-else.tar.gz\n")
    with pytest.raises(bake_artifacts.BakeError, match="no digest for"):
        bake_artifacts.bake(
            version=VERSION, base_url=source.as_uri(), dest=tmp_path / "artifacts"
        )


def test_a_missing_tarball_fails(tmp_path: Path) -> None:
    omit = bake_artifacts.tarball_name(VERSION, "arm64")
    with pytest.raises(bake_artifacts.BakeError):
        bake_artifacts.bake(
            version=VERSION,
            base_url=_release(tmp_path, omit=omit),
            dest=tmp_path / "artifacts",
        )


def test_an_unparseable_checksums_file_fails(tmp_path: Path) -> None:
    source = tmp_path / "release"
    source.mkdir()
    (source / "checksums.txt").write_text("this is not a digest line\n")
    with pytest.raises(bake_artifacts.BakeError, match="unparseable"):
        bake_artifacts.bake(
            version=VERSION, base_url=source.as_uri(), dest=tmp_path / "artifacts"
        )


@pytest.mark.parametrize("version", ["../../etc", "1.2.3 rm -rf", "a/b", ""])
def test_a_version_that_cannot_appear_in_an_artifact_name_is_refused(
    tmp_path: Path, version: str
) -> None:
    with pytest.raises(bake_artifacts.BakeError, match="refusing"):
        bake_artifacts.bake(
            version=version, base_url="https://example.com/x", dest=tmp_path / "a"
        )


def test_a_plaintext_base_url_is_refused(tmp_path: Path) -> None:
    with pytest.raises(bake_artifacts.BakeError, match="https"):
        bake_artifacts.bake(
            version=VERSION, base_url="http://example.com/x", dest=tmp_path / "a"
        )


def test_no_version_bakes_nothing_and_succeeds(tmp_path: Path) -> None:
    """The shared Dockerfile runs this unconditionally. With no version it must be a
    no-op, or the compose deployment would acquire a build-time network dependency."""
    dest = tmp_path / "artifacts"
    assert bake_artifacts.main(["--dest", str(dest)]) == 0
    assert not dest.exists()
