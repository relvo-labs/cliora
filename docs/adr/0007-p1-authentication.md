# ADR 0007: P1 authentication scheme

Status: accepted (2026-07-24)

Supersedes the development-only auth in ADR 0006 for the control plane.

- **User auth**: username + password. Passwords hashed with **Argon2id** (`argon2-cffi`), parameters fixed in `Settings` (time_cost=3, memory_cost=64 MiB, parallelism=4; revisit under load). Login runs a dummy verify for unknown users to avoid a timing oracle.
- **Tokens**: JWT **access** token (TTL 15 min) carrying `sub`, `role`, `jti`, `iat`, `exp`; **refresh** token (TTL 14 days) that is revocable. Revocation uses a per-user `token_version` integer plus a persisted refresh record; `logout` bumps/invalidates so the refresh fails immediately. Signing: HS256 with a secret from `CLIORA_JWT_SECRET` (rotatable; asymmetric keys deferred). `exp`/`iat` are aware UTC; comparison is in UTC; an instant exactly at `exp` is treated as expired.
- **Browser WS handshake**: JS WebSocket cannot set headers and a long-lived JWT must never appear in a query string or log. Browsers call `POST /api/ws-ticket` (with a valid access token) to mint a **single-use ticket** (TTL 60 s, bound to user + resource), then connect `?ticket=…`; the boundary validates and burns it. The P0 `cliora-p0-dev` subprotocol stays only behind `CLIORA_P0_ENABLED`.
- **TLS**: production requires `wss://` with standard server-certificate validation (CA + hostname). Plain `ws://` is allowed only behind an explicit dev flag. Certificate pinning / mTLS is deferred and not required for MVP.
- **Roles**: a user has exactly one role via `users.role_id` (PRD §12.1). The `user_roles` join and `daemon_releases` (tech §13.1) are deferred to P4.
