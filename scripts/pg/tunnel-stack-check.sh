#!/usr/bin/env bash
# Drive the port-forwarding path against a running stack, without a browser (plan/11 PG-14).
#
#   CLIORA_DATABASE_URL=... scripts/e2e/run-stack.sh scripts/pg/tunnel-stack-check.sh
#
# Why this exists next to the Playwright suite rather than inside it: the browser leg needs
# system libraries only root can install, so on an unprivileged host it cannot run at all —
# and "the gate could not launch" must not be the same colour as "the gate passed". This
# script asserts everything the suite asserts *except the rendering*: Central's routes, the
# control protocol, the supervisor, the stand-in provider, the URL's shape, the audit rows,
# and that the credential never comes back. It needs curl and python3 and nothing else.
#
# The tunnel it opens forwards `faketunnelapp` through `faketunnelprovider`, so the URL is on
# `.example.invalid` and is never fetched — RFC 2606 guarantees it cannot resolve.
set -uo pipefail

BASE="${E2E_BASE_URL:-http://127.0.0.1:${CENTRAL_PORT:-8000}}"
ADMIN_USER="${E2E_ADMIN_USER:-e2e-admin}"
ADMIN_PASS="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}"
APP_PORT="${E2E_TUNNEL_APP_PORT:-5199}"
TOKEN="STACKFAKETOKEN123"

FAILED=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=$((FAILED + 1)); }

jqp() { python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }

echo "== port forwarding against the stack at $BASE =="

ACCESS="$(curl -fsS -X POST "$BASE/api/auth/login" -H 'content-type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" | jqp 'd["tokens"]["access_token"]')"
[ -n "$ACCESS" ] || { fail "could not sign in"; exit 1; }
AUTH=(-H "authorization: Bearer $ACCESS" -H 'content-type: application/json')

# --- 1. the routes are absent until the integration is enabled -------------------------- #
CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/tunnels" "${AUTH[@]}")"
if [ "$CODE" = "404" ]; then
  pass "tunnel routes answer 404 while the integration is disabled"
else
  # Not a failure on a re-run: the database keeps the integration enabled.
  printf '  \033[33mNOTE\033[0m tunnels already enabled on this database (got %s)\n' "$CODE"
fi

# --- 2. enabling requires the acknowledgement ------------------------------------------- #
CODE="$(curl -s -o /dev/null -w '%{http_code}' -X PUT "$BASE/api/integrations/tunnel" \
  "${AUTH[@]}" -d '{"enabled":true}')"
case "$CODE" in
  422) pass "enabling without the acknowledgement is refused (422)" ;;
  200) printf '  \033[33mNOTE\033[0m already acknowledged on this database\n' ;;
  *)   fail "unexpected status enabling without acknowledgement: $CODE" ;;
esac

curl -fsS -X PUT "$BASE/api/integrations/tunnel" "${AUTH[@]}" \
  -d '{"enabled":true,"acknowledge":true}' >/dev/null || fail "could not enable the integration"

# --- 3. the credential goes in and never comes back ------------------------------------- #
STORED="$(curl -fsS -X PUT "$BASE/api/integrations/tunnel/credential" "${AUTH[@]}" \
  -d "{\"token\":\"$TOKEN\"}")"
READBACK="$(curl -fsS "$BASE/api/integrations/tunnel" "${AUTH[@]}")"
if grep -q "$TOKEN" <<<"$STORED$READBACK"; then
  fail "the token appeared in an API response"
else
  pass "no response contains the token"
fi
FINGERPRINT="$(jqp 'd["credential"]["fingerprint"] or ""' <<<"$READBACK")"
[ "${#FINGERPRINT}" = 8 ] && pass "the credential is reported as an 8-hex fingerprint" \
  || fail "unexpected fingerprint: '$FINGERPRINT'"

# --- 4. the node reports its prerequisites ---------------------------------------------- #
NODE_ID="$(curl -fsS "$BASE/api/nodes" "${AUTH[@]}" |
  jqp 'next((n["id"] for n in d if n["status"]=="online"), "")')"
[ -n "$NODE_ID" ] || { fail "no online node in the stack"; exit 1; }
POLICY="$(curl -fsS "$BASE/api/nodes/$NODE_ID/tunnel-policy" "${AUTH[@]}")"
if [ "$(jqp 'd["prereq_ok"]' <<<"$POLICY")" = "True" ] &&
  [ "$(jqp 'd["enabled"]' <<<"$POLICY")" = "True" ]; then
  pass "the node reports its prerequisites met and the policy permits"
else
  fail "policy/prerequisites not met: $POLICY"
fi

# --- 5. create: the URL comes back, and so does exactly one password --------------------- #
CREATED="$(curl -fsS -X POST "$BASE/api/tunnels" "${AUTH[@]}" -d "{
  \"node_id\":\"$NODE_ID\",\"port\":$APP_PORT,\"protection\":\"basic\",
  \"acknowledge_third_party\":true}")"
TUNNEL_ID="$(jqp 'd["id"]' <<<"$CREATED")"
URL="$(jqp 'd["url"] or ""' <<<"$CREATED")"
PASSWORD="$(jqp 'd["basic_auth_password"] or ""' <<<"$CREATED")"
if [[ "$URL" =~ ^https://[a-z0-9-]+\.tunnel\.example\.invalid$ ]]; then
  pass "the provider's URL arrived and has the expected shape: $URL"
else
  fail "unexpected URL: '$URL'"
fi
[ -n "$PASSWORD" ] && pass "the creation response carries the one-time password" \
  || fail "no password in the creation response"
if [[ "$PASSWORD" == *:* ]]; then
  fail "the generated password contains the provider's option separator"
else
  pass "the generated password contains no ':'"
fi

# --- 6. and nowhere else ---------------------------------------------------------------- #
LIST="$(curl -fsS "$BASE/api/tunnels" "${AUTH[@]}")"
if grep -q "$PASSWORD" <<<"$LIST"; then
  fail "the password is readable from the tunnel list"
else
  pass "no read response carries the password"
fi
if [ "$(jqp 'd[0]["state"]' <<<"$LIST")" = "running" ]; then
  pass "the tunnel is reported running"
else
  fail "unexpected state: $(jqp 'd[0]["state"]' <<<"$LIST")"
fi

# --- 7. the audit trail records it, without the URL ------------------------------------- #
AUDIT="$(curl -fsS "$BASE/api/audit?actions=tunnel.create&range=1h" "${AUTH[@]}")"
if grep -q "$URL" <<<"$AUDIT"; then
  fail "the tunnel URL was written to the audit trail"
elif grep -q '"tunnel.create"' <<<"$AUDIT"; then
  pass "tunnel.create is audited and carries no URL"
else
  fail "no tunnel.create audit row found"
fi

# --- 8. close ---------------------------------------------------------------------------- #
CODE="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/api/tunnels/$TUNNEL_ID" "${AUTH[@]}")"
[ "$CODE" = "204" ] && pass "closing answers 204" || fail "close returned $CODE"
REMAINING="$(curl -fsS "$BASE/api/tunnels" "${AUTH[@]}" | jqp 'len(d)')"
[ "$REMAINING" = "0" ] && pass "the closed tunnel leaves the live list" \
  || fail "$REMAINING tunnel(s) still listed after closing"

# --- 9. and the child process is gone ---------------------------------------------------- #
if pgrep -f "faketunnelprovider" >/dev/null 2>&1; then
  sleep 2
  if pgrep -f "faketunnelprovider" >/dev/null 2>&1; then
    fail "a stand-in provider process survived the close"
  else
    pass "no provider process survived the close"
  fi
else
  pass "no provider process survived the close"
fi

curl -fsS -X DELETE "$BASE/api/integrations/tunnel/credential" "${AUTH[@]}" >/dev/null || true

echo
if [ "$FAILED" -eq 0 ]; then
  echo "port forwarding works end to end against the stand-in provider"
  exit 0
fi
echo "$FAILED check(s) failed"
exit 1
