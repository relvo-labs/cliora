# IPC Patterns Reference

Use this reference when designing or reviewing Electron IPC, preload APIs, event streams, validation, or renderer-to-main communication.

## Channel Naming

Use:

```txt
domain:action
```

Examples:

```txt
app:get-version
settings:get
settings:update
dialog:select-file
updater:check
updater:install
logs:open-folder
```

Keep channel names constant and centralized.

```ts
export const IPC_CHANNELS = {
  settingsGet: 'settings:get',
  settingsUpdate: 'settings:update',
} as const
```

## Request-Response Pattern

Use `ipcMain.handle` in main and `ipcRenderer.invoke` in preload.

```ts
ipcMain.handle('settings:get', async () => {
  return settingsService.get()
})
```

```ts
contextBridge.exposeInMainWorld('desktopApi', {
  settings: {
    get: () => ipcRenderer.invoke('settings:get'),
  },
})
```

## Validation Pattern

Validate in the main process even if renderer already validates.

```ts
ipcMain.handle('settings:update', async (_event, input) => {
  const parsed = UpdateSettingsSchema.parse(input)
  return settingsService.update(parsed)
})
```

Prefer schema validators such as Zod for runtime validation when the project already uses or accepts that dependency.

## Error Pattern

Do not leak internal stack traces to renderer. Convert errors into stable application-level errors.

```ts
ipcMain.handle('settings:update', async (_event, input) => {
  try {
    const parsed = UpdateSettingsSchema.parse(input)
    return { ok: true, data: await settingsService.update(parsed) }
  } catch (error) {
    logger.error(error)
    return { ok: false, error: { code: 'SETTINGS_UPDATE_FAILED' } }
  }
})
```

## Event Stream Pattern

Use event streams only for ongoing status updates, such as updater progress, long-running tasks, logs, or device state.

Expose subscribe/unsubscribe methods from preload:

```ts
onUpdaterStatus: (callback: (status: UpdaterStatus) => void) => {
  const listener = (_event: Electron.IpcRendererEvent, status: UpdaterStatus) => callback(status)
  ipcRenderer.on('updater:status', listener)
  return () => ipcRenderer.removeListener('updater:status', listener)
}
```

Always return an unsubscribe function to avoid leaks.

## Avoid Arbitrary IPC Bridges

Do not expose generic wrappers:

```ts
invoke(channel: string, payload: unknown) {
  return ipcRenderer.invoke(channel, payload)
}
```

This destroys the security boundary and makes review difficult.

## IPC File Dialog Pattern

Renderer asks for intent, main process owns native dialog configuration.

```ts
ipcMain.handle('dialog:select-config-file', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'JSON', extensions: ['json'] }],
  })

  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})
```

Do not let renderer pass arbitrary dialog filters unless the filters are validated against an allowlist.

