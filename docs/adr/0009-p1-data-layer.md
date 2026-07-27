# ADR 0009: P1 data layer

Status: accepted (2026-07-24)

- **Database**: PostgreSQL 16. SQLAlchemy 2 **async** engine over `asyncpg`, connection string from `CLIORA_DATABASE_URL`. One `AsyncSession` per request/use case, one transaction; the engine is created and disposed in the FastAPI lifespan.
- **Layering**: `api/` (HTTP + WS boundary) → `services/` (use cases, RBAC, state) → `repositories/` (the only place that touches ORM queries). Terminal bytes and secret plaintext never enter the DB.
- **Migrations**: Alembic. Autogenerate is a starting point only — every migration is reviewed and must provide a working `downgrade`. Migrations must clean-upgrade on an empty DB and be safe to re-run against head.
- **Seeding**: roles (`Admin`/`Developer`/`Viewer`) and their permission matrix (PRD §8.1) are written by a dedicated **versioned migration**, never seeded at startup. The first Admin user is created by an explicit `cliora-admin` CLI/management command (password hashed with Argon2id), never a hard-coded plaintext.
- **Time**: all timestamp columns are `TIMESTAMP(timezone=True)`; Python holds aware UTC; DTOs serialize RFC 3339 `Z`. Naive datetimes are rejected before they reach the DB or a DTO (enforced by tests). Durations (heartbeat timeout, token expiry checks, retry) use monotonic time, not wall-clock subtraction — see ADR 0010.
- **Testing**: an ephemeral PostgreSQL (CI service container or a throwaway database/schema) with upgrade→downgrade and transaction-rollback tests; no reliance on a developer's local data.
