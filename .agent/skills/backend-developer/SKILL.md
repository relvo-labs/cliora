---
name: backend-developer
description: >-
  Design and implement Cliora's Central backend architecture with FastAPI, PostgreSQL, WebSockets, authentication, auditing, and observability. Use when changing service boundaries, repositories, connection registries, scalability, security, or backend-wide behavior; use fastapi for framework details.
---

# Backend Developer

Use `cliora-project-context`; inspect the backend and read relevant tech sections 6-7 and 12-20. Trace work through API, service, repository, database, and WebSocket layers. Keep durable state in PostgreSQL but terminal bytes out; define transaction, RBAC, timeout, idempotency, errors, audit, logs, and metrics. Preserve outbound daemon connections and browser-independent sessions. Test success, denial, timeout, disconnect, stale state, and rollback. Use `fastapi`, `terminal-websocket-protocol`, `timezone-precision`, and `cliora-security-review` as applicable. Do not invent coverage targets or topology.
