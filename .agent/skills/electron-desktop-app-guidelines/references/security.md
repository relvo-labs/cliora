# Electron Security Reference

Use this reference when a task involves BrowserWindow settings, preload exposure, navigation, external URLs, permissions, filesystem access, or renderer isolation.

## Security Baseline

Default to:

```ts
webPreferences: {
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  preload: preloadPath,
}
```

Do not weaken these settings for convenience. If a user asks to enable `nodeIntegration`, explain the risk and propose a preload-based alternative.

## Renderer Trust Model

Treat renderer code as less trusted because it processes UI state, user input, local content, and sometimes remote or semi-trusted content. Do not allow renderer code to directly access privileged APIs.

Forbidden renderer patterns:

```ts
import { ipcRenderer } from 'electron'
import fs from 'node:fs'
import childProcess from 'node:child_process'
```

Forbidden preload patterns:

```ts
contextBridge.exposeInMainWorld('electron', electron)
contextBridge.exposeInMainWorld('fs', fs)
contextBridge.exposeInMainWorld('ipcRenderer', ipcRenderer)
```

## Preload Exposure Rules

Expose intent-based methods, not infrastructure.

Bad:

```ts
send: (channel: string, payload: unknown) => ipcRenderer.invoke(channel, payload)
```

Good:

```ts
settings: {
  get: () => ipcRenderer.invoke('settings:get'),
  update: (input: UpdateSettingsInput) => ipcRenderer.invoke('settings:update', input),
}
```

Keep preload code small. It should adapt renderer calls to approved IPC channels, not contain business logic.

## Navigation Protection

For each BrowserWindow:

- Prevent unexpected in-app navigation.
- Deny new windows by default.
- Allow external links only through validation and explicit allowlists.

Example:

```ts
mainWindow.webContents.setWindowOpenHandler(({ url }) => {
  if (isAllowedExternalUrl(url)) {
    shell.openExternal(url)
  }
  return { action: 'deny' }
})
```

Do not blindly call `shell.openExternal(url)` with renderer-provided values.

## File Access

Renderer must never receive unrestricted file APIs. Main process should constrain file access to approved directories, such as `app.getPath('userData')`, or to files selected by the user through native dialogs.

Validate:

- path is absolute or resolved safely
- path is inside an allowed base directory when required
- extension and MIME type match expected use
- file size is acceptable
- symlink behavior is understood

## Shell and Process Execution

Avoid shell execution. If absolutely required:

- keep command names fixed in main process
- pass arguments as arrays rather than shell strings
- validate every argument
- never accept complete commands from renderer
- log failures safely

Prefer `execFile` or `spawn` with fixed executable paths over shell-based execution.

## Content Security Policy

Recommend a strict CSP for renderer HTML. Avoid `unsafe-eval` and remote script sources unless there is a documented reason.

For Vite/React development, distinguish development relaxations from production security. Production CSP should be stricter than development CSP.

## Permissions

Use explicit permission handling for media, notifications, geolocation, and other sensitive capabilities. Deny by default and allow only what the app truly needs.

