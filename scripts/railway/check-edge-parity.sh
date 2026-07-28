#!/usr/bin/env bash
# Keep the two edge configurations from drifting on the parts that must not drift
# (RW-05, ADR 0020).
#
# Cliora now ships two edges: `deploy/nginx/nginx.conf` for the single-host compose
# topology, and `deploy/railway/nginx.conf.template` for the platform deployment. They
# differ on purpose — TLS termination, listen port, how the upstream is resolved. They must
# not differ on the security policy, because then "Cliora sends this CSP" stops being a
# true sentence and starts being a sentence about whichever deployment someone tested.
#
# This is a *static* check and only claims to be one: it compares strings. Whether the
# headers actually reach a browser is asserted over the wire by
# `scripts/p4/verify-edge.sh` (compose) and `scripts/railway/verify-deployment.sh`
# (platform). The division of labour matters — a file can be identical in both places and
# still be discarded by nginx's `add_header` inheritance rules, which is exactly what
# happened once already.
#
#   scripts/railway/check-edge-parity.sh
#
# Exit status is the number of mismatches, so `make` stops on any of them.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOST_CONF="$ROOT/deploy/nginx/nginx.conf"
RAILWAY_CONF="$ROOT/deploy/railway/nginx.conf.template"
FAILURES=0

ok()   { printf 'ok: %s\n' "$*"; }
fail() { FAILURES=$((FAILURES + 1)); printf 'FAIL: %s\n' "$*" >&2; }

for file in "$HOST_CONF" "$RAILWAY_CONF"; do
  [ -f "$file" ] || { printf 'FAIL: missing %s\n' "$file" >&2; exit 1; }
done

# --- 1. The CSP, byte for byte ---
# Each file must also be internally consistent: the policy is repeated per location because
# `add_header` does not inherit, and one stale copy is the same bug as two stale files.
csp_of() {
  grep -o 'Content-Security-Policy "[^"]*"' "$1" | sed 's/^[^"]*"//; s/"$//' | sort -u
}
host_csp="$(csp_of "$HOST_CONF")"
railway_csp="$(csp_of "$RAILWAY_CONF")"
for label in host railway; do
  eval "value=\$${label}_csp"
  count=$(printf '%s\n' "$value" | grep -c . )
  [ "$count" = "1" ] || fail "$label config declares $count distinct CSP values; every copy must be identical"
done
[ -n "$host_csp" ] || fail "no Content-Security-Policy found in $HOST_CONF"
if [ "$host_csp" = "$railway_csp" ]; then
  ok "CSP is identical in both edge configurations"
else
  fail "CSP differs between the two edge configurations"
  diff <(printf '%s\n' "$host_csp") <(printf '%s\n' "$railway_csp") >&2
fi

# --- 2. The CSP still says what it is supposed to say ---
# Checked explicitly rather than left to equality: removing a clause from *both* files would
# pass a pure parity test while silently breaking Monaco or opening the policy up.
case "$host_csp" in
  *"worker-src 'self' blob:"*) ok "CSP keeps worker-src blob: (Monaco's language workers)" ;;
  *) fail "CSP lost worker-src 'self' blob:; the editor renders blank with only a console error" ;;
esac
if printf '%s' "$host_csp" | grep -qE '(^|[[:space:]])https?://'; then
  fail "CSP names an external origin: $(printf '%s' "$host_csp" | grep -oE 'https?://[^ ;]*' | tr '\n' ' ')"
else
  ok "CSP names no external origin"
fi

# --- 3. The security header set, and how many times each appears ---
# Occurrence counts are the drift signal: these headers are repeated per location precisely
# because a location that declares its own `add_header` discards the server-level set, so a
# count that falls out of step means one copy was edited and another was not.
HEADERS=(
  "Strict-Transport-Security"
  "X-Content-Type-Options"
  "Referrer-Policy"
  "X-Frame-Options"
  "Cross-Origin-Opener-Policy"
  "Permissions-Policy"
  "Content-Security-Policy"
)
for header in "${HEADERS[@]}"; do
  host_count=$(grep -c "add_header $header " "$HOST_CONF")
  railway_count=$(grep -c "add_header $header " "$RAILWAY_CONF")
  if [ "$host_count" != "$railway_count" ]; then
    fail "$header appears ${host_count}× in the host config and ${railway_count}× in the platform config"
  elif [ "$host_count" -lt 3 ]; then
    fail "$header appears only ${host_count}× (expected the server block plus each location that sets Cache-Control)"
  else
    ok "$header appears ${host_count}× in both"
  fi
done

# --- 4. Numeric limits that a protocol contract depends on ---
# Comments are stripped first. Both files discuss their own directives in prose — the host
# config's /ws/ comment contains the literal text `proxy_read_timeout 20s` as an example of
# the value that must *not* be used — so an extractor that reads comments reports the
# example instead of the setting. The first version of this script did exactly that and
# reported a mismatch that did not exist.
directives_of() { sed 's/#.*//' "$1"; }
value_of() {
  directives_of "$1" | grep -oE "^[[:space:]]*$2 [^;]+;" | head -1 |
    sed -E "s/^[[:space:]]*$2 //; s/;$//"
}

host_body=$(value_of "$HOST_CONF" client_max_body_size)
railway_body=$(value_of "$RAILWAY_CONF" client_max_body_size)
if [ "$host_body" != "$railway_body" ]; then
  fail "client_max_body_size differs: '$host_body' vs '$railway_body'"
elif [ "${host_body%m}" -lt 16 ] 2>/dev/null; then
  fail "client_max_body_size is $host_body; below the 8 MiB filesystem contract a legal file read becomes a 413"
else
  ok "client_max_body_size is $host_body in both"
fi

# The invariant is proxy_read_timeout > uvicorn's ws_ping_interval (20 s by default). Set it
# below and every terminal and daemon socket dies on a fixed cycle regardless of activity.
ws_timeout_of() {
  directives_of "$1" | awk '/location \/ws\/ \{/,/^[[:space:]]*\}/' |
    grep -oE 'proxy_read_timeout [0-9]+s' | head -1 | grep -oE '[0-9]+'
}
host_ws=$(ws_timeout_of "$HOST_CONF")
railway_ws=$(ws_timeout_of "$RAILWAY_CONF")
if [ -z "$host_ws" ] || [ -z "$railway_ws" ]; then
  fail "could not read proxy_read_timeout from the /ws/ location in both configs"
elif [ "$host_ws" != "$railway_ws" ]; then
  fail "/ws/ proxy_read_timeout differs: ${host_ws}s vs ${railway_ws}s"
elif [ "$host_ws" -lt 300 ]; then
  fail "/ws/ proxy_read_timeout is ${host_ws}s; too close to uvicorn's ping interval to be safe"
else
  ok "/ws/ proxy_read_timeout is ${host_ws}s in both"
fi

# --- 5. Rules that exist as blocks, not comments ---
for file in "$HOST_CONF" "$RAILWAY_CONF"; do
  name="$(basename "$file")"
  if awk '/location = \/api\/metrics \{/,/\}/' "$file" | grep -q 'return 404'; then
    ok "$name refuses /api/metrics with an exact-match block"
  else
    fail "$name has no exact-match 404 for /api/metrics; 'location /api/' would proxy it through"
  fi
  grep -q 'Cache-Control "no-store"' "$file" \
    && ok "$name keeps index.html uncached" \
    || fail "$name does not set no-store on the HTML entry point"
  grep -q 'Cache-Control "public, immutable"' "$file" \
    && ok "$name caches hashed assets immutably" \
    || fail "$name does not cache /assets/ immutably"
done

printf '\n%s\n' "mismatches: $FAILURES"
exit "$FAILURES"
