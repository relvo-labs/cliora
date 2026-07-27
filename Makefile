.PHONY: bootstrap format-check lint typecheck unit contract integration e2e build check dev-central dev-stack dev-frontend migrate create-admin test-db perf release release-snapshot traceability-validate traceability-selectors traceability-render traceability-coverage traceability-coverage-strict traceability-test traceability

# Postgres URL for the P1 data layer (override to point at your instance).
DB_URL ?= postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test

bootstrap:
	uv sync --project backend --locked
	cd frontend && npm ci
	cd daemon && go mod download

format-check:
	uv run --project backend ruff format --check backend
	cd daemon && test -z "$$(gofmt -l .)"
	cd frontend && npm run format:check

lint:
	uv run --project backend ruff check backend
	cd daemon && go vet ./...
	cd frontend && npm run lint

typecheck:
	uv run --project backend mypy backend/app
	cd frontend && npm run typecheck

unit:
	uv run --project backend pytest backend/tests -q
	cd daemon && go test -race ./...
	cd frontend && npm run test:unit -- --run

contract:
	uv run --project backend pytest backend/tests/contract -q
	cd daemon && go test ./internal/protocol -run Contract
	cd frontend && npm run test:unit -- --run src/protocol

integration:
	cd daemon && go test -tags integration -race ./internal/session ./internal/connection ./internal/files ./internal/workspace

e2e:
	cd frontend && npm run test:e2e

build:
	uv build --project backend
	cd daemon && mkdir -p bin && go build -o bin/agentd ./cmd/agentd && go build -o bin/fakecli ./cmd/fakecli
	cd frontend && npm run build

check: format-check lint typecheck unit contract build traceability-validate

# --- Requirement traceability (ADR 0019 / plan/06) ---
traceability-validate:
	scripts/trace validate --level static
	scripts/trace render --check

traceability-selectors:
	scripts/trace validate --level selectors

traceability-render:
	scripts/trace render --write

# Changed-scope blocking (ADR 0019 rollout stage 4): any gap outside the named
# baseline debt fails, and so does a debt entry that has since been closed.
traceability-coverage:
	scripts/trace coverage --scope all --baseline traceability/baseline-debt.json

# Stage 7 readiness: exits 0 only once the debt list is empty.
traceability-coverage-strict:
	scripts/trace coverage --scope all --strict

traceability-test:
	uv run --project backend python -m pytest scripts/traceability/tests -q

traceability: traceability-validate traceability-selectors traceability-coverage traceability-test

# Central alone, for API work. There is no dev relay any more (P4-07 retired the P0
# one), so a node reaches this through real enrollment — use `dev-stack` for that.
dev-central:
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8000

# Central + a real enrolled daemon node whose "claude" runtime is the Fake CLI, all
# rootless. This replaces the old `dev-daemon`, which connected to the P0 relay with a
# shared static token: that path no longer exists, and the real enrollment handshake
# is what the product actually does. Needs a PostgreSQL at CLIORA_DATABASE_URL.
dev-stack:
	CLIORA_DATABASE_URL=$(DB_URL) scripts/e2e/run-stack.sh

dev-frontend:
	cd frontend && npm run dev

# --- P1 data layer helpers ---
migrate:
	cd backend && CLIORA_DATABASE_URL=$(DB_URL) uv run --project . alembic upgrade head

# Create the first Admin user. Set ADMIN_USER and CLIORA_ADMIN_PASSWORD.
create-admin:
	cd backend && CLIORA_DATABASE_URL=$(DB_URL) uv run --project . python -m app.bootstrap create-admin --username $${ADMIN_USER:-admin}

# DB-backed tests (requires a migrated Postgres at DB_URL).
test-db:
	cd backend && CLIORA_DATABASE_URL=$(DB_URL) CLIORA_TEST_DATABASE_URL=$(DB_URL) uv run --project . pytest tests/db -q

# Latency / bounds harnesses. Each exits non-zero on a regression.
#   P2 (plan/03/08 §3): terminal-relay latency, backpressure and scale.
#   P3 (plan/04/07 §3): filesystem latency in two legs — the daemon's confined
#   list/read/search, and Central's relay + correlation bounds. Artifacts land in
#   artifacts/{p2,p3}/local/. CLIORA_PERF_OUT must be absolute: `go test` runs in
#   the package directory.
perf:
	cd backend && uv run --project . python perf/relay_bench.py --out ../artifacts/p2/local/relay-bench.json
	cd backend && uv run --project . python perf/files_bench.py --out ../artifacts/p3/local/relay-latency.json
	cd daemon && CLIORA_PERF_OUT="$(CURDIR)/artifacts/p3/local/fs-latency.json" go test ./internal/files -run TestFilesystemLatencyBudget

# --- Release artifacts (ADR 0011) ---
# Build the agentd tarballs + checksums.txt from daemon/.goreleaser.yaml.
# Requires GoReleaser on PATH (https://goreleaser.com/install/). Output lands in
# daemon/dist/. `release-snapshot` is a tag-less dry run for local verification;
# CI runs `release` on version tags (.github/workflows/p1.yml).
release:
	cd daemon && goreleaser release --clean

release-snapshot:
	cd daemon && goreleaser release --snapshot --clean
