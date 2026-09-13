# Cliora mobile session prototype and rollout plan

Version: **mobile addendum v0.1 (Proposed)**  
Baseline: `26f4178c7c11e19356c4bafdde0094e17c6cab65`  
Decision sources: #62 selected direction, #61 shared engineering gates, #64 file-mode reference, #67 decision index.

This plan turns the selected **light A / Pocket Workbench** direction into one integrated prototype: session list → exact selected session → directly visible Terminal/Files switch → folder browsing, whole-workspace filename search, and fullscreen read-only TEXT/CODE preview. C contributes the file interaction; it is not a second home page or a parallel product.

The executable artifact is [`prototypes/mobile-session/`](../../prototypes/mobile-session/README.md). It is deliberately independent of production Vue and makes no API/PTY/WebSocket request. All data and transitions are labeled fixtures held in memory.

## Decisions carried forward

1. Responsive web first; no native app, push, offline CLI, or background WebSocket promise.
2. Mobile is session-first and entirely light: near-white canvas, white surfaces, deep text, blue accent, plus light terminal and preview. The latter two are **new proposals**, not current Porcelain token behavior.
3. Session identity never becomes implicit: session id, node, runtime, and workspace remain visible. `/sessions/:id` continues to identify the exact server session.
4. Terminal and Files are direct peers in the selected session. Opening Files or preview never starts a session, sends terminal bytes, or changes the writer.
5. Filename substring search covers the **whole current session workspace**. It is not full-text search and is not silently limited to the current folder. The UI exposes partial stop reason and scanned count.
6. Preview supports current read-only text/code capability only. Image, PDF, archive, binary, unsupported encoding, sensitive, permission-denied, missing, and oversized content remain refusal states. Existing `PreviewPane.vue` is not an image viewer.
7. Editing, rename, and delete remain decided against. Download is unbuilt and excluded. Existing upload is already a production capability but is outside this prototype and needs its own mobile adaptation in M3.
8. Closing/leaving the main CLI view means detach and must not stop it. A system `TERMINAL` is a separate child shell that is terminated on close/leave/route-id change/pagehide and is not exposed as a fixture control here.
9. No session creation, stop, shell, command-send, chat, approval, agent-semantic, or fake reconnect control appears in the prototype. Small scope is preferred to an inert success message.

## Deliverables

- [`00-execution-plan.md`](00-execution-plan.md): design read, causal receipts, scope, and implementation sequence.
- [`01-mobile-addendum-v0.1.md`](01-mobile-addendum-v0.1.md): proposed versioned route, state, component, terminal/input, responsive, security, and theme contract.
- [`02-rollout-and-verification.md`](02-rollout-and-verification.md): phased DAG, ownership, acceptance IDs, evidence classification, UAT gates, staged rollout, kill switch, and rollback.
- [`prototypes/mobile-session/index.html`](../../prototypes/mobile-session/index.html), `style.css`, `app.js`: integrated interactive static prototype.
- [`prototypes/mobile-session/test_prototype.py`](../../prototypes/mobile-session/test_prototype.py): local-HTTP Playwright behavior, viewport, touch, overflow, keyboard, and screenshot test.

## Prototype result, not production status

Fixture acceptance `MSP-F-*` is green as recorded in `02-rollout-and-verification.md`. Every `MSP-R-*` gate remains pending because this PR does not touch production or use a real Central, daemon, xterm, Monaco, device keyboard, authorization service, or node. A fixture can prove the proposed interaction is coherent; it cannot prove production reconnection, path confinement, RBAC, ANSI rendering, IME, real-device layout, or security posture.

## Shortest local commands

View:

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory prototypes/mobile-session
```

Test and capture external evidence (the script owns and cleans up its HTTP server):

```sh
/opt/data/cliora-mobile-study/venv/bin/python prototypes/mobile-session/test_prototype.py --chromium /opt/hermes/.playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell --evidence-dir /opt/data/cliora-mobile-pr/evidence/mobile-session-writer
```

The coordinator opens the Draft PR and requests a fresh independent review. This writer does not commit, push, or perform GitHub writes.
