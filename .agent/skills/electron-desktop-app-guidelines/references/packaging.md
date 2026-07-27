# Electron Packaging Reference

Use this reference when the task involves build configuration, production behavior, installers, code signing, notarization, auto update, environment variables, or release readiness.

## Development vs Production

Keep dev server loading separate from production file loading.

Development may load from Vite or Next dev server. Production should load packaged files with a resolved local path or framework-specific production entry.

Do not leave production dependent on `localhost` dev servers.

## Build Checklist

Check:

- app id
- product name
- icons for each platform
- installer target
- bundled native dependencies
- preload path resolution
- renderer asset path resolution
- environment variable strategy
- source map policy
- code signing
- macOS notarization when required
- Windows signing when required
- update provider configuration
- logs and crash reporting

## Preload Path

Ensure preload path works in both development and production. Do not assume TypeScript source paths exist after packaging.

Prefer a small helper that resolves packaged paths explicitly.

## Auto Update

Keep update logic in main process. Renderer may request checks and receive status updates, but should not directly control update internals.

Common states:

```txt
idle
checking
available
not-available
downloading
downloaded
installing
error
```

Require user confirmation before installing updates unless the product intentionally uses silent updates.

## Environment Variables

Separate build-time and runtime config. Do not expose secrets in renderer bundles. Anything included in renderer code should be considered public.

## Logs

Write logs to an app-specific location under user data or logs path. Provide a user-safe action such as `logs:open-folder` rather than exposing arbitrary filesystem browsing.

## Native Modules

When using native modules, verify:

- rebuild step matches Electron version
- architecture is correct
- packaging includes native binaries
- CI builds each target platform intentionally

## Release Channels

If the app has beta/stable channels, keep update feeds separate. Do not let users accidentally downgrade or cross channels unless the product supports that flow.

## Production Smoke Test

After packaging, test the installed app, not only the dev app:

- launch app from installer
- open main window
- call preload API
- execute key IPC handlers
- read/write config
- restart app
- check logs
- verify update behavior with mock or staging feed

