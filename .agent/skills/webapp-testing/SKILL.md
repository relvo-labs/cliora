---
name: webapp-testing
description: >-
  Test Cliora browser behavior with Playwright, including authentication, nodes, sessions, xterm.js, file preview, RBAC, disconnect, reconnect, and errors. Use when verifying frontend functionality, debugging browser behavior, capturing screenshots or logs, or implementing E2E tests; not for backend unit tests.
---

# Webapp Testing

Use `cliora-project-context`; inspect scripts and run `scripts/with_server.py --help`. Distinguish Vue unit tests, E2E with a deterministic mock daemon, Central-daemon integration, and isolated live CLI smoke tests. Cover login/RBAC, node status, session create/attach/reconnect/terminate, terminal input/resize/scrollback/focus, writer/viewer policy, read-only preview denials, offline/timeout/retry, and output bursts. Prefer accessible selectors, assert visible state and side effects, collect console/network failures, and clean up. Never target production without explicit authorization.
