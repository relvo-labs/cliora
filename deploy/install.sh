#!/usr/bin/env bash
# Cliora daemon one-line installer (ADR 0011, tech §15.1).
#
# Thin by design: it only detects the distro/arch, downloads the matching agentd
# binary from --server, verifies its SHA256 against checksums.txt, then hands off
# to `agentd install`, which performs every real step (register, write 0600
# config/credentials, systemd unit, start as the non-root --user). The enrollment
# token is never printed; it is passed straight through to the binary.
#
#   curl -fsSL https://platform.example.com/api/install-script | sudo bash -s -- \
#     --server https://platform.example.com --token enroll_xxx --name dev-vm-01 --user neil
set -euo pipefail

SERVER=""
TOKEN=""
NAME=""
RUN_USER=""
ALLOW_INSECURE=0
WORKSPACE_ROOTS=()

die() { echo "error: $*" >&2; exit 1; }
warn() { echo "warning: $*" >&2; }

usage() {
  cat >&2 <<'EOF'
Usage: install.sh --server URL --token TOKEN --name NAME --user USER
                  [--workspace-root PATH]... [--allow-insecure]
EOF
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --server) SERVER="${2:-}"; shift 2 ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --user) RUN_USER="${2:-}"; shift 2 ;;
    --workspace-root) WORKSPACE_ROOTS+=("${2:-}"); shift 2 ;;
    --allow-insecure) ALLOW_INSECURE=1; shift ;;
    -h | --help) usage ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$SERVER" ] && [ -n "$TOKEN" ] && [ -n "$NAME" ] && [ -n "$RUN_USER" ] || usage
[ "$(id -u)" -eq 0 ] || die "install.sh must run as root (pipe to 'sudo bash')"
[ "$(uname -s)" = "Linux" ] || die "the Cliora daemon supports Linux only"

# Read the distro id in a subshell so os-release's own NAME/VERSION do not
# clobber the caller's --name argument.
if [ -r /etc/os-release ]; then
  distro_id="$(. /etc/os-release 2>/dev/null && echo "${ID:-}")"
  case "$distro_id" in
    ubuntu | debian) : ;;
    *) die "unsupported distribution '${distro_id:-unknown}' (supported: Ubuntu, Debian)" ;;
  esac
fi

case "$(uname -m)" in
  x86_64 | amd64) ARCH="amd64" ;;
  aarch64 | arm64) ARCH="arm64" ;;
  *) die "unsupported architecture '$(uname -m)' (supported: amd64, arm64)" ;;
esac

command -v curl >/dev/null 2>&1 || die "curl is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v tar >/dev/null 2>&1 || die "tar is required"

# tmux is required by the daemon to host terminal sessions, but it is NOT needed
# by this installer nor by the control-plane path (register + heartbeat + status).
# So a missing tmux degrades rather than blocks the node: enrollment and status
# still work, but session features stay unavailable until tmux is installed. We
# warn (not die) here — unlike curl/sha256sum/tar, which install.sh itself needs.
# `agentd doctor` reports the same condition after install. (No token is echoed.)
command -v tmux >/dev/null 2>&1 || warn \
  "tmux not found: this node will install and report status, but terminal sessions require tmux (e.g. 'apt-get install -y tmux'); install it and restart agentd to enable sessions"

BASE="${SERVER%/}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "Fetching checksums…"
curl -fsSL "$BASE/api/downloads/checksums.txt" -o "$WORKDIR/checksums.txt" \
  || die "could not download checksums from $BASE"

line="$(grep "_linux_${ARCH}.tar.gz" "$WORKDIR/checksums.txt" | head -n1 || true)"
[ -n "$line" ] || die "no agentd build for linux/${ARCH} was published"
expected_sha="$(echo "$line" | awk '{print $1}')"
filename="$(echo "$line" | awk '{print $2}')"

echo "Downloading ${filename}…"
curl -fsSL "$BASE/api/downloads/${filename}" -o "$WORKDIR/${filename}" \
  || die "could not download ${filename}"

echo "Verifying checksum…"
echo "${expected_sha}  ${WORKDIR}/${filename}" | sha256sum -c - >/dev/null 2>&1 \
  || die "checksum verification failed for ${filename} (aborting install)"

tar -xzf "$WORKDIR/${filename}" -C "$WORKDIR" || die "failed to extract ${filename}"
bin="$(find "$WORKDIR" -type f -name agentd | head -n1)"
[ -n "$bin" ] || die "agentd binary not found in the downloaded archive"
chmod +x "$bin"

install_args=(install --server "$SERVER" --token "$TOKEN" --name "$NAME" --user "$RUN_USER")
for root in "${WORKSPACE_ROOTS[@]:-}"; do
  [ -n "$root" ] && install_args+=(--workspace-root "$root")
done
[ "$ALLOW_INSECURE" -eq 1 ] && install_args+=(--allow-insecure)

echo "Running agentd install…"
exec "$bin" "${install_args[@]}"
