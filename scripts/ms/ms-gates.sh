#!/usr/bin/env bash
# The plan/29 mobile gates, in one place because two callers need them:
# .github/workflows/ci.yml and a future scripts/ms/evidence.sh. Same shape and
# same reasoning as scripts/vr/vr-gates.sh and scripts/ly/layout-gates.sh.
#
#   scripts/ms/ms-gates.sh              # both
#   scripts/ms/ms-gates.sh breakpoint   # one of: breakpoint | history-path
#
# WHAT THESE CATCH, AND WHAT THEY CANNOT
#
# Both are text checks. Neither can see a rendered pixel, so neither can tell
# you that a control is smaller than the touch floor, that the drawer will not
# open at 1024px, or that the safe-area padding resolved to zero. Those are
# browser measurements and they live in frontend/tests/e2e/mobile.spec.ts.
#
# plan/29 originally specified a third gate, GATE-MS-TOUCH-TOKEN, as a text
# check for hardcoded control heights. It was dropped after measuring: 40 of the
# literal `height: NNpx` declarations under frontend/src are icon sizes and
# sr-only 1px clips, so the rule would have been mostly exemptions, and a gate
# that is mostly exemptions teaches people to add another one. The failure it
# was aimed at — a control under 44x44 — is geometry, and the E2E measures it
# directly.
#
# What these two buy is the failure that *accumulates*: a width literal creeping
# back into a component, and a path creeping into browser history.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

status=0
SRC="frontend/src"

# GATE-MS-BREAKPOINT
#
# One source for the viewport widths. Before plan/29 there were three —
# AppLayout's 768, SessionWorkspaceView's 1024, and a `max-width: 1100px` in
# that view's stylesheet — and the 76px between the last two was a file panel
# that, at 1024-1100px, was in the DOM, `display: none`, and had no control to
# open it. Nobody introduced that on purpose; it is what three literals do over
# time.
#
# CSS cannot import a TypeScript constant, so stylesheets still spell the
# numbers out. This holds the set closed instead.
ALLOWED='767|768|1023|1024|1439|1440'
gate_breakpoint() {
  local hits
  # Width-valued media features only. `prefers-reduced-motion`,
  # `prefers-color-scheme` and the like carry no number and never match.
  hits=$(grep -rnE '@media[^{]*(min|max)-width:[[:space:]]*[0-9]+px' "$SRC" \
    --include='*.vue' --include='*.css' 2>/dev/null |
    grep -vE "(min|max)-width:[[:space:]]*($ALLOWED)px" |
    # Comment lines, same exemption and same anchoring as vr-gates. A media
    # query inside a comment is prose, and this repository's prose quotes the
    # rules it removed — SessionWorkspaceView explains the 1100px it deleted.
    grep -vE ':[0-9]+:[[:space:]]*(//|\*|/\*|<!--)' || true)
  if [ -n "$hits" ]; then
    printf '%s\n' "$hits"
    echo "FAIL: a @media width outside the four breakpoints (plan/29 MS-01)."
    echo "      Allowed: $ALLOWED. If a layout needs another one, it needs a"
    echo "      breakpoint, and a breakpoint is a decision — not a local number."
    status=1
  else
    echo "ok: every @media width is one of the four breakpoints"
  fi

  # And the JavaScript half. `useBreakpoint.ts` is the one file allowed to
  # compare against a width; anywhere else it is a layout decision that cannot
  # react to a boundary and cannot be found by grep later.
  hits=$(grep -rnE 'innerWidth[[:space:]]*[<>]' "$SRC" \
    --include='*.vue' --include='*.ts' 2>/dev/null |
    grep -vE '^frontend/src/composables/useBreakpoint\.ts:' |
    grep -vE '\.test\.ts:' || true)
  if [ -n "$hits" ]; then
    printf '%s\n' "$hits"
    echo "FAIL: a layout decision read innerWidth directly (plan/29 MS-01)."
    echo "      Use useBreakpoint(). It listens with matchMedia, which fires"
    echo "      once at the boundary rather than on every frame of a drag."
    status=1
  else
    echo "ok: only useBreakpoint.ts compares against a viewport width"
  fi
}

# GATE-MS-HISTORY-PATH
#
# A workspace-relative path must not reach browser history (ADR 0014 keeps paths
# server-validated; plan/29 addendum §1/§7 keeps them out of anything durable).
#
# The mobile preview pushes one history entry so the system Back button closes
# the preview instead of leaving the session. That entry is deliberately inert:
# `pushState(null, "", window.location.href)`. The tempting version — putting
# the path in the URL or in the state object — would make it shareable,
# loggable, and present in the back-forward cache, which is the whole category
# the addendum rules out.
gate_history_path() {
  local hits
  hits=$(grep -rnE '(pushState|replaceState)\(' "$SRC" \
    --include='*.vue' --include='*.ts' 2>/dev/null |
    grep -vE '\.test\.ts:' |
    grep -vE 'pushState\(null, "", window\.location\.href\)' || true)
  if [ -n "$hits" ]; then
    printf '%s\n' "$hits"
    echo "FAIL: a history entry carries something (plan/29 MS-08)."
    echo "      The only permitted call is"
    echo '      pushState(null, "", window.location.href) — no state, same URL.'
    echo "      A path in history is a path in the URL bar, in shared links and"
    echo "      in the bfcache."
    status=1
  else
    echo "ok: history entries carry no state and no path"
  fi
}

case "${1:-all}" in
breakpoint) gate_breakpoint ;;
history-path) gate_history_path ;;
all)
  gate_breakpoint
  gate_history_path
  ;;
*)
  echo "unknown gate: $1" >&2
  echo "usage: $0 [breakpoint|history-path]" >&2
  exit 2
  ;;
esac

exit "$status"
