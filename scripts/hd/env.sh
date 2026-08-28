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
export PATH="$HOME/.local/bin:$PATH"
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" && nvm use "$(cat "$(git rev-parse --show-toplevel)/.nvmrc")" >/dev/null 2>&1
export CLIORA_TEST_DATABASE_URL="${CLIORA_TEST_DATABASE_URL:-postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test}"
export CLIORA_DATABASE_URL="${CLIORA_DATABASE_URL:-$CLIORA_TEST_DATABASE_URL}"
