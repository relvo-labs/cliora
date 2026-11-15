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
HOST_CONF="${1:-$ROOT/deploy/nginx/nginx.conf}"
RAILWAY_CONF="${2:-$ROOT/deploy/railway/nginx.conf.template}"
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

# --- 6. Issue 59 admission policy and forwarding contract (values AND scope) ---
# Compare only risk-bearing directives, keeping deliberate topology differences.
security_policy_of() {
  directives_of "$1" | awk '
    /location / { location=$0 }
    /^[[:space:]]*(limit_req|limit_conn|map \$uri |default ""|~\^\/ws\/nodes\/)/ ||
    /proxy_set_header X-(Forwarded-For|Real-IP)/ {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "");
      print location " | " $0
    }'
}
if diff -u <(security_policy_of "$HOST_CONF") <(security_policy_of "$RAILWAY_CONF"); then
  ok "rate/connection limits and client-IP forwarding have identical scope and values"
else
  fail "rate/connection limits or client-IP forwarding differ"
fi
for file in "$HOST_CONF" "$RAILWAY_CONF"; do
  for directive in \
    'limit_req_status 429;' 'limit_conn_status 429;' \
    'limit_req_zone $binary_remote_addr zone=cliora_login:10m rate=10r/m;' \
    'limit_req_zone $binary_remote_addr zone=cliora_refresh:10m rate=10r/m;' \
    'limit_req_zone $binary_remote_addr zone=cliora_register:10m rate=10r/m;' \
    'limit_req zone=cliora_login burst=10 nodelay;' \
    'limit_req zone=cliora_refresh burst=10 nodelay;' \
    'limit_req zone=cliora_register;' 'limit_conn cliora_nodes 50;'; do
    directives_of "$file" | grep -F "$directive" >/dev/null || fail "$file missing $directive"
  done
  if directives_of "$file" | grep 'proxy_add_x_forwarded_for' >/dev/null; then
    fail "$file appends an untrusted forwarding chain"
  fi
done

# Compose may opt into a verified host proxy. Validate explicit trust in either topology;
# runtime includes are generated by the same bounded renderer, with Railway requiring one.
if python3 - "$HOST_CONF" "$RAILWAY_CONF" <<'PYTRUST'
import ipaddress
import re
import sys
from pathlib import Path

for path in sys.argv[1:]:
    source = re.sub(r"#[^\n]*", "", Path(path).read_text())
    for name, expected in (("real_ip_header", "X-Real-IP"), ("real_ip_recursive", "off")):
        values = re.findall(r"\b" + name + r"\s+([^;]+);", source)
        if values != [expected]:
            sys.exit(f"FAIL: {path}: expected exactly {name} {expected}")
    if "include /etc/nginx/trusted-proxies/*.conf;" not in source:
        sys.exit(f"FAIL: {path}: missing generated proxy-trust include")
    for value in re.findall(r"\bset_real_ip_from\s+([^;]+);", source):
        try:
            network = ipaddress.ip_network(value.strip(), strict=True)
        except ValueError:
            sys.exit(f"FAIL: {path}: proxy trust must be numeric and canonical")
        if network.prefixlen == 0:
            sys.exit(f"FAIL: {path}: global proxy trust is forbidden")
print("ok: optional Compose / required Railway trust uses bounded canonical networks")
PYTRUST
then
  ok "real-IP header, recursion and proxy trust contract validated"
else
  fail "proxy trust contract invalid"
fi

# --- 7. Issue 184: the generated include, keyword path included ---
# The static configs above may never contain global trust. Only the renderer may produce it,
# and only for the exact Railway keyword; hand-typed global ranges stay errors.
RENDERER="$ROOT/deploy/railway/19-trusted-proxies.sh"
render_to() { # <dir> <value> [renderer args...]
  local dir="$1" value="$2"; shift 2
  CLIORA_TRUSTED_PROXY_DIR="$dir" CLIORA_TRUSTED_PROXY_CIDRS="$value" sh "$RENDERER" "$@" 2>/dev/null
}
render_dir="$(mktemp -d)"
trap 'rm -rf "$render_dir"' EXIT
if render_to "$render_dir/edge" railway-edge &&
  [ "$(grep -v '^#' "$render_dir/edge/realip.conf")" = "$(printf 'set_real_ip_from 0.0.0.0/0;\nset_real_ip_from ::/0;')" ]; then
  ok "railway-edge renders X-Real-IP trust for every IPv4 and IPv6 peer, and nothing else"
else
  fail "railway-edge does not render exactly set_real_ip_from 0.0.0.0/0 and ::/0"
fi
if render_to "$render_dir/numeric" "10.23.0.4/32,fd00:59::2/128" &&
  [ "$(cat "$render_dir/numeric/realip.conf")" = "$(printf 'set_real_ip_from 10.23.0.4/32;\nset_real_ip_from fd00:59::2/128;')" ]; then
  ok "numeric proxy lists still render bounded entries"
else
  fail "numeric proxy list did not render as bounded entries"
fi
for value in "" "0.0.0.0/0" "::/0" "railway-edge,10.23.0.4/32" "Railway-Edge"; do
  if render_to "$render_dir/reject" "$value"; then
    fail "Railway renderer accepted '${value}'; only railway-edge or numeric non-global ranges may start"
  fi
done
if render_to "$render_dir/compose" railway-edge --allow-direct; then
  fail "the Compose renderer accepted railway-edge; Compose has no Railway edge"
fi
if render_to "$render_dir/direct" "" --allow-direct && [ ! -s "$render_dir/direct/realip.conf" ]; then
  ok "renderer rejects empty/global/mixed Railway values and keeps Compose's direct default"
else
  fail "the Compose direct-facing default no longer renders an empty include"
fi

printf '\n%s\n' "mismatches: $FAILURES"
exit "$FAILURES"
