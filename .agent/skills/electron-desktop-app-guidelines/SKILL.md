---
name: electron-desktop-app-guidelines
description: >-
  Apply secure Electron main, preload, renderer, IPC, packaging, and production patterns. Use only for explicit Electron desktop application work; do not trigger merely because Cliora uses xterm.js or Monaco in its browser frontend.
---

> Electron desktop application engineering standards: architecture, security, IPC, and packaging.

## Overview

Apply this skill whenever working on an ElectronJS desktop application or adapting an existing web application into an Electron desktop app.

## When to Use

Use when reviewing, designing, refactoring, testing, or generating code for Electron applications, especially when the task involves main process, renderer process, preload, IPC communication, filesystem access, OS integration, application lifecycle, web-to-desktop migration, installers, updater, or production hardening.

**Not for:**
- Node/Turborepo monorepo build workflows → `turborepo-node-workflow`
- Browser-based web app testing → `webapp-testing`

## Workflow

For Electron-related tasks, structure the answer as:

1. Identify the desktop-specific risk or architectural concern.
2. Recommend the secure Electron pattern.
3. Provide TypeScript-oriented examples when code is useful.
4. Give migration or refactor steps when changing existing web code.

Avoid generic web-only advice when the task clearly involves Electron.

## Non-Negotiable Principles

Treat Electron as a desktop application platform, not a browser wrapper.

Keep responsibilities separated:

- Main process: app lifecycle, native APIs, BrowserWindow creation, menus, tray, updater, filesystem, OS integration, permissions, global shortcuts, and secure IPC handlers.
- Preload layer: narrow, typed, validated bridge between renderer and main process.
- Renderer process: UI and browser-safe logic only.
- Shared code: pure types, constants, validation schemas, and framework-independent utilities.

Assume renderer code is less trusted than main process code. Never give renderer unrestricted access to Node.js, Electron internals, shell commands, arbitrary IPC, or filesystem APIs.

## Required BrowserWindow Baseline

Prefer this security baseline unless the user gives a strong reason otherwise:

```ts
webPreferences: {
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  preload: preloadPath,
}
```

Do not enable `nodeIntegration` for convenience. Do not disable `contextIsolation`. Do not expose raw `ipcRenderer`, `electron`, `fs`, `path`, `child_process`, or `shell` to renderer code.

## Preferred Project Structure

Recommend this structure for new or reorganized Electron apps:

```txt
src/
├── main/
│   ├── index.ts
│   ├── app-lifecycle.ts
│   ├── windows/
│   ├── ipc/
│   ├── services/
│   ├── updater/
│   └── security/
├── preload/
│   ├── index.ts
│   └── desktop-api.ts
├── renderer/
│   ├── app/
│   ├── components/
│   ├── hooks/
│   └── styles/
└── shared/
    ├── types/
    ├── constants/
    ├── schemas/
    └── utils/
```

Use existing project conventions when they are already clean, but preserve the process boundaries above.

## IPC Rules

Use `ipcMain.handle` and `ipcRenderer.invoke` for request-response operations. Use explicit event subscriptions only for streaming or status updates.

Channel naming convention:

```txt
domain:action
```

Examples:

```txt
app:get-version
dialog:select-file
settings:get
settings:update
filesystem:read-config
updater:check
```

Validate every IPC input in the main process. Prefer schemas in `src/shared/schemas/`. Never allow renderer to choose arbitrary file paths, URLs, shell commands, or IPC channel names without validation and allowlisting.

Prefer a typed renderer API:

```ts
window.desktopApi.settings.get()
```

Avoid renderer imports like:

```ts
import { ipcRenderer } from 'electron'
```

## Secure Preload Pattern

Expose only minimal APIs through `contextBridge`.

Bad:

```ts
contextBridge.exposeInMainWorld('electron', electron)
contextBridge.exposeInMainWorld('ipcRenderer', ipcRenderer)
```

Good:

```ts
contextBridge.exposeInMainWorld('desktopApi', {
  app: {
    getVersion: () => ipcRenderer.invoke('app:get-version'),
  },
  dialog: {
    selectFile: () => ipcRenderer.invoke('dialog:select-file'),
  },
})
```

When generating preload code, also generate renderer-side TypeScript declarations for `window.desktopApi`.

## Web-to-Desktop Migration Rules

When adapting an existing web app:

1. Reuse UI components where possible.
2. Keep browser-safe UI logic in renderer.
3. Move filesystem, local database, tray, menu, updater, notifications, system permissions, and OS integrations into main-process services.
4. Replace direct web assumptions with a desktop API abstraction.
5. Do not couple React components directly to raw IPC channels.
6. Preserve a clean path to run the renderer as a web app if the product still needs both web and desktop builds.

## Local Data Rules

Use Electron app paths for mutable runtime data:

```ts
app.getPath('userData')
```

Do not write runtime data into the packaged application directory. Separate config, logs, cache, and database files. Version and migrate local data schemas.

## Navigation and External URLs

Prevent untrusted navigation. Use explicit allowlists for external URLs. Use `setWindowOpenHandler` and validate before calling `shell.openExternal`. Avoid loading remote content in privileged windows.

## Production Readiness Checklist

Before considering an Electron app production-ready, check:

- `contextIsolation` is enabled.
- `nodeIntegration` is disabled.
- preload exposes a minimal typed API.
- IPC inputs are validated in main process.
- file paths are constrained to approved directories.
- external links are allowlisted.
- app lifecycle works on Windows, macOS, and Linux as required.
- dev server assumptions are removed from production builds.
- installer, app id, icons, code signing, notarization, updater, logs, crash handling, and source-map policy are handled.

## References

- [Security](references/security.md) — BrowserWindow hardening, preload exposure, navigation, shell, permissions, and CSP.
- [IPC Patterns](references/ipc-patterns.md) — Typed IPC, channel naming, validation, event streams, and error handling.
- [Architecture](references/architecture.md) — Folder structure, process boundaries, service patterns, and web-to-desktop migration.
- [Packaging](references/packaging.md) — Build, installer, code signing, auto update, environment handling, and production checks.
- [Testing](references/testing.md) — Unit, main-process, preload, and Electron end-to-end testing patterns.

## Related Skills

- `turborepo-node-workflow` — Node/Turborepo monorepo build and execution environment (complements).
- `webapp-testing` — Playwright-based web app testing (complements).
