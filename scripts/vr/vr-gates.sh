#!/usr/bin/env bash
# The four plan/28 visual-refresh gates, in one place because two callers need
# them: .github/workflows/ci.yml (every push) and scripts/vr/evidence.sh (the
# exit pack). Duplicating them would let CI and the pack drift, and the drift
# would not be visible — both would still be green. Same reasoning, and the same
# shape, as scripts/ly/layout-gates.sh.
#
#   scripts/vr/vr-gates.sh                  # all four
#   scripts/vr/vr-gates.sh literal-color    # one of:
#                                           #   literal-color | legacy-token
#                                           #   glyph-icon | theme-contract
#
# WHAT THESE CATCH, AND WHAT THEY CANNOT
#
# Three of the four are pure text checks and the fourth is pure arithmetic. None
# of them can see a rendered pixel. Specifically they do NOT catch:
#
#   * "used a token, but the wrong token" — border.subtle where border.control
#     belongs looks identical to a grep;
#   * "the theme switch rebuilt the terminal" — that is a runtime behaviour;
#   * "the drawer will not open at 1024px" — that needs layout.
#
# Those three are the browser measurements in frontend/tests/e2e/theme.spec.ts.
# What these gates do buy is the failure that *accumulates*: they cannot stop a
# token being used wrongly once, but they stop the palette being bypassed
# entirely, which is how 69 literal colours arrived in 13 files.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

status=0
SRC="frontend/src"
# The two files that ARE the colour source. Everything else is a consumer.
# Anchored with the trailing colon because grep -n prefixes `path:line:`, so a
# `$`-anchored path pattern would never match anything.
THEME_EXEMPT='^frontend/src/theme/(tokens\.css|themes\.ts):'
# Test files are exempt, and the reason is narrow: a *.test.ts cannot style
# anything, and theme.contrast.test.ts deliberately holds the five historical
# failing values as fixtures ("--border-focus #67a2ae measured 2.85") so that
# reintroducing one of them goes red by name. Exempting them keeps that evidence
# where it is useful instead of pushing it into prose.
TEST_EXEMPT='\.test\.ts:'

# GATE-VR-NO-LITERAL-COLOR
#
# Ordering note that is easy to get wrong: this gate is only honest *after* the
# token table has an exit for every case that needed a literal. Before plan/28
# there was no row for a badge's foreground/background pair and no terminal
# colour at all, so the 69 literals were not carelessness — they had nowhere
# else to go. A gate landed before the table would only have taught people to
# add an exemption.
gate_literal_color() {
  local hits
  hits=$(grep -rnE '#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(' "$SRC" \
    --include='*.vue' --include='*.ts' --include='*.css' 2>/dev/null |
    grep -vE "$THEME_EXEMPT" | grep -vE "$TEST_EXEMPT" || true)
  # A colour named inside a comment is evidence, not a colour: several comments
  # quote the measured value they are replacing ("blue #3465A4 measures 3.13").
  hits=$(printf '%s\n' "$hits" | grep -vE ':\s*(//|\*|/\*|<!--)' || true)
  hits=$(printf '%s\n' "$hits" | grep -vE '^\s*$' || true)
  if [ -n "$hits" ]; then
    printf '%s\n' "$hits"
    echo "FAIL: literal colour outside theme/tokens.css and theme/themes.ts (ADR 0027 §3)."
    echo "      Add a semantic token instead. If no token fits, the table is missing a"
    echo "      row — add it there, with its measured contrast, not here."
    status=1
  else
    echo "ok: no literal colour outside the two theme files"
  fi
}

# GATE-VR-NO-LEGACY-TOKEN
#
# The old palette's names. Without this, a copied-in snippet reintroduces
# `--text-muted`, which resolves to nothing, and the symptom is a component that
# inherits its parent's colour — visible only as "slightly odd".
LEGACY_TOKENS=(
  --surface-elevated
  --text-muted
  --text-inverse
  --border-default
  --border-focus
  --border-danger
  --action-primary
  --action-primary-hover
  --action-disabled
  --status-online
  --status-offline
  --status-busy
  --radius-sm
  --radius-md
  --radius-lg
)
gate_legacy_token() {
  local found=0 token hits
  for token in "${LEGACY_TOKENS[@]}"; do
    # The negative lookahead matters: --status-error is legacy, but
    # --status-error-fg is current, and a plain substring match would report
    # every use of the new name.
    hits=$(grep -rnE -- "${token}(\$|[^a-zA-Z0-9-])" "$SRC" \
      --include='*.vue' --include='*.ts' --include='*.css' 2>/dev/null |
      grep -vE ':\s*(//|\*|/\*|<!--)' || true)
    if [ -n "$hits" ]; then
      printf '%s\n' "$hits"
      found=1
    fi
  done
  if [ "$found" -eq 1 ]; then
    echo "FAIL: a retired token name is back (plan/28 02-…md §11)."
    echo "      These resolve to nothing, so the symptom is an element inheriting its"
    echo "      parent's colour rather than an error."
    status=1
  else
    echo "ok: no retired token names"
  fi
}

# GATE-VR-NO-GLYPH-ICON
#
# The seven navigation glyphs, plus the size bound on theme-boot.js.
#
# The glyphs were not merely unfashionable: `▷` is font-substituted differently
# per platform (sometimes as an emoji variant, with a different width and
# weight), and each was a *readable text node*, so a screen reader announced it
# with whatever name the matched font's database gave. Once the rail collapses
# to icons only they would have been its entire visual content.
GLYPHS='◫|◈|▣|▷|◉|☰|⇄'
gate_glyph_icon() {
  local hits
  hits=$(grep -rnE "$GLYPHS" "$SRC" --include='*.vue' 2>/dev/null |
    grep -vE ':\s*(//|\*|/\*|<!--)' || true)
  if [ -n "$hits" ]; then
    printf '%s\n' "$hits"
    echo "FAIL: a text glyph is being used as an icon (ADR 0027, style.md §20)."
    echo "      Use a Lucide component. A glyph is font-substituted per platform and"
    echo "      is announced by a screen reader as whatever the font calls it."
    status=1
  else
    echo "ok: no text glyphs used as icons"
  fi

  # theme-boot.js is the one unbundled script plan/28 accepts, and the deal is
  # that it stays small enough that reading it is the whole audit.
  local boot="frontend/public/theme-boot.js" lines
  if [ ! -f "$boot" ]; then
    echo "FAIL: $boot is missing — the theme would apply after first paint (FOUC)."
    status=1
    return 0
  fi
  # Strip block and line comments first. Without this the check reads the
  # file's own header, which says it "imports nothing" — and finds the word.
  local code
  code=$(awk '
    { line = $0 }
    /\/\*/ { inblock = 1 }
    inblock { if (line ~ /\*\//) { inblock = 0 }; next }
    { sub(/\/\/.*/, "", line); if (line ~ /[^[:space:]]/) print line }
  ' "$boot")
  lines=$(printf '%s\n' "$code" | grep -c '[^[:space:]]' || true)
  if [ "$lines" -gt 12 ]; then
    echo "FAIL: $boot has $lines code lines (limit 12)."
    echo "      It blocks first paint and runs outside the bundle. Anything beyond"
    echo "      reading a key and setting an attribute belongs in main.ts."
    status=1
  elif printf '%s\n' "$code" | grep -qE '\b(import|require\(|fetch\(|eval\()'; then
    echo "FAIL: $boot imports or fetches something."
    status=1
  else
    echo "ok: theme-boot.js is $lines code lines, imports nothing"
  fi
}

# GATE-VR-THEME-CONTRACT
#
# The only one of the four that is not a grep. Three tests: tokens.css agrees
# with themes.ts key by key, every theme defines every token (toEqual, not
# containment), and every declared pair meets its measured target.
gate_theme_contract() {
  if (cd frontend && npm run --silent test:unit -- --run src/theme); then
    echo "ok: token contract, completeness and contrast all pass"
  else
    echo "FAIL: the theme contract is broken (ADR 0027 §2/§8)."
    echo "      Two colour sources is a deliberate cost; this test is the fuse."
    status=1
  fi
}

case "${1:-all}" in
literal-color) gate_literal_color ;;
legacy-token) gate_legacy_token ;;
glyph-icon) gate_glyph_icon ;;
theme-contract) gate_theme_contract ;;
all)
  gate_literal_color
  gate_legacy_token
  gate_glyph_icon
  gate_theme_contract
  ;;
*)
  echo "usage: $0 [literal-color|legacy-token|glyph-icon|theme-contract|all]" >&2
  exit 2
  ;;
esac

exit "$status"
