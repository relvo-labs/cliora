"""Tests for the in-image agentd packer (ADR 0020 §8).

Every assertion here is a contract with code that lives somewhere else, and each one fails
on the *node* rather than in the build if the packer drifts:

  * the filenames must pass `app.services.releases.ARTIFACT_PATTERN`, or Central holds an
    artifact it will not serve;
  * `agentd` must sit at the archive root, because `daemon/internal/update/files.go`
    extracts exactly that member and ignores anything with a directory part;
  * `checksums.txt` must be in GoReleaser's shape, because `deploy/install.sh` greps it
    and `releases.py` parses it.

A stub `go` on PATH keeps this hermetic and fast: what is being tested is the layout and
the naming, not the compiler.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "pack-agentd.sh"
_REPO_ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(_REPO_ROOT / "backend"))
from app.services.releases import ARTIFACT_PATTERN, parse_checksums  # noqa: E402

VERSION = "1.2.3"

# Stands in for the toolchain. It records nothing and compiles nothing; it only honours
# the two invocations the packer makes, and writes bytes that differ per architecture so a
# packer that built one binary and copied it twice would show up as equal digests.
_STUB_GO = """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "mod" ]; then exit 0; fi
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$out" ] || { echo "stub go: no -o" >&2; exit 1; }
mkdir -p "$(dirname "$out")"
printf 'fake agentd for %s\\n' "${GOARCH:-unset}" > "$out"
chmod +x "$out"
"""


@pytest.fixture
def packed(tmp_path: Path) -> Path:
    """Run the packer against a stub toolchain and return the destination directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "go"
    stub.write_text(_STUB_GO)
    stub.chmod(0o755)

    source = tmp_path / "src"
    (source / "cmd" / "agentd").mkdir(parents=True)
    dest = tmp_path / "artifacts"

    subprocess.run(
        [str(_SCRIPT), VERSION, str(dest)],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    return dest


def test_it_writes_both_architectures_and_a_checksums_file(packed: Path) -> None:
    assert sorted(p.name for p in packed.iterdir()) == [
        "agentd_1.2.3_linux_amd64.tar.gz",
        "agentd_1.2.3_linux_arm64.tar.gz",
        "checksums.txt",
    ]


def test_every_name_it_writes_is_accepted_by_the_server_side_allowlist(packed: Path) -> None:
    """Same pinning the baker's tests apply: a name this script can produce but
    `/api/downloads` will not serve is an artifact that exists and cannot be fetched."""
    for entry in packed.iterdir():
        assert ARTIFACT_PATTERN.match(entry.name), entry.name


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_the_binary_sits_at_the_archive_root(packed: Path, architecture: str) -> None:
    """`daemon/internal/update/files.go` takes exactly one member named `agentd` and
    ignores anything carrying a directory part, so `bin/agentd` would fail on the node
    after the download rather than in the build."""
    with tarfile.open(packed / f"agentd_{VERSION}_linux_{architecture}.tar.gz") as archive:
        assert archive.getnames() == ["agentd"]
        member = archive.getmember("agentd")
        assert member.isfile()
        assert member.mode & 0o111


def test_the_two_architectures_are_not_the_same_build(packed: Path) -> None:
    digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in packed.glob("agentd_*.tar.gz")
    }
    assert len(set(digests.values())) == 2, digests


def test_checksums_parse_and_match_what_is_on_disk(packed: Path) -> None:
    digests = parse_checksums((packed / "checksums.txt").read_text(encoding="utf-8"))
    assert set(digests) == {
        f"agentd_{VERSION}_linux_amd64.tar.gz",
        f"agentd_{VERSION}_linux_arm64.tar.gz",
    }
    for name, digest in digests.items():
        assert hashlib.sha256((packed / name).read_bytes()).hexdigest() == digest


def test_the_archives_are_reproducible(tmp_path: Path, packed: Path) -> None:
    """Two builds of one commit must produce identical bytes (ADR 0017). tar embeds mtimes
    and ownership by default, which would break that before the compiler ever got a say."""
    first = (packed / f"agentd_{VERSION}_linux_amd64.tar.gz").read_bytes()
    second_dest = packed.parent / "artifacts-again"
    subprocess.run(
        [str(_SCRIPT), VERSION, str(second_dest)],
        cwd=packed.parent / "src",
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": f"{packed.parent / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert (second_dest / f"agentd_{VERSION}_linux_amd64.tar.gz").read_bytes() == first


@pytest.mark.parametrize("version", ["../../etc", "1.2.3 rm -rf", "a/b"])
def test_a_version_that_cannot_appear_in_an_artifact_name_is_refused(
    tmp_path: Path, version: str
) -> None:
    result = subprocess.run(
        [str(_SCRIPT), version, str(tmp_path / "artifacts")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "refusing" in result.stderr


def test_missing_arguments_are_refused(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(_SCRIPT), VERSION], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 2
