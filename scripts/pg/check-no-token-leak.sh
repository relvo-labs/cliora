#!/usr/bin/env bash
# Static gate: nothing in the tree writes the provider credential or a tunnel password
# somewhere it could be read back (plan/11 PG-14, ADR 0022 D19).
#
#   scripts/pg/check-no-token-leak.sh
#
# Four checks, each one covering a way this leaks in practice rather than in theory:
#
#   1. A log or error line that interpolates the credential. The daemon holds the plaintext
#      in memory; one `slog.Info("...", "credential", cred)` added while debugging would put
#      it on disk on every node, and it would look like ordinary instrumentation in review.
#   2. An audit metadata key that the redaction pass does not mask. Keys containing
#      "credential"/"token"/"secret" are masked; a key like `provider_key` would not be, so
#      the allowlist of what tunnel code writes is checked explicitly.
#   3. A golden fixture that carries something shaped like a real token. A realistic-looking
#      value in a fixture eventually gets tried against the real service.
#   4. A response model with a field the credential or a password could travel in.
#
# The complementary checks live in the test suites, where they can assert behaviour rather
# than text: `test_the_integration_response_never_carries_the_token` (serialized response),
# `test_the_credential_audit_records_the_fingerprint_and_nothing_else` (audit metadata), and
# vitest's DOM assertions. This script is for the paths a test cannot reach: fixtures,
# templates, and log call sites that only run on a node.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

FAILED=0

fail() {
  echo "FAIL: $1"
  FAILED=$((FAILED + 1))
}

pass() {
  echo "ok:   $1"
}

# --- 1. No log or error site interpolates the credential ------------------------------- #
#
# Matches a logging/error call on the same line as a credential-shaped identifier. The
# daemon's own field names (`Credential`, `opts.Credential`) are what would appear.
if grep -rnE '(slog\.(Debug|Info|Warn|Error)|fmt\.(Errorf|Sprintf)|log\.(warning|info|error))\(.*([Cc]redential|token)' \
  --include='*.go' --include='*.py' daemon/internal/tunnel daemon/internal/connection \
  backend/app/services/tunnels.py backend/app/services/integrations.py \
  backend/app/api/http/tunnels.py backend/app/api/http/integrations.py 2>/dev/null |
  grep -vE 'credential_undecryptable|Credential that could redirect|CodeUnauthorized|# ' ; then
  fail "a log or error site names the credential; the plaintext must never reach a sink"
else
  pass "no log or error site interpolates the provider credential"
fi

# --- 2. Audit metadata keys are the known, redaction-safe set -------------------------- #
#
# The actual `audit.record(...)` calls are read rather than grepped for: the same file also
# builds a `tunnel.open` payload that legitimately contains `basic_auth.password`, and a text
# search cannot tell that apart from an audit row recording one.
#
# `fingerprint` is deliberate: the redaction pass masks any string under a key containing
# "credential", so the more descriptive `credential_fingerprint` would store `***` and lose
# the fact being recorded.
if python3 scripts/pg/audit_metadata_keys.py; then
  pass "audit metadata carries no token, password, url or label key"
else
  fail "tunnel/integration code writes a forbidden audit metadata key"
fi

# --- 3. Fixtures carry obviously fake credentials -------------------------------------- #
#
# The valid `tunnel.open` fixtures must use a value nobody could mistake for real. A
# fixture that looks like a token is a fixture somebody will paste into a terminal.
for fixture in contracts/v1/fixtures/valid/tunnel-open-*.json; do
  [ -f "$fixture" ] || continue
  credential=$(python3 -c "
import json,sys
payload = json.load(open('$fixture')).get('payload', {})
print(payload.get('credential', ''))
" 2>/dev/null)
  [ -z "$credential" ] && continue
  # Obviously fake: one repeated character, or containing FAKE/EXAMPLE.
  if printf '%s' "$credential" | grep -qE '^(.)\1+$' ||
    printf '%s' "$credential" | grep -qiE 'fake|example|placeholder'; then
    pass "fixture credential is obviously fake: $(basename "$fixture")"
  else
    fail "$(basename "$fixture") carries a realistic-looking credential: use AAAA… instead"
  fi
done

# --- 4. No response model has a field a secret could travel in ------------------------- #
#
# `basic_auth_password` on TunnelDetail is the single intended exception (the creation and
# rotation responses). Anything else — on the integration DTO especially — is a leak.
if python3 - <<'PY'
import re
import sys

text = open("backend/app/api/http/schemas.py", encoding="utf-8").read()
# The integration DTO must not gain a secret-bearing field. Read its class body only.
match = re.search(r"class TunnelIntegrationDTO\(BaseModel\):(.*?)\n\nclass ", text, re.S)
body = match.group(1) if match else ""
bad = [
    field
    for field in re.findall(r"^\s{4}([a-z_]+):", body, re.M)
    # `secret_key_available` is a boolean about the *deployment*, not a secret, which is why
    # the match is on the secret-bearing words rather than on "secret" alone.
    if "token" in field or "password" in field or field in {"credential_value", "secret_key"}
]
if bad:
    print("TunnelIntegrationDTO exposes:", bad)
    sys.exit(1)

# And the summary DTO, which every read path returns, must have no password field.
match = re.search(r"class TunnelSummary\(BaseModel\):(.*?)\n\nclass ", text, re.S)
body = match.group(1) if match else ""
bad = [f for f in re.findall(r"^\s{4}([a-z_]+):", body, re.M) if "password" in f]
if bad:
    print("TunnelSummary exposes:", bad)
    sys.exit(1)
PY
then
  pass "no read DTO has a field the credential or a password could travel in"
else
  fail "a response model exposes a secret-bearing field"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "no credential leak paths found"
  exit 0
fi
echo "$FAILED check(s) failed"
exit 1
