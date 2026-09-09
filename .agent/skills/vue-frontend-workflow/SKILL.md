---
name: vue-frontend-workflow
description: >-
  Implement Cliora's Vue 3, TypeScript, Vite, Pinia, Vue Router, xterm.js, and Monaco frontend. Shared components are hand-built — there is no UI component library. Use when building pages, stores, composables, routes, forms, tables, terminal views, file previews, WebSocket state, or frontend tests.
---

# Vue Frontend Workflow

Renamed from `vue-naive-ui-workflow` in `plan/28` (ADR 0027 §6). Naive UI had
never been used — zero components, one type-only import, and that import's own
file was imported by nothing — so the dependency was removed and the shared
components are built here. Anything in an older plan that names the skill by its
previous title means this one.

1. Use `cliora-project-context`; inspect package manager, scripts, TypeScript config, and source layout.
2. Read PRD section 10, tech section 16, and `research/style.md` as relevant.
3. Separate API types, shared stores, lifecycle composables, views, and presentation components.
4. Model idle, loading, success, empty, **no-results**, stale, reconnecting, offline, forbidden, and error. Empty and no-results are different states with different next actions and must not share wording.
5. Apply semantic tokens from `theme/tokens.css`; **never a literal colour**, and never another palette. If no token fits, the token table is missing a row — add it there with its measured contrast (`GATE-VR-NO-LITERAL-COLOR` blocks the alternative).
6. Test transitions and cleanup, then run existing lint, typecheck, unit, and E2E scripts.

Prefer typed Composition API and Pinia only for shared state. Give each WebSocket, xterm terminal, Monaco model, and subscription one owner and dispose it. Never build shell commands in the renderer. Preserve terminal keyboard, resize, scrollback, and reconnect behavior. Keep the preview read-only — the *workspace* no longer is (ADR 0024) — and distinguish sensitive, oversized, binary and non-UTF-8 files, which need different next steps from the user. Intercept a terminal paste only in the capture phase and only when `clipboardData.files` is non-empty; xterm.js calls `stopPropagation` and reads only `text/plain`, so a bubble listener never fires and an unguarded one breaks ordinary text paste. Gate a write affordance on the server-computed capability *and* the node's own report, and hide it rather than disabling it when either says no.

## Shared components are ours

Reach for `components/ui/` before writing a button, a table or a notice. Four accessibility behaviours are hand-built and must not be re-implemented per call site:

- `useFocusTrap` — focus containment, Escape, and focus **return**, shared by `UiDialog` and the file drawer. `aria-modal` alone does nothing to the Tab order; a dialog without this leaks focus to the page behind it and drops focus to `<body>` on close.
- `WorkspaceTabs` roving tabindex and `FileTree` keyboard handling already exist and are correct. Do not replace them.
- `UiIconButton` makes `label` **required**, so an unnamed icon button cannot be written by accident.
- `Toast` has no `error` member in its type. A message that removes itself after four seconds is one the user may never have read, so failures stay in the region they belong to (`UiInlineNotice`, `ErrorNotice`) and stay put.

Two message components take `message?: string` rather than `unknown`, deliberately: a wider type invites `:message="caught"`, which ships whatever the server said — a stack frame, a query, an internal host name.

## Themes

Colour lives in two files bound by one test: `theme/tokens.css` (CSS custom properties, so a theme switch does not remount anything) and `theme/themes.ts` (resolved strings, because `terminal.options.theme` and `monaco.editor.defineTheme()` cannot take a `var()`). `theme.contract.test.ts` compares them key by key — it is the fuse for a deliberate cost, not paperwork.

Every theme defines **every** token. A gap is not an error at runtime; it silently inherits the previous theme's colour, which reads as "slightly odd" in a screenshot review and is therefore the failure most likely to ship.

Three token rules that are easy to get wrong:

- `--accent-primary` is a fill that **carries no text**. Accent-as-text is `--accent-strong` — in two of the five themes `accent-primary` on `accent-subtle` measures under 4.5:1, and that pair is the selected state of navigation and tabs.
- `--border-subtle` is decoration. A control boundary is `--border-control`; `border.subtle` measures 1.21–1.61:1 against a panel in all five themes.
- On `--accent-subtle`, text is `--text-primary` or `--accent-strong`, never `--text-secondary`.

Disabled is a colour (`--text-disabled`, measured ≥ 3:1 on all three surfaces), never an opacity: opacity dims the label along with everything else, and a disabled control has to be able to say why it is disabled.

A theme switch must not interrupt work: assign `terminal.options.theme` and call `monaco.editor.setTheme` — never construct a new `Terminal` and never unmount a panel holding a socket (`FR-TERM-001.AC-15`). A theme is a display preference; it changes no authorization.
