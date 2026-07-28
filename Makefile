.PHONY: bootstrap format-check lint typecheck unit contract integration e2e build check dev-central dev-stack dev-frontend migrate create-admin test-db perf release release-snapshot traceability-validate traceability-selectors traceability-render traceability-coverage traceability-coverage-baseline traceability-test traceability railway-parity railway-test railway-check

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

check: format-check lint typecheck unit contract build traceability-validate railway-check

# --- Railway deployment target (ADR 0020 / plan/07) ---
# Both of these are static and hermetic: no platform account, no network. What they cannot
# prove is asserted against a running deployment by scripts/railway/verify-deployment.sh.

# The two edge configurations (host nginx and the Railway template) must not drift on the
# security policy, or "Cliora sends this CSP" stops being a true sentence.
railway-parity:
	scripts/railway/check-edge-parity.sh

# The artifact baker and the pre-deploy variable check. Both are gates whose whole value is
# that they fail on a bad input, so both have negative tests.
railway-test:
	uv run --project backend python -m pytest scripts/railway/tests -q

railway-check: railway-parity railway-test

# --- Requirement traceability (ADR 0019 / plan/06) ---
traceability-validate:
	scripts/trace validate --level static
	scripts/trace render --check

traceability-selectors:
	scripts/trace validate --level selectors

traceability-render:
	scripts/trace render --write

# Full release blocking (ADR 0019 rollout stage 7). Any criterion missing a
# required link, and any criterion whose PRD text cannot be decided, fails here.
traceability-coverage:
	scripts/trace coverage --scope all --strict

# The baseline-debt allowlist is empty, so this now only guards against one being
# added back without the rollout being stepped down deliberately.
traceability-coverage-baseline:
	scripts/trace coverage --scope all --baseline traceability/baseline-debt.json

traceability-test:
	uv run --project backend python -m pytest scripts/traceability/tests -q

traceability: traceability-validate traceability-selectors traceability-coverage traceability-coverage-baseline traceability-test

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
