#!/usr/bin/env bash
# The three layout invariants from plan/09, in one place because two callers need
# them: .github/workflows/ci.yml (every push) and scripts/ly/evidence.sh (the exit
# gate pack). Duplicating them would let the pack and CI drift, and the drift would
# not be visible — both would still be green.
#
#   scripts/ly/layout-gates.sh              # all three
#   scripts/ly/layout-gates.sh height       # one of: height | panels | sidebar
#
# These are cheap text checks, deliberately. They cannot see geometry — only the
# measuring Playwright test can, and it needs a browser and a full stack. What they
# can do is stop the *specific* CSS that caused the collapse from coming back, on
# every push, with no browser at all.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

status=0

# D1: one source of height. A view that computes its own from the viewport will
# disagree with the shell's, and the disagreement shows up as a page that scrolls a
# little rather than as an obvious error. LoginView has no app shell around it, and
# AppLayout is the shell.
gate_height() {
  if grep -rnE '^[[:space:]]*(min-|max-)?height:[^;]*(100vh|100dvh)' frontend/src |
    grep -vE '^frontend/src/components/layout/AppLayout\.vue:|^frontend/src/views/LoginView\.vue:'; then
    echo "FAIL: a view re-derived the page height (plan/09 D1)."
    echo "      Height comes from the app shell; a page that owns the viewport uses <AppLayout fill>."
    status=1
  else
    echo "ok: no view derives its own page height"
  fi
}

# D3: panels must not size themselves by counting children. Two of these three have
# conditionally rendered children, so a grid row template hands the 1fr to whichever
# child happens to land there — which is how the CLI terminal spent three phases at
# half the height of its pane with every gate green.
gate_panels() {
  local file="$1" selector="$2" block
  block=$(awk -v sel="$selector" 'index($0, sel" {") == 1 { inside = 1 }
                                  inside { print }
                                  inside && /^}/ { exit }' "$file")
  if [ -z "$block" ]; then
    echo "FAIL: $file: rule $selector not found — renamed? update this gate with it"
    status=1
    return
  fi
  if ! printf '%s\n' "$block" | grep -q 'display: flex'; then
    echo "FAIL: $file $selector must be a flex column (plan/09 D3)"
    status=1
  fi
  if printf '%s\n' "$block" | grep -q 'grid-template-rows'; then
    echo "FAIL: $file $selector must not size itself with a row template (plan/09 D3)"
    status=1
  fi
  [ "$status" -eq 0 ] && echo "ok: $selector takes its height from flex"
  return 0
}

# D5/D6: the rail's width lives in three places (the token, style.md §9's prose and
# §22's token block). This phase exists partly because a previous one changed a
# number in one of them only.
gate_sidebar() {
  local token spec
  token=$(sed -nE 's/^[[:space:]]*--layout-sidebar:[[:space:]]*([0-9]+)px;.*/\1/p' \
    frontend/src/theme/tokens.css)
  spec=$(sed -nE 's/^[[:space:]]*sidebar:[[:space:]]*([0-9]+)[[:space:]]*$/\1/p' research/style.md)
  if [ -z "$token" ]; then
    echo "FAIL: could not read --layout-sidebar from tokens.css"
    status=1
    return
  fi
  if [ "$token" != "$spec" ]; then
    echo "FAIL: tokens.css says ${token}px, research/style.md §22 says ${spec} (plan/09 D5)"
    status=1
    return
  fi
  if ! grep -A2 '^Sidebar$' research/style.md | grep -qx "${token}px"; then
    echo "FAIL: research/style.md §9 does not list Sidebar as ${token}px (plan/09 D5)"
    status=1
    return
  fi
  echo "ok: the rail is ${token}px in the token and in both halves of style.md"
}

case "${1:-all}" in
height) gate_height ;;
panels)
  gate_panels frontend/src/views/SessionWorkspaceView.vue .terminal-pane
  gate_panels frontend/src/components/file/PreviewPane.vue .preview
  gate_panels frontend/src/components/file/FileTree.vue .tree-panel
  ;;
sidebar) gate_sidebar ;;
all)
  gate_height
  gate_panels frontend/src/views/SessionWorkspaceView.vue .terminal-pane
  gate_panels frontend/src/components/file/PreviewPane.vue .preview
  gate_panels frontend/src/components/file/FileTree.vue .tree-panel
  gate_sidebar
  ;;
*)
  echo "usage: $0 [height|panels|sidebar|all]" >&2
  exit 2
  ;;
esac

exit "$status"
