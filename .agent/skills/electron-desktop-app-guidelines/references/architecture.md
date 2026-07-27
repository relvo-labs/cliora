# Electron Architecture Reference

Use this reference when the task involves folder structure, process boundaries, service design, window management, or adapting a web app to Electron.

## Process Boundaries

Main process owns privileged desktop capabilities. Renderer owns UI. Preload bridges the two.

Never import main-process services into renderer code. Never import renderer components into main process code. Shared code must be browser-safe and side-effect-light.

## Recommended Structure

```txt
src/
├── main/
│   ├── index.ts
│   ├── app-lifecycle.ts
│   ├── windows/
│   ├── ipc/
│   ├── services/
│   ├── updater/
│   ├── menu/
│   ├── tray/
│   └── security/
├── preload/
│   ├── index.ts
│   └── desktop-api.ts
├── renderer/
│   ├── app/
│   ├── components/
│   ├── hooks/
│   ├── pages/
│   └── styles/
└── shared/
    ├── constants/
    ├── schemas/
    ├── types/
    └── utils/
```

## Main Process Services

Use services for desktop responsibilities:

```txt
src/main/services/
├── settings-service.ts
├── log-service.ts
├── file-service.ts
├── device-service.ts
└── updater-service.ts
```

IPC handlers should be thin. They should validate input, call services, and map service errors into stable responses.

## Window Management

Centralize BrowserWindow creation.

```txt
src/main/windows/
├── create-main-window.ts
├── create-settings-window.ts
└── window-manager.ts
```

Handle:

- app ready
- all windows closed
- activate on macOS
- before quit
- single instance lock when needed
- restoring or focusing existing windows

## App Lifecycle

For single-instance desktop apps, use `app.requestSingleInstanceLock()`. When a second instance is launched, focus the existing window and pass any deep-link or file-open information through a controlled path.

## Web-to-Desktop Migration

When migrating a web app:

- Keep React/Vue/Svelte UI components reusable.
- Replace browser-only persistence with a desktop storage service when appropriate.
- Move native capabilities behind `window.desktopApi`.
- Keep network API clients separate from local desktop services.
- Avoid making components aware of Electron IPC details.

Recommended renderer abstraction:

```ts
const settings = await window.desktopApi.settings.get()
```

Avoid:

```ts
const settings = await ipcRenderer.invoke('settings:get')
```

## Local Database and Files

Place mutable data under `app.getPath('userData')`. Do not write to app installation directories. Use explicit migrations for local databases or config files.

Suggested layout:

```txt
userData/
├── config.json
├── logs/
├── cache/
└── db/
```

## Cross-Platform Design

Account for differences across Windows, macOS, and Linux:

- app menu behavior
- tray behavior
- file paths and separators
- auto-start mechanisms
- code signing requirements
- installer conventions
- notification permissions
- global shortcuts

Do not hardcode platform-specific paths. Use Electron and Node path utilities in main process.

