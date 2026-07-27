#!/usr/bin/env bash
# Drill: ClioraDaemonUpdateFailed, via a deliberate checksum mismatch.
#
# Appends a byte to a published artifact without updating checksums.txt, so the daemon
# downloads it, computes a different digest, and aborts at the `checksum` stage. Nothing
# is installed — which is the property being demonstrated.
. "$(dirname "$0")/_common.sh"

ARTIFACTS="${CLIORA_ARTIFACTS_DIR:-}"
VERSION="${CLIORA_DRILL_VERSION:-}"
ARCH="${CLIORA_DRILL_ARCH:-amd64}"

if [ -z "$ARTIFACTS" ] || [ -z "$VERSION" ]; then
  echo "Set CLIORA_ARTIFACTS_DIR and CLIORA_DRILL_VERSION (a published release)." >&2
  exit 1
fi
ARTIFACT="${ARTIFACTS}/agentd_${VERSION}_linux_${ARCH}.tar.gz"
[ -f "$ARTIFACT" ] || { echo "No such artifact: ${ARTIFACT}" >&2; exit 1; }

confirm "This corrupts ${ARTIFACT} (a byte is appended) so the next update fails its
checksum check. The original is restored at the end."

BACKUP="$(mktemp)"
cp "$ARTIFACT" "$BACKUP"
# shellcheck disable=SC2064
trap "echo; echo 'Restoring ${ARTIFACT}'; cp '${BACKUP}' '${ARTIFACT}'; rm -f '${BACKUP}'" EXIT

printf 'drill' >>"$ARTIFACT"
echo "Corrupted. checksums.txt is unchanged, so the published digest no longer matches."

banner "Attempting the update (expect UPDATE_CHECKSUM_MISMATCH)"
sudo agentd update --version "${VERSION}" --dry-run || true

banner "Confirm nothing was installed"
sudo agentd version

follow_up "cliora_node_update_total{status!=\"succeeded\"}" "docs/runbooks/update-failure.md §6"
