#!/usr/bin/env bash
# GATE-PV-ARGV-CHANNEL — nobody outside the node may name a launch argument.
#
# ADR 0023 gave the daemon a launch flag of its own (codex's sandbox bypass). The
# property that has to survive that is the half of SCOPE-011 ADR 0021 §1 kept: the
# console and Central send a runtime id, and the node decides the argv.
#
# This gate is not aimed at malice. It is aimed at the next reasonable-sounding
# request — "let the user pick --model", "let Central turn the sandbox on for this one
# session" — whose shortest implementation is a new field, and which no existing test
# would notice. ADR 0021 §Context records what that looked like last time: green CI,
# unchanged coverage, and a scope change nobody reviewed.
#
#   scripts/pv/check-no-argv-channel.sh
#
# Exits non-zero on the first violation, printing the file and line.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
FAILED=0

fail() {
  echo "FAIL: $1" >&2
  FAILED=1
}

# 1. No wire schema may carry an argv-shaped or posture-setting property. `sandbox_bypass`
#    and `privileged_terminal` are exempt where they belong — node → Central reports —
#    and nowhere else.
for schema in contracts/v1/schemas/messages/*.schema.json; do
  base="$(basename "$schema")"
  case "$base" in
    runtime-item.schema.json | node-register.schema.json) forbidden='"(args|argv|command|flags|shell|env|entrypoint|sudo|tmux_options)"' ;;
    *) forbidden='"(args|argv|command|flags|shell|env|entrypoint|sudo|tmux_options|sandbox|sandbox_bypass|privileged_terminal)"' ;;
  esac
  if hits="$(grep -nE "$forbidden[[:space:]]*:" "$schema")"; then
    fail "$base declares a launch-argument or posture-setting property:"
    echo "$hits" >&2
  fi
done

# 2. The node's config may gate the daemon's flags with a boolean; it may not name them.
if hits="$(grep -rnE 'yaml:"(args|argv|flags|command|entrypoint)"' daemon/internal/config/)"; then
  fail "daemon config declares an argv field (a boolean is the only permitted control):"
  echo "$hits" >&2
fi

# 3. Exactly one place may hold launch arguments. If a second appears, the answer to
#    "what gets passed to a CLI" stops being greppable.
tables="$(grep -rln 'SandboxBypassFlag[[:space:]]*=' daemon/internal/ | grep -v _test.go)"
if [ "$(printf '%s\n' "$tables" | grep -c .)" -ne 1 ]; then
  fail "the launch-flag constant must be declared exactly once; found:"
  printf '%s\n' "$tables" >&2
fi

# 4. Central builds session.start from the five contract fields only. A sixth key here
#    would be a posture or an argument travelling from the platform to the node.
start_payload="$(sed -n '/"session.start",/,/^            )/p' backend/app/services/sessions.py)"
for key in args argv command flags sandbox sudo env entrypoint; do
  if printf '%s' "$start_payload" | grep -qE "\"$key\""; then
    fail "backend session.start payload carries \"$key\""
  fi
done

# 5. Both posture switches must still exist as a node-side veto. If either disappears,
#    the posture stops being refusable and ADR 0023's opt-out is gone.
grep -q 'SandboxBypass \*bool' daemon/internal/config/config.go ||
  fail "runtime.sandbox_bypass is gone: the node can no longer refuse the bypass"
grep -q 'NoNewPrivileges=true' daemon/internal/install/systemd.go ||
  fail "the unprivileged unit no longer sets NoNewPrivileges"
grep -q 'hardeningPrivileged' daemon/internal/install/systemd.go ||
  fail "the privileged unit no longer explains why NoNewPrivileges is absent"

if [ "$FAILED" -eq 0 ]; then
  echo "OK: no argv channel, and both posture vetoes are in place"
fi
exit "$FAILED"
