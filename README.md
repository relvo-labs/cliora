# Cliora

Cliora is a browser control plane for CLI coding agents: Browser → FastAPI Central → Go daemon → tmux → CLI.

- **P0** is a local-only terminal vertical slice with no database or production auth (see [P0](#p0-local-terminal-slice)).
- **P1** adds the PostgreSQL-backed control plane: authentication, node enrollment, and the daemon installer (see [P1](#p1-node-control-plane)).

## P0 (local terminal slice)

Cliora P0 is a local-only terminal vertical slice: Browser → FastAPI Central → Go daemon → tmux → deterministic Fake CLI. It intentionally has no database, production authentication, arbitrary shell entry point, or real Claude/Codex integration.

## Prerequisites

- Linux and tmux 3.4 or newer
- Python 3.12.3 and uv
- Go 1.26.5
- Node 22.14.0 and npm 10

Verify with `python --version`, `uv --version`, `go version`, `node --version`, `npm --version`, and `tmux -V`. Runtime versions come from `.python-version`, `.go-version`, and `.nvmrc` and are also consumed by CI.

## Bootstrap and checks

```bash
make bootstrap
make check
```

`make check` runs format checks, lint/vet, type checking, unit tests, contract tests, and builds. Host-level tmux integration and browser E2E are separate because they require tmux and installed browsers:

```bash
make integration
make e2e
```

## Local development

Use three terminals:

```bash
make dev-central
make dev-daemon
make dev-frontend
```

Defaults are development-only: node `00000000-0000-4000-8000-000000000001`, session `00000000-0000-4000-8000-000000000002`, and shared credential `cliora-p0-dev-only`. Open `http://localhost:5173/poc/terminal`. The backend refuses to expose P0 WebSockets unless `CLIORA_P0_ENABLED=true` and refuses that mode when `CLIORA_ENV=production`.

Terminal input/output is never logged or persisted. A browser disconnect detaches transport only; only an explicit stop removes the tmux session.

## P1 (node control plane)

P1 introduces a PostgreSQL data layer, JWT authentication, node enrollment, and
the daemon installer. Unlike P0, this path requires a database.

### Additional prerequisites

- PostgreSQL 16 (the CI service container and local default)
- Everything from the P0 prerequisites above

### Database configuration

Central and the P1 tooling read their connection string from
`CLIORA_DATABASE_URL` (all settings use the `CLIORA_` prefix; see
`backend/app/settings.py`). The Makefile's P1 helpers take a single `DB_URL`
variable and pass it through as `CLIORA_DATABASE_URL`; it defaults to a local
`cliora_test` database:

```
DB_URL ?= postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test
```

Start a local PostgreSQL matching that default (adjust `DB_URL` to point at your
own instance):

```bash
docker run -d --name cliora-pg -p 5432:5432 \
  -e POSTGRES_USER=cliora -e POSTGRES_PASSWORD=cliora -e POSTGRES_DB=cliora_test \
  postgres:16-alpine
```

### Migrate, bootstrap, and test

```bash
make migrate       # alembic upgrade head (0001 → 0002 seed roles → 0003 Ed25519 credentials)
make create-admin  # bootstrap the first Admin so someone can sign in
make test-db       # DB-backed auth/enrollment/node/status/audit tests
```

`make create-admin` reads the password from `CLIORA_ADMIN_PASSWORD` (or
`--password`) so it never lands in shell history, and takes the username from
`ADMIN_USER` (default `admin`):

```bash
CLIORA_ADMIN_PASSWORD='choose-a-strong-password' ADMIN_USER=admin make create-admin
```

`make test-db` sets both `CLIORA_DATABASE_URL` and `CLIORA_TEST_DATABASE_URL`
(the DB-test suite is gated on the latter) to `DB_URL`.

### Run Central against PostgreSQL

Point Central at your database via `CLIORA_DATABASE_URL` and start Uvicorn (the
P1 auth/node/enrollment APIs need no `CLIORA_P0_ENABLED` flag):

```bash
CLIORA_DATABASE_URL="$DB_URL" \
  uv run --project backend uvicorn app.main:app --app-dir backend --port 8000
```

Then sign in as the admin you bootstrapped and create enrollment tokens.

### Installing a daemon (node enrollment)

Admins mint a one-time enrollment token in the UI, then install the `agentd`
daemon on a Linux host with a single command. The installer verifies a SHA256
checksum before running anything and never prints the token. See
[deploy/README.md](deploy/README.md) for the full flow, `agentd` lifecycle
commands, `agentd doctor` diagnostics, and how release artifacts are produced
(`make release` / GoReleaser).
