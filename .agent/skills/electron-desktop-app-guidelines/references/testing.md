# Electron Testing Reference

Use this reference when the task involves test strategy, Playwright Electron tests, IPC handler tests, preload tests, or production smoke tests.

## Test Levels

Use at least three levels when practical:

1. Unit tests for shared utilities, schemas, and service logic.
2. Main-process tests for IPC handlers and desktop services.
3. End-to-end tests for real desktop flows.

## Unit Tests

Test pure logic in `src/shared` and service modules without launching Electron where possible.

Good candidates:

- schema validation
- path validation
- config migration
- serialization
- updater state mapping
- permission decision logic

## IPC Handler Tests

Keep IPC handlers thin so they can be tested by calling handler functions directly. Extract handler implementation from registration when needed.

Pattern:

```ts
export function createSettingsHandlers(deps: Deps) {
  return {
    getSettings: async () => deps.settingsService.get(),
    updateSettings: async (input: unknown) => {
      const parsed = UpdateSettingsSchema.parse(input)
      return deps.settingsService.update(parsed)
    },
  }
}
```

Then register separately:

```ts
const handlers = createSettingsHandlers(deps)
ipcMain.handle('settings:get', handlers.getSettings)
ipcMain.handle('settings:update', (_event, input) => handlers.updateSettings(input))
```

## Preload Tests

Verify that preload exposes only approved APIs. The renderer should not see raw `ipcRenderer`, `fs`, `path`, `child_process`, or `electron`.

## End-to-End Tests

Use Playwright Electron or an equivalent tool when appropriate.

Important flows:

- app launches
- main window appears
- renderer calls a preload API
- invalid IPC input fails safely
- file dialog flow works or is mocked
- settings persist after restart
- app quits cleanly
- app focuses existing window on second launch
- renderer cannot access Node.js APIs

## Production Smoke Tests

Test packaged builds separately from development builds. Many Electron issues only appear after packaging because paths, preload files, native modules, and asset locations change.

Smoke test checklist:

- installed app launches
- preload is loaded
- core IPC works
- app can read/write user data
- external links are handled safely
- logs are created
- updater does not crash when offline

