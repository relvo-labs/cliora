"""Bake one verified agentd release into a Central image (RW-08, ADR 0020).

Why this exists at all: `/api/downloads` and the release manifest read the **local
filesystem** named by `CLIORA_ARTIFACTS_DIR`, and a managed platform's container
filesystem is ephemeral. So on Railway the artifacts have to arrive at build time, and
they have to arrive verified — an unverified artifact in the directory Central publishes
from would defeat the checksum chain the daemon relies on (ADR 0011, SEC-002,
tech §23 #12).

What the digest check does and does not prove. It proves the bytes in the image are the
bytes `checksums.txt` names: a truncated download, a proxy that mangled the stream, or a
version/arch mismatch all fail the build instead of failing on a node mid-update. It does
**not** authenticate the release host; that is the same trust model as `deploy/install.sh`,
which verifies against a `checksums.txt` fetched from the same origin as the tarball.
Signing the release is a separate decision (ADR 0017) and this script deliberately does
not pretend to make it.

Doing nothing is a valid outcome. With no `--version`, the script exits 0 without writing
anything, which is what makes it safe to keep in the shared Dockerfile: the compose
deployment mounts a host directory instead and must not acquire a network dependency at
build time.

    python scripts/railway/bake_artifacts.py \
        --version 1.2.3 \
        --base-url https://github.com/<owner>/<repo>/releases/download/v1.2.3 \
        --dest /srv/artifacts \
        --install-script deploy/install.sh
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import urllib.request
from pathlib import Path

# Kept in step with `ARTIFACT_PATTERN` in `backend/app/services/releases.py`. Two copies
# of an allowlist eventually disagree, and the direction of that disagreement decides
# whether a node can be updated at all — so this one is deliberately narrower (it only
# ever *constructs* names) and the test suite asserts every name it constructs is
# accepted by the server-side pattern.
_ARCHITECTURES = ("amd64", "arm64")
_CHECKSUMS = "checksums.txt"
_VERSION = re.compile(r"^[0-9A-Za-z.+_-]+$")
# GoReleaser's format: sha256 hex, two spaces, filename (optionally `*`-prefixed).
_CHECKSUM_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})\s+\*?(?P<name>\S+)$")


class BakeError(RuntimeError):
    """A failure that must stop the image build rather than ship a partial directory."""


def tarball_name(version: str, architecture: str) -> str:
    return f"agentd_{version}_linux_{architecture}.tar.gz"


def parse_checksums(text: str) -> dict[str, str]:
    digests: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _CHECKSUM_LINE.match(line.strip())
        if match is None:
            raise BakeError(f"unparseable checksums.txt line: {line!r}")
        digests[match["name"]] = match["digest"]
    if not digests:
        raise BakeError("checksums.txt named no artifact")
    return digests


def _fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url) as response:  # noqa: S310 - explicit base URL
            return bytes(response.read())
    except Exception as exc:  # pragma: no cover - network shapes vary
        raise BakeError(f"cannot fetch {url}: {exc}") from exc


def bake(
    *,
    version: str,
    base_url: str,
    dest: Path,
    install_script: Path | None = None,
) -> list[str]:
    """Download, verify and place one release. Returns the filenames written.

    Nothing is written until every digest matches. A directory holding one good tarball
    and one corrupt one is worse than an empty directory: the manifest would publish the
    good entry and a node asking for the other architecture would fail after downloading.
    """
    if not _VERSION.match(version):
        raise BakeError(f"refusing to build an artifact name from version {version!r}")
    if not base_url.startswith("https://") and not base_url.startswith("file://"):
        # file:// is for the test suite; anything else would be an unencrypted fetch of
        # the thing whose whole job is to be verifiable.
        raise BakeError(f"base URL must be https:// (got {base_url!r})")

    base = base_url.rstrip("/")
    expected = parse_checksums(_fetch(f"{base}/{_CHECKSUMS}").decode("utf-8"))

    staged: dict[str, bytes] = {}
    for architecture in _ARCHITECTURES:
        name = tarball_name(version, architecture)
        if name not in expected:
            raise BakeError(f"{_CHECKSUMS} has no digest for {name}")
        payload = _fetch(f"{base}/{name}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != expected[name]:
            raise BakeError(f"checksum mismatch for {name}: {digest} != {expected[name]}")
        staged[name] = payload

    dest.mkdir(parents=True, exist_ok=True)
    for name, payload in staged.items():
        (dest / name).write_bytes(payload)
    # Written verbatim, not regenerated: the daemon and `install.sh` verify against this
    # exact file, so re-emitting a "cleaned up" version would mean Central publishes a
    # digest list nobody upstream ever signed off on.
    (dest / _CHECKSUMS).write_bytes(_fetch(f"{base}/{_CHECKSUMS}"))
    written = sorted([*staged, _CHECKSUMS])

    if install_script is not None:
        if not install_script.is_file():
            raise BakeError(f"install script not found: {install_script}")
        shutil.copyfile(install_script, dest / "install.sh")
        written.append("install.sh")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bake_artifacts")
    parser.add_argument("--version", default="", help="release version; empty = do nothing")
    parser.add_argument("--base-url", default="", help="directory URL holding the release")
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--install-script", default=None, type=Path)
    args = parser.parse_args(argv)

    if not args.version:
        print("no --version given; not baking any artifact (downloads stay disabled)")
        return 0
    if not args.base_url:
        raise SystemExit("--base-url is required when --version is given")

    try:
        written = bake(
            version=args.version,
            base_url=args.base_url,
            dest=args.dest,
            install_script=args.install_script,
        )
    except BakeError as exc:
        print(f"artifact bake failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified and wrote: {' '.join(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
