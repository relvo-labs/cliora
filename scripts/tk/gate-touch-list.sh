#!/usr/bin/env bash
# GATE-TK-TOUCH-LIST (plan/17 D12): V2.1 *does* touch the daemon and the contract, so
# the V2.0-era "zero diff there" gate cannot be reused — and dropping it entirely would
# leave the phase's most load-bearing claim unchecked.
#
# The claim is narrower and sharper than V2.0's: the projection needed a new write verb
# and one message pair. The security/retention review subsequently required two
# narrow hardenings: projected tokens are intrinsic-sensitive in policy/search,
# and the session manager exposes live workspaces to the projection cleanup loop.
# Terminal, tmux, tunnel, recovery and the existing read/store/upload paths remain
# untouched.
#
# So this gate is an allowlist for the daemon and contract trees, and a denylist for the
# parts of them that must not move. The denylist is the half worth reading: if it ever
# needs an exemption, that is a design change and belongs in an ADR rather than in this
# file.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASE="${1:-origin/v2}"

# Files V2.1 is allowed to add or change under the otherwise-frozen trees.
ALLOWED='^(daemon/internal/files/(project|project_test|store_policy|policy|search|files_test)\.go|daemon/internal/session/manager(_test)?\.go|daemon/internal/config/|daemon/internal/cli/|daemon/internal/connection/(connection|files_handlers)\.go|daemon/internal/protocol/codec\.go|daemon/internal/install/|daemon/cmd/agentd/(main|install)\.go|daemon/VERSION|contracts/)'
# Files that must not move at all. These are the phase's actual promise.
FORBIDDEN='^daemon/internal/(terminal|tmux|tunnel|update|workspace|systeminfo|runtime|metrics)/|^daemon/internal/session/(integration_test|recovery_test|scrollback_integration_test)\.go$|^daemon/internal/files/(store|upload|read|list|service)\.go$'

CHANGED="$( { git diff --name-only "$BASE"...HEAD 2>/dev/null || true; git status --porcelain | awk '{print $2}'; } | sort -u )"

VIOLATIONS="$(printf '%s\n' "$CHANGED" | grep -E "$FORBIDDEN" || true)"
if [ -n "$VIOLATIONS" ]; then
  echo "V2.1 must not touch these — terminal, tmux, tunnel, recovery and existing read/store/upload paths:" >&2
  printf '  %s\n' $VIOLATIONS >&2
  exit 1
fi

# Everything under daemon/ or contracts/ has to be on the allowlist.
UNEXPECTED="$(printf '%s\n' "$CHANGED" | grep -E '^(daemon/|contracts/)' | grep -Ev "$ALLOWED" || true)"
if [ -n "$UNEXPECTED" ]; then
  echo "unexpected node-side changes (add them to the allowlist deliberately, or don't make them):" >&2
  printf '  %s\n' $UNEXPECTED >&2
  exit 1
fi

echo "node-side changes stay inside the projection's footprint"
