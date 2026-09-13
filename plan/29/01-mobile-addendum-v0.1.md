# Mobile addendum v0.1 — proposed contract

Status: **Proposed**, not an amendment to VDS 1.0 or ADR 0027 yet.
Scope: responsive presentation and interaction over existing sessions/files/terminal capabilities.
Normative language in this proposal becomes production policy only after M0 approval and the required versioned VDS/ADR decision.

## 1. Information architecture and route contract

### Session list

`/sessions` remains the source list and `frontend/src/views/SessionsView.vue` remains its production owner. The mobile presentation is a compact operational list ordered only by an approved existing server/list property; it must not invent activity ranking. Each row retains name, node, runtime, workspace, status, and available activity metadata. Selecting a row navigates with its existing `SessionDetail.id` to `/sessions/:id`.

The mobile starting route is an M0 product/router decision: changing `/` from the current dashboard redirect would affect desktop and is not silently proposed here. The lowest-risk v0.1 keeps `/sessions` explicit and makes it the primary mobile navigation entry while `/` remains unchanged until approved.

### Selected session

`/sessions/:id` and `frontend/src/views/SessionWorkspaceView.vue` remain the exact-session boundary. The header exposes the route session id (or a safe shortened rendering with the full id accessible), node, runtime, workspace, and separately:

- server session state;
- browser terminal connection state;
- writer/viewer control state;
- privileged/sandbox posture when reported.

The directly visible top-level mobile modes are `terminal` and `files`. A fullscreen preview is an in-route substate of Files, not a new file URL, not a new session, and not a second workspace. This avoids putting a workspace-relative path into browser history or persistent storage. Desktop's existing CLI / preview / conditional system-TERMINAL tabs and desktop theme behavior remain governed by the current VDS; the mobile light treatment does not change them.

### In-memory state shape

One mounted workspace owns one bounded state object:

```text
MobileWorkspaceState {
  sessionId
  mode: terminal | files | preview
  directoryRelPath
  filenameQuery
  directoryScrollTop
  previewRelPath
  previewScroll: LRU<relPath, scrollTop>  // at most 8, matching Monaco model cache
  previewReturnFocusKey
}
```

Only workspace-relative paths are held. Nothing above is written to `localStorage`, `sessionStorage`, analytics, error logs, or a preferences API. Existing display preferences may continue in `localStorage` only because ADR 0027 limits them to non-identifying theme/nav/font-size/panel-width values.

Retention is deliberately bounded to the mounted, exact session and eight preview positions: it gives useful back-navigation without building a browser-side path history. Clear the whole object and abort in-flight work on logout, authentication expiry, 403/capability loss, route session-id change, terminal server state, or unmount. A 403 clears content **before** the denial replaces it. Normal preview → file-list return restores directory, query, nonzero scroll, and focus; Files ↔ Terminal retains the current main CLI connection without remounting it.

## 2. Exact production mapping

| Proposed responsibility | Existing source/route/contract | Required adaptation boundary |
|---|---|---|
| Session-first list | `/sessions`; `views/SessionsView.vue`; `stores/sessions.ts`; `GET /api/sessions` | Responsive list/card presentation; retain server ids/states and distinct empty/no-results states. |
| Exact session detail | `/sessions/:id`; `views/SessionWorkspaceView.vue`; `GET /api/sessions/{id}`; `SessionDetail` | Mobile header and mode state; never substitute/create a session. |
| Terminal owner | `composables/useTerminalSession.ts`; `POST /api/sessions/{id}/attach`; `/ws/sessions/{id}/terminal`; `terminal.resize`, `terminal.control_acquire` | Keep one owner; CSS-hide rather than unmount; fresh ticket per reconnect; no renderer command strings. |
| Main CLI lifecycle | FR-SESSION-006; ADR 0012/0013; existing workspace view | Back/background/unmount detach only. A stop remains an explicit separately authorized confirmation, not part of this prototype. |
| System shell lifecycle | `POST /api/sessions/{id}/shell`; `can_open_shell`; ADR 0021; `SessionWorkspaceView.vue` close/unmount/pagehide/route-id paths | Not exposed in prototype. If later adapted, keep owner-only server capability and terminate child shell on close/leave; never make it durable like main CLI. |
| File session binding | `stores/files.ts::useSession/clearForSession/abortInflight`; `filesSessionId` in workspace view | Exact-session abort/wipe is load-bearing; no late old-session response may land. |
| Folder listing | `FileTree.vue`; `useFileTree.ts`; `GET /api/sessions/{id}/files/tree`; `filesystem-list.schema.json`; `FileTreePage` | Mobile list, up, relative breadcrumb, lazy levels, `truncated` + `next_cursor`; no absolute path. |
| Filename search | `FileSearchBar.vue`; `useFileTree.ts` calls `store.runSearch(keyword)` without `root`; `GET /api/sessions/{id}/files/search`; `filesystem-search.schema.json`; `FileSearchResult` | Whole current session workspace, case-insensitive filename substring only. Show `partial`, `stopped_reason`, `scanned_count`; never imply full text/current folder. |
| Existing read-only preview | async `PreviewPane.vue`; `useMonacoModel.ts`; `PreviewDenied.vue`; `GET /api/sessions/{id}/files/content`; `filesystem-read.schema.json`; `FileContent` | Fullscreen mobile host, text/code only, same denial taxonomy, at most 8 models/positions, content cleared before loading/denial/session switch. Existing production code is not an image viewer. |
| Existing upload | `FileTree.vue`, `FileTreeToolbar.vue`, `useFileUpload`; ADR 0026 | Outside prototype. M3 adapts only when server `can_upload_files` and node posture both allow it; touch picker must remain reachable. No edit/replace/delete. |
| Theme consumers | `theme/tokens.css`, `theme/themes.ts`, `theme.contract.test.ts`, `theme.contrast.test.ts`, xterm and Monaco setup | Approved mobile-only light terminal/editor behavior must update both concrete sources and every mobile consumer/test atomically through the reviewed VDS/ADR version mechanism. Desktop policy remains unchanged. |

## 3. File behavior and denial states

Directory browsing is level-by-level. The daemon remains the final path authority under ADR 0014 (`workspace.Root`/validated handles); the browser only sends the exact session id and workspace-relative path. Directory responses can be partial with an opaque `next_cursor`; the UI offers a real load-more continuation and never labels a truncated level complete.

Search is bounded by results, depth, scanned count, and monotonic timeout. The UI must render these literal outward meanings:

| `stopped_reason` | Required meaning |
|---|---|
| `results` | Result cap reached; only earlier matches are shown. |
| `depth` | Deeper directories were not scanned. |
| `scanned` | Scan-count cap reached; results are incomplete. |
| `timeout` | Search timed out; already-found matches are shown. |

Preview requests are only made after a user activates a file and `can_browse_files` is true. Current supported capability is UTF-8 text/code rendered read-only with line numbers, wrap/find/copy/refresh/goto-line as the platform can support. This proposal adds no preview type. Required distinct denials include:

- `FILE_TOO_LARGE`: show observed size and 2 MiB limit; do not read full content;
- `FILE_BINARY`: show MIME/size/modified time; **images are included here and are not rendered**;
- `reason=unsupported_encoding`: explain text encoding separately from binary;
- `FILE_PERMISSION_DENIED`: daemon execution user cannot read it;
- sensitive/unknown classification: no fragment, absolute path, or secret-bearing filename in audit;
- missing/invalid/outside root: safe outward wording that does not enable path probing;
- transient relay failure: persistent inline error and honest retry;
- empty directory versus zero search matches: separate messages and next actions;
- ended session: no daemon-side browse attempt and no inert retry.

## 4. Responsive and viewport contract

The proposed content breakpoints retain the VDS four ranges and add the issue-specific device matrix:

| Width | Proposed behavior |
|---|---|
| `<768px` | Single-column session/detail/file flow; full-width terminal/files/preview; top navigation; no simultaneous tree + terminal + Monaco. |
| `768–1023px` | Intermediate compact layout; file browser is an accessible overlay/dedicated mode, not hidden. |
| `1024–1439px` | Desktop workbench with collapsed primary navigation and compact work header. |
| `≥1440px` | Existing expanded desktop baseline; mobile changes must not regress it. |

Acceptance widths are 360×844, 390×844, 430×932, 844×390, 768, 1024, 1100, and 1440×900. General UI has no document-level horizontal overflow. Any terminal horizontal browsing is internal and explicit; ANSI layout is never rewritten to fit.

The app shell remains the sole height owner. Use `100dvh` with a `100vh` fallback at the shell, `env(safe-area-inset-*)` on edge padding, and flex/grid `min-height: 0` for inner scrolling. Production M1 listens to `visualViewport` resize/scroll while the virtual keyboard is present and updates a non-persistent usable-height CSS variable; it removes listeners on unmount and must not double-subtract safe areas. Fixed input/toolbar elements are rejected unless real-device evidence shows they remain above the keyboard.

The current `SessionWorkspaceView.vue` has a runtime `<1024` drawer decision followed by a historical `@media (max-width: 1100px) { .workspace-rail { display:none } }`, and `SessionHeader.vue` places posture in a compact disclosure. These are **static findings**, not proven production defects in this PR. M1 first reproduces at 390/768/1000/1023/1024/1100/1101 and checks posture before first input; only then may a separately scoped production repair change them.

## 5. Terminal input, reconnect, and posture

The prototype intentionally has no input. Production M1's isolated IME spike and M2 integration must establish:

- `compositionstart` begins local composition; no partial bytes are sent;
- `compositionend` commits exactly once; a following browser `input` event cannot duplicate it;
- special keys (Esc, Tab, arrows, Ctrl modifiers, Enter, Page Up/Down) preserve native xterm byte semantics; Ctrl+C is labeled as interrupt, never copy;
- input mode and text-selection mode are explicit; long-press selection cannot emit remote input;
- multiline paste shows exact content and line count in a confirmation step; confirmation sends exactly those bytes, with **no appended Enter**;
- cancel sends nothing; disconnected/viewer state disables sending; there is no offline queue or later replay;
- ordinary single-line paste stays native unless risk evidence supports a narrower interception;
- clipboard file handling remains the existing capture-phase, files-present-only image-drop path and does not break text paste.

Browser connection, server session, and control role are independent. Disconnect keeps visible output marked stale and disables input. Every reconnect mints a fresh single-use ticket through `POST /api/sessions/{id}/attach`, rechecks authorization/capabilities, then re-enables input only after the server assigns writer. Snapshot truncation/gap is visible. No session replacement or automatic command replay occurs.

One writer/many viewers, explicit `terminal.control_acquire`, server-authoritative takeover, and writer-only resize remain unchanged. A hidden terminal is not fit; after it becomes visible, fit reads the real container, clamps rows 2–300 and columns 2–500, and sends only a changed valid size. Multi-device orientation/posture conflicts use the current server contract or require a fresh ADR; mobile never assumes simultaneous independent PTY sizing is safe.

Node privileged and Codex sandbox-bypass posture stays visible before typing. Compact layout may shorten wording but cannot place it only behind a disclosure. The platform still names runtime id, never a shell command/binary/argv/environment/entrypoint.

## 6. Mobile-only light terminal/editor contract

The product direction is already settled by #62: mobile xterm, preview, toolbar, denial, warning, and error surfaces stay light. OS dark preference **must not** flip the mobile workspace to dark. This applies to mobile presentation only; desktop retains its current theme policy and current dark xterm/Monaco behavior. M0 must not reopen those decisions.

Current ADR 0027 and VDS §18/§19 do not yet encode this mobile-only exception. The remaining review is strictly the versioned mechanism: a mobile addendum and the appropriate VDS/ADR contract change. The behavior must not be smuggled in as component CSS or broadened into a desktop theme-policy change.

After that mechanism is approved, the theme owner updates `frontend/src/theme/tokens.css` and `frontend/src/theme/themes.ts` together with explicitly mobile-scoped selection; `theme.contract.test.ts` proves exact key/value parity and desktop regression tests prove existing desktop selection is unchanged. Component-derived contrast tests cover page/terminal/editor text, dim text, selection, cursor and cursor accent, control borders, focus, warning/error/success states, and read-only/denial metadata. A simulated OS dark preference must still produce the approved light mobile values.

Real xterm/Monaco validation must cover ANSI 16 normal/bright colors, selection, cursor, dim text, warning/error output, reverse video, explicit background colors, and representative real Claude/Codex/tmux/`ls`/Git truecolor output. Truecolor emitted by the CLI may remain visually imperfect; bytes and ANSI semantics are never changed. CSS `filter`/`invert`, canvas inversion, output recoloring, or PTY-byte rewriting are forbidden. Theme application changes colors in place; it does not remount xterm/Monaco, reconnect, move scroll, lose pending input, or alter authorization.

## 7. Authentication, paths, security, and retention

- HTTP and WebSocket authorization remain server-side. UI hiding is only an affordance.
- Reconnect tickets stay short-lived, single-use, user/resource-bound, and absent from persistent/browser logs.
- All file operations re-authorize exact session and `file.browse`; the daemon repeats canonical root/symlink/handle validation on each operation.
- Client state contains only workspace-relative paths and is cleared on logout, 403, session switch, expiry, terminal session state, or view disposal.
- Terminal bytes and file content never enter analytics, screenshots used as production evidence, exceptions, or logs. Fixture screenshots contain synthetic data only.
- Preview remains read-only for all roles. Viewer gains no terminal or upload right from responsive layout.
- Existing upload's W1–W4, server capability + node veto, quotas/free-space, audit, and never-overwrite rules remain unchanged when adapted. This prototype adds no write surface.
- External security issues #47/#56/#57/#58/#59 require current disposition and verification at M4; a mobile shell cannot repair backend authorization.

## 8. Explicit non-goals

No production code in this PR; no native app/PWA offline mode/push; no chat, approval inbox, agent-event parsing, summaries, shell command builder, session creation/stop fixture, system-shell control, editor, rename, delete, download, SFTP, full-text search, image/PDF/archive preview, arbitrary path, remote font/asset, or new dependency.
