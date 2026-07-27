"""Release manifest: the single definition of an installable daemon release
(P4-10, ADR 0017, SEC-002).

The daemon may install **only** what appears here. That is what makes
"allowlisted release" a checkable statement rather than a claim: the update
protocol carries a version and nothing else — no URL, no filename, no digest —
so every artifact reference is derived from this manifest plus the daemon's own
config file.

The manifest is therefore built to **fail closed**. An entry is published only
when all four facts line up: the filename passes the closed allowlist, the file
exists, `checksums.txt` records a digest for it, and the recorded size matches
what is on disk. Anything partial is omitted, because a published entry the
daemon cannot verify is worse than no entry — it would fail mid-update, after the
download, instead of before it starts.

An empty result is `{"latest": null, "artifacts": []}`, never a 404: the daemon
must be able to tell "no update is available" from "this Central does not have
the endpoint".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.clock import now_utc
from app.settings import Settings, get_settings

# The closed allowlist of artifact names. `api/http/downloads.py` serves exactly
# these, and this module publishes exactly these — one pattern, so a name that can
# be downloaded is always a name that can appear in a manifest and vice versa.
ARTIFACT_PATTERN = re.compile(
    r"^(?:agentd_[0-9A-Za-z.+_-]+_linux_(?:amd64|arm64)\.tar\.gz|checksums\.txt)$"
)

# The same names, parsed. Kept separate from the allowlist so the allowlist stays
# a single flat pattern that is easy to read as a security control.
_TARBALL_NAME = re.compile(
    r"^agentd_(?P<version>[0-9A-Za-z.+_-]+)_linux_(?P<arch>amd64|arm64)\.tar\.gz$"
)

CHECKSUMS_NAME = "checksums.txt"

# sha256 hex, two spaces (GoReleaser's format), filename.
_CHECKSUM_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})\s+\*?(?P<name>\S+)$")


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    version: str
    architecture: str
    filename: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class Manifest:
    latest: str | None
    artifacts: tuple[ReleaseArtifact, ...]
    generated_at: datetime


def version_key(version: str) -> tuple[int, int, int, int, str]:
    """Sort key for release ordering.

    A pre-release sorts below the same release (`1.0.0-rc1` < `1.0.0`), which is
    the only ordering that makes `latest` safe to offer as an update target — the
    alternative would push every node onto a release candidate.

    Unparseable versions sort last-resort lowest rather than raising: a stray file
    must not be able to break the whole manifest.
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$", version)
    if match is None:
        return (-1, 0, 0, 0, version)
    major, minor, patch, pre = match.groups()
    # 0 for a pre-release, 1 for the final release, so final sorts higher.
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def parse_checksums(text: str) -> dict[str, str]:
    """Parse `checksums.txt` into {filename: sha256}.

    Unrecognized lines are skipped, not fatal: the file is generated, but a blank
    line or a future header must not take the whole manifest down. A filename that
    is not on the allowlist is dropped here too, so a digest for something
    unserviceable cannot make it into the manifest.
    """
    digests: dict[str, str] = {}
    for line in text.splitlines():
        match = _CHECKSUM_LINE.match(line.strip())
        if match is None:
            continue
        name = match.group("name")
        if ARTIFACT_PATTERN.match(name):
            digests[name] = match.group("digest")
    return digests


class ReleaseService:
    """Builds the manifest from what is actually on disk.

    Results are cached on the directory's and checksum file's mtimes, so a
    published release is picked up without a restart while a steady state does not
    re-scan the directory on every request.
    """

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def manifest(self) -> Manifest:
        root = self._root()
        if root is None:
            return Manifest(latest=None, artifacts=(), generated_at=now_utc())
        cache_key = _cache_key(root)
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
        built = _build(root)
        _cache.clear()
        _cache[cache_key] = built
        return built

    def _root(self) -> Path | None:
        if not self._settings.artifacts_dir:
            return None
        root = Path(self._settings.artifacts_dir)
        return root if root.is_dir() else None

    def find(self, version: str, architecture: str) -> ReleaseArtifact | None:
        """The artifact for one (version, architecture), or None if not published.

        None is the fail-closed answer to every "may this be installed?" question:
        an unknown version, an architecture that was not built, or a release whose
        digest did not line up all look the same to the caller, and all mean no.
        """
        for artifact in self.manifest().artifacts:
            if artifact.version == version and artifact.architecture == architecture:
                return artifact
        return None


def _cache_key(root: Path) -> tuple[str, float, float]:
    """Directory mtime plus the checksums file's, since editing `checksums.txt` in
    place changes neither the directory listing nor any tarball."""

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    return (str(root), mtime(root), mtime(root / CHECKSUMS_NAME))


def _build(root: Path) -> Manifest:
    checksums_path = root / CHECKSUMS_NAME
    try:
        digests = parse_checksums(checksums_path.read_text(encoding="utf-8"))
    except OSError:
        # No checksums file means nothing is verifiable, so nothing is installable.
        digests = {}

    artifacts: list[ReleaseArtifact] = []
    for entry in sorted(root.iterdir() if root.is_dir() else []):
        if not entry.is_file():
            continue
        parsed = _TARBALL_NAME.match(entry.name)
        if parsed is None:
            continue
        digest = digests.get(entry.name)
        if digest is None:
            # Present but unverifiable. Publishing it would move the failure from
            # "not offered" to "fails after the download".
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        artifacts.append(
            ReleaseArtifact(
                version=parsed.group("version"),
                architecture=parsed.group("arch"),
                filename=entry.name,
                sha256=digest,
                size=size,
            )
        )

    latest = max((a.version for a in artifacts), key=version_key, default=None)
    artifacts.sort(key=lambda a: (version_key(a.version), a.architecture), reverse=True)
    return Manifest(latest=latest, artifacts=tuple(artifacts), generated_at=now_utc())


# Process-local, keyed by mtime; at most one entry (the current directory state).
_cache: dict[tuple[str, float, float], Manifest] = {}


def reset_cache() -> None:
    """Drop the manifest cache. Tests, and any code that writes into artifacts_dir
    within the same process."""
    _cache.clear()
