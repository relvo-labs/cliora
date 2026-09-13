# Mobile session prototype — execution plan

Status: prototype and rollout-plan work only. Baseline `26f4178c7c11e19356c4bafdde0094e17c6cab65`; issues #61/#62/#67, with #64 as the file-mode reference. No production, CI, governance, API, PTY, WebSocket, or persistence changes.

## Design Read

Build one operational, session-first flow: a practical dense session list opens the **exact selected session**, whose Terminal/Files switch remains directly visible with session, node, runtime, and workspace context. Incorporate C's browse/search/read-only-preview pattern inside A's selected information architecture; do not ship two variants.

Visual direction: Porcelain-derived near-white canvas, white surfaces, deep text, and a restrained blue accent. Terminal, code preview, warnings, and errors are entirely light. This is a **new proposal**, not a claim about current production tokens: current Porcelain still gives xterm and Monaco dark surfaces. Use local system fonts with Traditional Chinese fallbacks, restrained visual variance and motion, practical list density, semantic warning/danger colors, visible focus, minimum 44×44 px controls, and no remote fonts or assets.

Design dials: low visual variance; low motion; medium-high operational density. The repository VDS, accessibility rules, product decisions, and source contracts supersede the selected minimalist guidance.

## Causal read receipts

- `/opt/data/cliora-mobile-pr/evidence/project-skills.json` and every hash-pinned repository skill were read and their SHA-256 values matched. They require exact session scoping, read-only preview, no frontend command construction, explicit lifecycle/error states, focus return, and real browser verification.
- `prototypes/visual-refresh/README.md` is historical only: this work will not repeat its private preview URL, stale Naive UI statement, localStorage path/state posture, image-preview implication, or simulated command controls.
- `plan/28/README.md`, `research/style.md` §§1–5, 9, 12–22, 24; `research/prd.md` §§4–6, 8.5.1–8.8, 10, 15–20; and `research/tech.md` §§3, 9–11, 14, 16, 19, 23–24 establish calm dense workbench styling, one visible centre panel, exact CLI/session lifecycles, filename-only file search, read-only Monaco semantics, responsive/focus rules, and production gates that this fixture cannot satisfy.
- ADR 0014/0015 require workspace-relative paths, daemon-authoritative containment, bounded directory/search results, visible partial stop reasons (`results`, `depth`, `scanned`, `timeout`), and explicit binary/encoding/permission/size denials. ADR 0024/0026 keep preview read-only, make editing/rename/delete decided against, leave download unbuilt, and place existing upload outside this prototype. ADR 0021 keeps main CLI detach alive while a system-terminal child shell ends on close/leave. ADR 0027 binds real theme colors across `tokens.css` and `themes.ts`; a future light-terminal change must update both and their contract/contrast tests.
- Issue snapshots #61/#62/#64/#67 select light A Pocket Workbench, require C-style file browsing without a file-first home page, preserve exact-session identity and return state, and reserve real-device/IME/reconnect/RBAC/security proof for later gates.
- Approved sources `cliora-mobile-A.html` and `cliora-mobile-C.html` supplied the compact session hierarchy, direct terminal/file relationship, relative-path context, and bright surfaces. Their copied variants, image/upload controls, fake create/stop/reconnect, and terminal-send demonstrations are not carried forward.
- Current `FileSearchBar.vue`, `FileTree.vue`, `useFileTree.ts`, `stores/files.ts`, `PreviewPane.vue`, `PreviewDenied.vue`, `useMonacoModel.ts`, `SessionWorkspaceView.vue`, `SessionHeader.vue`, `useTerminalSession.ts`, `tokens.css`, and `themes.ts` were inspected. The prototype will mirror whole-workspace filename-substring search, current-directory browsing, partial cursors, session-switch abort/wipe, text/code-only preview, and fresh-ticket/writer/viewer/resize plans without pretending to exercise those production paths.
- `/opt/data/skills/creative/taste-frontend-design/SKILL.md` and its selected `references/upstream/minimalist-skill/SKILL.md` were read. Their useful hierarchy, spacing, flat surfaces, state completeness, and restrained motion are adopted; marketing whitespace, webfonts, remote imagery, ornamental motion, and absolute aesthetic rules are rejected for this operational UI.

## Write set and implementation order

1. Create `prototypes/mobile-session/` with one dependency-free HTML/CSS/JS experience and a short README.
2. Implement in-memory fixtures for normal, empty folder, 403, transient failure with honest retry, unsupported binary/image, too-large file, ended session, and bounded partial search/list behavior.
3. Preserve folder, breadcrumb, query, and actual nonzero list/preview scroll on preview return; return focus to the opening file. On session switch, synchronously clear old path/query/preview/scroll and invalidate pending fixture work.
4. Add a task-owned Python Playwright runner that starts and stops a local HTTP server, writes evidence only to `--evidence-dir`, and uses the explicit Chromium executable.
5. Write `plan/29/README.md` plus the versioned v0.1 mobile rollout addendum with route/component/contract mapping, acceptance IDs, phased DAG, role/write-set ownership, release gates, rollback boundaries, and prototype-vs-production evidence labels.

## Verification gates

- Interaction: list → exact session; Terminal/Files; browse/up/breadcrumb; whole-workspace filename search; partial stop reasons; preview scroll/list scroll/query restoration; focus return; session switch while preview and 403; every fixture state and recovery; Escape and keyboard paths.
- Geometry: 360×844, 390×844, 430×932, 844×390, 768×1024, 1024×768, 1100×800, and 1440×900; no document overflow; every visible interactive target at least 44×44 CSS px.
- Runtime: local HTTP, no network/API/PTY/WebSocket requests, no localStorage/sessionStorage, no page errors, reduced-motion coverage, server process cleaned up in `finally`.
- Evidence: mobile and desktop session-list, files, preview, and error PNGs plus literal command output under `/opt/data/cliora-mobile-pr/evidence/`; fixtures are never reported as production or UAT proof.

## Stop condition

Stop with only new files under `prototypes/mobile-session/` and `plan/29/`, locally green comprehensive fixture tests, and external `writer-summary.md`. Do not commit, push, open a PR, or claim real service/device/security/UAT completion.
