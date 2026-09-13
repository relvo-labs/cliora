# Cliora mobile session prototype

One integrated, fixture-only prototype for the selected **light A / session-first** direction with C's required file browsing folded into the same selected session. It is not a second product, a production Vue implementation, or service evidence.

## Run

From the repository root:

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory prototypes/mobile-session
```

Then open `http://127.0.0.1:8080/`. Stop the server with Ctrl+C.

## Test and capture evidence

The test command starts and stops its own task-owned local HTTP server and writes logs/screenshots only to the supplied external directory:

```sh
/opt/data/cliora-mobile-study/venv/bin/python prototypes/mobile-session/test_prototype.py \
  --chromium /opt/hermes/.playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell \
  --evidence-dir /opt/data/cliora-mobile-pr/evidence/mobile-session
```

## Scope

- Exact selected-session context, directly visible Terminal/Files switch, nested folder navigation, up/breadcrumb controls, and filename-substring search across the whole selected session workspace.
- Fullscreen read-only TEXT/CODE preview with real list/preview scroll restoration, focus return, Escape, and session-switch wipe.
- Explicit synthetic states: normal, empty folder, 403, transient failure/retry, unsupported binary/image, too-large, ended session, and all four bounded-search stop reasons.
- Every state and output is synthetic and held only in JavaScript memory. Refresh resets it. No localStorage/sessionStorage, network API, PTY, WebSocket, shell, command execution, or remote asset exists.
- Preview matches the current capability boundary: text/code only. Images, archives, and other binary content are explicitly refused; this prototype is not an image viewer.
- No create/stop/session-shell/input/upload/edit/rename/delete/download controls. Existing production upload remains outside this prototype; editing/rename/delete remain decided against and download remains unbuilt.

The light terminal and code surface are a design proposal. Current production Porcelain still uses dark xterm/Monaco surfaces; adoption requires a versioned VDS/ADR 0027 decision and matching `tokens.css`/`themes.ts` contract and real CLI color validation.
