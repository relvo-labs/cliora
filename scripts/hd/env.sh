# Source this before running anything in `plan/27`. Six lines, and four of them exist
# because getting them wrong produces *failures that look like defects*.
#
#   CLIORA_TEST_DATABASE_URL   the fixture's database
#   CLIORA_DATABASE_URL        **the same one**, and this is the non-obvious half:
#                              `AuthzDenialAuditMiddleware._record` opens its own session
#                              from `get_database()` rather than from the fixture, so with
#                              the two pointing at different databases the audit row is
#                              written to one and asserted in the other. The symptom is
#                              `test_audit_coverage` failing on `assert 0 == 1` with an
#                              `audit_write_failed` warning three screens earlier — which
#                              reads as a broken audit chain and is not one.
#
# Discovered while running the `beta.2` baseline: ten tests failed on a tree that had
# never been touched, and nine of them were this.
#
# **Run the database suite once at a time.** `tests/db/` shares one PostgreSQL database
# and does not namespace per worker, so two concurrent `pytest tests` runs corrupt each
# other. The symptom is a large, *unstable* failure count — 73 on one run and 54 on the
# next from identical code — which reads as a real regression and is not one. If a run
# reports dozens of failures, check `pgrep -af pytest` before reading the tracebacks.
export PATH="$HOME/.local/bin:$PATH"
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" && nvm use "$(cat "$(git rev-parse --show-toplevel)/.nvmrc")" >/dev/null 2>&1
export CLIORA_TEST_DATABASE_URL="${CLIORA_TEST_DATABASE_URL:-postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test}"
export CLIORA_DATABASE_URL="${CLIORA_DATABASE_URL:-$CLIORA_TEST_DATABASE_URL}"

# Stack-only settings. Kept out of the block above because the test suites do not need
# them and a `create-admin` that demands a master key is a confusing first error.
hd_stack_env() {
  export CLIORA_DATABASE_URL="postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_hd"
  export CLIORA_TEST_DATABASE_URL="$CLIORA_DATABASE_URL"
  export CLIORA_ADMIN_PASSWORD="e2e-admin-pw"
  export CLIORA_PROJECTS_ENABLED=true
  export CLIORA_AGENT_RUNS_ENABLED=true
  # Required whenever agent runs are on: a deployment that can dispatch secrets must be
  # able to decrypt them, and settings refuses to start without it rather than starting
  # and failing at the first dispatch.
  export CLIORA_SECRET_MASTER_KEY="${CLIORA_SECRET_MASTER_KEY:-aGQtZTFsb2NhbHN0YWNrbWFzdGVya2V5MzJieXRlcyE=}"
  export CLIORA_JWT_SECRET="${CLIORA_JWT_SECRET:-hd-e1-local-stack-jwt-secret-not-for-production}"
}
