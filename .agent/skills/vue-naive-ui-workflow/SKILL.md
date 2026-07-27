---
name: vue-naive-ui-workflow
description: >-
  Implement Cliora's Vue 3, TypeScript, Vite, Naive UI, Pinia, Vue Router, xterm.js, and Monaco frontend. Use when building pages, stores, composables, routes, forms, tables, terminal views, file previews, WebSocket state, or frontend tests.
---

# Vue Naive UI Workflow

1. Use `cliora-project-context`; inspect package manager, scripts, TypeScript config, and source layout.
2. Read PRD section 10, tech section 16, and `research/style.md` as relevant.
3. Separate API types, shared stores, lifecycle composables, views, and presentation components.
4. Model idle, loading, success, empty, stale, reconnecting, offline, forbidden, and error.
5. Apply semantic Naive UI tokens from `style.md`; do not create another palette.
6. Test transitions and cleanup, then run existing lint, typecheck, unit, and E2E scripts.

Prefer typed Composition API and Pinia only for shared state. Give each WebSocket, xterm terminal, Monaco model, and subscription one owner and dispose it. Never build shell commands in the renderer. Preserve terminal keyboard, resize, scrollback, and reconnect behavior. Keep MVP preview read-only and distinguish sensitive, oversized, and binary files.
