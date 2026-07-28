#!/usr/bin/env bash
# Build one agentd release from this checkout and lay it out the way Central serves it
# (ADR 0011, ADR 0020 §8, tech §15.3/§20.3).
#
# Why this exists next to `bake_artifacts.py`. That script downloads a published release
# and verifies it against the release's own `checksums.txt`. It cannot be used when the
# release assets live behind authentication — an unauthenticated fetch of a private
# repository's asset answers 404, so the image build fails with no release baked in and
# `/api/downloads` and `/api/install-script` keep answering 404. This script covers that
# case by removing the fetch entirely: the bytes come from the commit being built.
#
# The trust model that swaps in. There is no external digest to compare against, because
# there is no external source; what `checksums.txt` records here is what this build
# produced. The digest chain the *node* relies on is unchanged — `deploy/install.sh` and
# `daemon/internal/update` both verify the tarball against this file before executing
# anything (tech §23 #12). Release signing remains a separate decision (ADR 0017).
#
#   pack-agentd.sh <dest> [version]     # run from the daemon module root
#
# The version is not an input the deployment supplies. It is declared in `daemon/VERSION`
# alongside the code being compiled, because it describes that code: a platform variable
# would let the image serve a binary labelled with a version nobody built. The optional
# argument exists for tests.
set -euo pipefail

DEST="${1:-}"
VERSION="${2:-}"
[ -n "$DEST" ] || {
  echo "usage: pack-agentd.sh <dest> [version]" >&2
  exit 2
}

if [ -z "$VERSION" ]; then
  [ -r VERSION ] || {
    echo "error: no VERSION file in $(pwd); run this from the daemon module root" >&2
    exit 1
  }
  VERSION="$(tr -d '[:space:]' < VERSION)"
fi
[ -n "$VERSION" ] || { echo "error: VERSION is empty" >&2; exit 1; }

# The same character class `bake_artifacts.py` enforces, for the same reason: the version
# is interpolated into a filename and into linker flags, and a name this script can write
# but `ARTIFACT_PATTERN` will not serve is an artifact that exists and cannot be fetched.
case "$VERSION" in
  *[!0-9A-Za-z.+_-]*)
    echo "error: refusing to build an artifact name from version '$VERSION'" >&2
    exit 1
    ;;
esac

ARCHITECTURES="amd64 arm64"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

mkdir -p "$DEST"

for arch in $ARCHITECTURES; do
  mkdir -p "$WORKDIR/$arch"
  echo "Building agentd ${VERSION} for linux/${arch}…"
  # Flags kept in step with daemon/.goreleaser.yaml. `-trimpath` is not cosmetic: it is
  # what makes "same commit, two builds, same checksum" hold (ADR 0017), and it keeps the
  # build machine's absolute paths out of a shipped artifact.
  CGO_ENABLED=0 GOOS=linux GOARCH="$arch" \
    go build -trimpath -ldflags "-s -w -X main.version=${VERSION}" \
      -o "$WORKDIR/$arch/agentd" ./cmd/agentd

  # `agentd` must be a regular file at the archive ROOT. `daemon/internal/update/files.go`
  # extracts exactly one member by that exact name and ignores anything carrying a
  # directory part, so `bin/agentd` would fail on the node *after* the download rather
  # than here. The flags after it drop mtimes and ownership so two builds of one commit
  # produce identical bytes.
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -czf "$DEST/agentd_${VERSION}_linux_${arch}.tar.gz" -C "$WORKDIR/$arch" agentd
done

# Generated inside $DEST so the recorded names carry no directory part: `checksums.txt` is
# parsed by `app/services/releases.py` and grepped by `deploy/install.sh`, and both expect
# GoReleaser's bare `<sha256>  <filename>` lines.
(
  cd "$DEST"
  # shellcheck disable=SC2086  # the glob must expand
  sha256sum agentd_${VERSION}_linux_*.tar.gz > checksums.txt
)

echo "built and wrote: $(cd "$DEST" && echo agentd_${VERSION}_linux_*.tar.gz) checksums.txt"
