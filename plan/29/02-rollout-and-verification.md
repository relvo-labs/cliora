# Rollout, ownership, and verification

## 1. Phased DAG

```text
M0 decisions + versioned contracts
  └─> M1 mobile shell/navigation/list
        ├─> independent IME/input spike
        └──────────────┬───────────────┘
                       v
                 M2 real xterm integration
                       v
                 M3 file adaptation
                       v
                 M3 remaining navigation
                       v
                 M4 devices/security/UAT
                       v
                 staged production rollout
```

### M0 — decisions before code

Approve mobile addendum version/status, `/` versus `/sessions` mobile entry behavior, in-route mode state, light-terminal VDS/ADR 0027 policy, exact capability wording, data retention, analytics exclusions, release flag ownership, and acceptance IDs. Reproduce and record the 1024/1100 drawer and compact-posture findings before declaring defects. No estimates are invented.

### M1 — shell plus isolated input spike

Implement responsive AppLayout/PrimaryNav/SessionsView/session header and mode shell without reconnect or file behavior changes. In parallel, an independent device spike exercises xterm input, Chinese IME, special keys, selection, multiline paste, visualViewport, safe area, backgrounding, and rotation against a disposable non-production node. The spike does not edit the shared mobile shell files and its code is not merged by default.

### M2 — real xterm

Only after M1 layout and spike evidence pass: integrate the existing `useTerminalSession` owner; keep the host mounted; enforce writer/viewer, fresh-ticket reconnect, gap/stale state, resize bounds, theme-in-place, and detach lifecycle. Any wire-shape change stops the phase for a separately reviewed contract/ADR update across browser, Central, and daemon.

### M3 — file adaptation, then remaining navigation

Adapt `FileTree`/`FileSearchBar`/`PreviewPane` to the dedicated mobile flow, preserving `stores/files.ts` abort/wipe, partial cursor/search metadata, exact-session capability gates, denial clearing, and Monaco LRU disposal. After file acceptance, adapt existing upload with its unchanged security contract, then verify discoverable node/tunnel/enrollment/audit/integration/preferences routes by role. This sequencing prevents navigation and file writers from touching the same session shell concurrently.

### M4 — real devices, security, and UAT

Run real iOS Safari and Android Chrome, real services/node/CLI, role/ticket/network/background/orientation tests, security issue disposition checks, accessibility review, desktop regression, and independent code/security review. User UAT occurs only after these gates. Prototype screenshots are not accepted as substitutes.

## 2. Named role and write-set ownership

One native implementation writer owns each production write set at a time. “Independent” means separate evidence or non-overlapping files, not concurrent edits to shared sources.

| Role | Exclusive write set | Boundary |
|---|---|---|
| M0 product/VDS owner | versioned mobile addendum, approved `research/style.md` revision, new/amended ADR, requirement/traceability updates | Decides policy; no Vue behavior edits. |
| M1 shell writer | `AppLayout.vue`, `PrimaryNav.vue`, `SessionsView.vue`, `SessionHeader.vue`, route presentation tests | Does not touch terminal/file composables or wire contracts. |
| IME spike owner | external evidence and a disposable isolated spike directory only | No shared frontend source; reports events/bytes/device versions, never production completion. |
| M2 terminal writer | `SessionWorkspaceView.vue`, `useTerminalSession.ts`, dedicated mobile input components/tests | Sole owner of xterm/socket/resize during M2; no file-store edits. |
| Theme owner | `theme/tokens.css`, `theme/themes.ts`, Monaco theme setup, theme contract/contrast/real-render tests | Starts only after M0 VDS/ADR approval; no socket/lifecycle edits. Coordinate sequentially with M2 where the workspace view overlaps. |
| M3 file writer | `FileTree*`, `FileSearchBar.vue`, `PreviewPane.vue`, `PreviewDenied.vue`, `useFileTree.ts`, `useMonacoModel.ts`, `stores/files.ts`, file E2E | No terminal transport or shell lifecycle edits. |
| M3 navigation writer | remaining existing route/nav components after the file writer merges | No file/terminal internals; server capabilities remain authoritative. |
| M4 QA/security reviewers | external evidence and review findings | Read-only against implementation; fixes return to the owning writer. |
| Release owner | rollout flag/config and runbook/release note after all gates | Cannot broaden RBAC, stop sessions, or waive security/UAT gates. |

If a needed edit crosses write sets, stop and transfer ownership or serialize the change. No two writers patch `SessionWorkspaceView.vue`, theme consumers, or a shared test in parallel.

## 3. Acceptance ledger

### Fixture proof completed by this PR

| ID | Acceptance | Evidence |
|---|---|---|
| `MSP-F-001` | Session-first list opens exact selected synthetic id and shows session/node/runtime/workspace. | Playwright interaction; mobile/desktop session-primary PNGs. |
| `MSP-F-002` | Terminal/Files switch is directly visible; terminal is bright, read-only synthetic stdout with correct CLI-vs-shell lifecycle wording. | Keyboard tab switch and screenshot. |
| `MSP-F-003` | Browse nested folder, up, and relative breadcrumb. | Real click assertions. |
| `MSP-F-004` | Search from `src` finds `docs/mobile-guide.md`, proving fixture behavior is whole-workspace filename substring rather than current-folder/full text. | Submit/Escape assertions and explicit scope label. |
| `MSP-F-005` | Preview is fullscreen read-only TEXT/CODE; returning restores folder/query, actual nonzero file-list scroll, prior preview scroll, and triggering control focus; Escape works. | DOM scroll values >0 and `activeElement` assertion. |
| `MSP-F-006` | Session switch during preview or 403 clears old content, path, query, denial, preview, and scroll. | Cross-session assertions. |
| `MSP-F-007` | Normal, empty folder, 403, transient failure/honest retry, unsupported image/binary, too-large, and ended-session fixtures are explicit. | State transitions and copy assertions. |
| `MSP-F-008` | `results`, `depth`, `scanned`, and `timeout` partial search reasons plus scanned count are visible. | Four fixture assertions. |
| `MSP-F-009` | 360×844, 390×844, 430×932, 844×390, 768×844, 1024×768, 1100×800, 1440×900 have no document overflow; every visible button/input/select is at least 44×44. | Browser geometry checks. |
| `MSP-F-010` | Keyboard session activation, tab arrow navigation, search Escape, preview Escape/focus return, and reduced-motion mode work without JS errors. | Playwright keyboard/media/pageerror checks. |
| `MSP-F-011` | No persistent browser storage and no external request/WebSocket. | Runtime storage/request assertions; local HTTP only. |
| `MSP-F-012` | Mobile and desktop session-primary/files/preview/error images are external to Git. | Eight PNG paths under the requested evidence directory. |

These IDs prove only fixture behavior. They do not satisfy a production requirement merely because the shape resembles it.

### Pending real-service/device proof

| ID | Gate | Required evidence |
|---|---|---|
| `MSP-R-001` | Production route/list/detail integration | Real API ids/states/capabilities; direct URL/reload/back; no substitute session. |
| `MSP-R-002` | Main CLI detach/reconnect | Close/background/network transition; same tmux session; fresh ticket; stale/gap state; no replay. |
| `MSP-R-003` | System shell lifecycle | Owner-only open/attach; close/unmount/route-id/pagehide termination; parent/idle cleanup; no inherited abandoned shell. |
| `MSP-R-004` | Writer/viewer/takeover/resize | Two users and two devices; exactly one writer; explicit acquire; valid 2–300×2–500 resize; orientation/posture behavior. |
| `MSP-R-005` | IME/special keys/paste | iOS and Android event+byte traces for Traditional Chinese composition, Esc/Tab/arrows/Ctrl/Enter, selection mode, multiline confirmation, no autoEnter/no duplicate/offline replay. |
| `MSP-R-006` | File list/search contracts | Real current workspace; lazy levels; next cursor; every stop reason; abort of old request; no absolute/cross-session path. |
| `MSP-R-007` | Preview and denials | Real Monaco/read endpoint; UTF-8/ANSI text corpus, non-UTF-8, NUL/binary/image, size, sensitive, symlink/path, permission, missing, 403, ended session; stale content cleared first. |
| `MSP-R-008` | Auth/session expiry | Access expiry, 403/capability loss, ws-ticket expiry/replay, logout; memory/cache/content wiped and server refusal preserved. |
| `MSP-R-009` | Entirely light theme | Approved VDS/ADR version; CSS↔TS contract; component contrast; xterm/Monaco ANSI16/cursor/selection/dim/warning/error/reverse/truecolor with real CLIs; no remount/byte rewrite. |
| `MSP-R-010` | Viewport/keyboard/accessibility | Real iOS Safari and Android Chrome versions; safe areas, dvh/visualViewport keyboard open/close, rotation, 200% text, VoiceOver/TalkBack, touch, focus; 768/1024/1100/1440 desktop checks. |
| `MSP-R-011` | Network/background recovery | Wi-Fi↔cellular, offline, background 60s+, ticket refresh, node offline/return, output burst/backpressure; no command replay. |
| `MSP-R-012` | Security and desktop release gate | #47/#56/#57/#58/#59 current disposition/evidence, RBAC/path/audit/log-redaction tests, current desktop suite/layout gates, fresh independent security/code review, user UAT. |

## 4. Local evidence command and literal result

Command run from the repository root:

```sh
/opt/data/cliora-mobile-study/venv/bin/python -m py_compile prototypes/mobile-session/test_prototype.py
/opt/data/cliora-mobile-study/venv/bin/python prototypes/mobile-session/test_prototype.py --chromium /opt/hermes/.playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell --evidence-dir /opt/data/cliora-mobile-pr/evidence/mobile-session-writer
```

Literal result:

```text
PASS session-first list renders
PASS exact session and synthetic terminal contract
PASS folder browse, up, and breadcrumb
PASS whole-workspace filename substring search
PASS preview/list scroll restoration, focus return, and Escape
PASS session switch wipes preview, path, search, and scroll state
PASS session switch while 403 clears denial state
PASS failure retry, empty folder, and ended-session states
PASS binary/image refusal and too-large denial
PASS all bounded-search stop reasons are visible
PASS keyboard session activation
PASS no persistent browser storage
PASS 8 responsive sizes have no document overflow and visible controls are >=44px
PASS 8 external screenshots captured
PASS reduced-motion browser mode active
PASS no external requests, WebSocket traffic, or JavaScript page errors
RESULT PASS (16 checks)
```

Generated evidence is outside Git at `/opt/data/cliora-mobile-pr/evidence/mobile-session-writer/`: `prototype-test-results.json`, `browser-console.log`, and eight PNGs under `screenshots/`. The browser log is empty because no console message/error occurred.

## 5. M4 UAT and security matrix

Record real device/browser/OS versions and distinguish device results from emulation. At minimum:

- current iPhone Safari and Android Chrome physical devices, portrait/landscape, safe-area devices, software keyboard open/closed, Traditional Chinese IME, VoiceOver/TalkBack;
- 360/390/430 widths, 844×390 landscape, 768/1024/1100 transition widths, and 1440×900 desktop regression;
- Admin/Developer/Viewer, owner/non-owner, `file.browse`, `file.upload`, `terminal.operate`, `terminal.shell`, node veto, privileged and non-privileged nodes;
- access expiry, fresh/replayed/expired ws-ticket, logout, 403, node offline, background ≥60 seconds, Wi-Fi/cellular switch, socket gap/output burst;
- two devices alternately viewing/controlling the same managed session; takeover exactly once; resize/posture observation; no new/substitute session and no replayed input;
- normal/empty/no-result/partial cursor/partial search/permission/sensitive/binary/image/unsupported-encoding/too-large/missing/changed-to-denied preview paths;
- main CLI detach survival versus child-shell termination; explicit stop confirmation only in production where already authorized;
- terminal/file content absent from analytics, crash reports, console/network logs, screenshot automation, and ticket/query logging;
- current disposition and verification artifacts for security issues #47, #56, #57, #58, #59;
- all existing frontend unit/E2E/theme/layout/security gates and fresh independent review.

UAT cannot be marked complete from Chromium viewport screenshots. A production claim requires the real service and device evidence above.

## 6. Staged rollout, kill switch, and rollback

The future implementation is reversible presentation work behind a server/deployment-controlled mobile-IA flag with default off. The flag selects only responsive navigation/presentation after authentication; it does not grant capabilities, change endpoints, mint tickets, alter RBAC, or change node posture.

1. Internal non-production cohort: disposable nodes and synthetic/non-sensitive workspaces; gather M2/M3 evidence.
2. Staff opt-in: supported mobile browsers, server-observed errors/latency only, never terminal/file content.
3. Small production cohort after `MSP-R-001`–`012` and independent review.
4. Broader rollout only with stable evidence and recorded UAT acceptance.

Kill switch behavior: stop serving the new mobile presentation on the next navigation/reload and return to the existing responsive UI. It may detach browser terminal connections in the same way a normal navigation does; it **must not** stop a main CLI session, terminate another user's session, create a replacement, broaden a viewer, or replay input. If a system child shell is open, existing bounded-lifecycle cleanup still applies—rollback does not weaken it or invent a keepalive.

Rollback removes/turns off presentation code and its light-theme extension while retaining compatible server contracts. No data migration should be necessary because mobile paths/positions are memory-only and there is no mobile preferences API. If a future phase changes a wire schema, it needs a separately reversible compatibility window; this plan does not pre-authorize one.

The release owner records the flag state and rollback reason without identifiers, paths, terminal bytes, or file content. A rollback is not authority to stop sessions or bypass unresolved security gates.
