#!/usr/bin/env bash
# GATE-PJ-NO-WIRE (plan/16 D12): V2.0 touches no daemon, no protocol, no file
# surface, no terminal, and does not move the deployment surface. The claim that
# this phase adds a data model and two screens *without shifting any existing risk
# surface* is only worth something if something checks it.
#
# One narrowing, added deliberately in PJ-09 rather than to make a failure go away:
# `deploy/` holds two kinds of file. `nginx.conf`, the compose topology and the
# Railway service definitions are **behaviour** — changing them changes what a
# deployment does, and they stay forbidden. `.env.example` and the `*.md` guides are
# **documentation**: nothing reads them at runtime, and `research/02/11` §3 requires
# a new environment variable to be documented in exactly those files. Forbidding
# them would make the plan self-contradictory.
#
# The exemption is printed, never silent: a gate that quietly excuses things is a
# gate nobody can audit.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASE="${1:-origin/v2}"
FORBIDDEN='^(daemon/|contracts/|backend/app/api/ws/|deploy/|frontend/src/(protocol|monaco)/|backend/app/services/(files|terminal_relay|terminal_queue|tunnels|integrations|node_update)\.py$)'
# Documentation under an otherwise-forbidden tree.
DOCS_ONLY='^deploy/.*(\.env\.example|\.md)$'

CHANGED="$( { git diff --name-only "$BASE"...HEAD 2>/dev/null || true; git status --porcelain | awk '{print $2}'; } | sort -u )"
MATCHED="$(printf '%s\n' "$CHANGED" | grep -E "$FORBIDDEN" || true)"
EXEMPT="$(printf '%s\n' "$MATCHED" | grep -E "$DOCS_ONLY" || true)"
HITS="$(printf '%s\n' "$MATCHED" | grep -Ev "$DOCS_ONLY" || true)"

if [ -n "$EXEMPT" ]; then
  echo "documentation-only, allowed:"
  printf '  %s\n' $EXEMPT
fi

if [ -n "$HITS" ]; then
  echo "V2.0 must not touch these:"
  printf '  %s\n' $HITS
  exit 1
fi
echo "no forbidden paths touched"
