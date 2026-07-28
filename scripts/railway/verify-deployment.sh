#!/usr/bin/env bash
# Assert the deployed edge over the wire (RW-10, ADR 0020).
#
# The platform counterpart to `scripts/p4/verify-edge.sh`, and it exists for the same
# reason: every claim about TLS, headers, the CSP and WebSocket behaviour otherwise rests on
# having *read* a configuration file, and the two most likely regressions — a CSP that
# blanks Monaco, a proxy timeout that kills every terminal on a fixed cycle — would both
# ship green. The difference is that this one owns nothing: no docker, no local Central, no
# database. It takes a URL and interrogates whatever is actually serving it.
#
#   scripts/railway/verify-deployment.sh https://cliora.example.com [output-dir]
#
# Optional, and reported as *skipped with a prerequisite* when absent rather than quietly
# passing:
#   CLIORA_VERIFY_ADMIN / CLIORA_VERIFY_PASSWORD   enable the idle-WebSocket leg, which
#                                                  needs an enrolled node socket
#   CLIORA_VERIFY_IDLE_SECONDS   (default 90)
#
# Exit status is the number of failures. Skips are not failures and are not passes either.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${1:-}"
[ -n "$BASE" ] || { echo "usage: $0 <base-url> [output-dir]" >&2; exit 2; }
BASE="${BASE%/}"
OUT="${2:-$ROOT/artifacts/rw/local}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
REPORT="$OUT/deployment-verification.md"

command -v curl >/dev/null || { echo "curl is required" >&2; exit 2; }

CHECKS=0
FAILURES=0
SKIPS=0
note() { printf '%s\n' "$*" >>"$REPORT"; }
ok()   { CHECKS=$((CHECKS+1)); note "- ok — $*"; echo "ok: $*"; }
fail() { CHECKS=$((CHECKS+1)); FAILURES=$((FAILURES+1)); note "- **FAIL** — $*"; echo "FAIL: $*" >&2; }
skip() { SKIPS=$((SKIPS+1)); note "- _skipped_ — $*"; echo "skip: $*"; }

code_of()    { curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$@"; }
headers_of() { curl -sS -D - -o /dev/null --max-time 30 "$@"; }

: >"$REPORT"
note "# Railway deployment verification"
note ""
note "- target: \`$BASE\`"
note "- generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
note "- curl: $(curl --version | head -1)"
note ""
note "Executed against the running deployment. Nothing here is inferred from"
note "\`deploy/railway/nginx.conf.template\`; the parity of that file with the host edge is a"
note "separate, static check (\`scripts/railway/check-edge-parity.sh\`)."
note ""

# --------------------------------------------------------------------------- #
note "## Reachability"
note ""
edge_body="$(curl -sS --max-time 15 "$BASE/edge-health")"
if [ "$edge_body" = "ok" ]; then
  ok "/edge-health answers from the console service"
else
  fail "/edge-health did not answer 'ok' (got '${edge_body:-nothing}'); the edge itself is not serving"
  note ""
  note "Remaining checks would report the edge's absence, not the deployment's properties."
  note ""
  note "checks: $CHECKS · failures: $FAILURES · skipped: $SKIPS"
  exit "$FAILURES"
fi

# --------------------------------------------------------------------------- #
note ""
note "## TLS and redirect (FR-CONN-002, SEC-005, tech §23 #1)"
note ""
# The redirect rule itself, exercised the way the platform edge exercises it. Testing this
# separately from a real plain-HTTP request matters: the rule is fail-open by construction
# (no X-Forwarded-Proto means no redirect, so platform-internal probes are not redirected
# into a health-check failure), so both halves have to be checked.
redirect_headers="$(headers_of -H 'X-Forwarded-Proto: http' "$BASE/")"
redirect_code="$(printf '%s' "$redirect_headers" | head -1 | awk '{print $2}')"
redirect_target="$(printf '%s' "$redirect_headers" | grep -i '^location:' | tr -d '\r' | awk '{print $2}')"
if [ "$redirect_code" = "301" ] && [ "${redirect_target#https://}" != "$redirect_target" ]; then
  ok "a request marked as plain HTTP is redirected (301 → $redirect_target)"
else
  fail "X-Forwarded-Proto: http produced $redirect_code (location: ${redirect_target:-none}); HTTPS is not enforced"
fi

case "$BASE" in
  https://*)
    host="${BASE#https://}"
    real_code="$(code_of "http://$host/")"
    if [ "$real_code" = "301" ]; then
      ok "a real plain-HTTP request to the public domain is redirected (301)"
    else
      fail "http://$host/ returned $real_code; the platform edge may not be forwarding X-Forwarded-Proto"
    fi
    tls="$(curl -sS -o /dev/null -w '%{ssl_verify_result} %{http_version}' --max-time 30 "$BASE/")"
    case "$tls" in
      "0 "*) ok "the certificate validates (verify_result=0, HTTP/${tls#* })" ;;
      *)     fail "certificate verification returned '$tls'" ;;
    esac
    ;;
  *)
    skip "real plain-HTTP and certificate checks (target is not https; prerequisite: run against the public domain)"
    ;;
esac

# --------------------------------------------------------------------------- #
note ""
note "## Security headers and CSP"
note ""
index_headers="$(headers_of "$BASE/")"
index_code="$(printf '%s' "$index_headers" | head -1 | awk '{print $2}')"
[ "$index_code" = "200" ] && ok "the console is served (200)" || fail "the console returned $index_code"

REQUIRED_HEADERS=(
  strict-transport-security
  x-content-type-options
  referrer-policy
  x-frame-options
  cross-origin-opener-policy
  permissions-policy
  content-security-policy
)
missing=()
for header in "${REQUIRED_HEADERS[@]}"; do
  grep -qi "^${header}:" <<<"$index_headers" || missing+=("$header")
done
if [ ${#missing[@]} -eq 0 ]; then
  ok "all ${#REQUIRED_HEADERS[@]} security headers are present on /"
else
  fail "missing on /: ${missing[*]}"
fi

# Compared against the file that is deployed, not against a copy of the policy written into
# this script — a policy hard-coded here would drift from the config and then assert nothing.
expected_csp="$(grep -o 'Content-Security-Policy "[^"]*"' \
  "$ROOT/deploy/railway/nginx.conf.template" | sed 's/^[^"]*"//; s/"$//' | sort -u | head -1)"
served_csp="$(printf '%s' "$index_headers" | grep -i '^content-security-policy:' |
  tr -d '\r' | sed 's/^[^:]*: //')"
if [ "$served_csp" = "$expected_csp" ]; then
  ok "the served CSP matches deploy/railway/nginx.conf.template"
else
  fail "the served CSP differs from the shipped template"
  note "  - served:   \`$served_csp\`"
  note "  - expected: \`$expected_csp\`"
fi
case "$served_csp" in
  *"worker-src 'self' blob:"*) ok "CSP allows Monaco's blob workers" ;;
  *) fail "CSP has no worker-src blob:; the editor renders blank with only a console error" ;;
esac
external="$(printf '%s' "$served_csp" | grep -oE '(^| )https?://[^ ;]*' | tr '\n' ' ')"
[ -z "$external" ] && ok "CSP names no external origin" || fail "CSP names external origin(s): $external"

grep -qi '^cache-control:.*no-store' <<<"$index_headers" \
  && ok "index.html is not cached" \
  || fail "index.html has no no-store; a browser keeps loading a bundle whose assets a deploy removed"

# The same header set must survive on /assets/, which declares its own add_header and
# therefore discards the server-level set. Checking only / leaves half the regression open.
asset="$(curl -sS --max-time 30 "$BASE/" | grep -oE '/assets/[A-Za-z0-9._-]+\.js' | head -1)"
if [ -n "$asset" ]; then
  asset_headers="$(headers_of "$BASE$asset")"
  asset_missing=()
  for header in "${REQUIRED_HEADERS[@]}"; do
    grep -qi "^${header}:" <<<"$asset_headers" || asset_missing+=("$header")
  done
  if [ ${#asset_missing[@]} -eq 0 ]; then
    ok "security headers survive on $asset"
  else
    fail "missing on $asset: ${asset_missing[*]} (its own add_header discards the server set)"
  fi
  grep -qi 'immutable' <<<"$asset_headers" \
    && ok "hashed assets are cached immutably" \
    || fail "hashed assets are not cached immutably"
else
  fail "no hashed asset found in index.html; the /assets/ header check did not run"
fi

server_header="$(printf '%s' "$index_headers" | grep -i '^server:' | tr -d '\r')"
if printf '%s' "$server_header" | grep -qE '[0-9]+\.[0-9]+'; then
  fail "the Server header leaks a version: '$server_header'"
else
  ok "the Server header carries no version"
fi

# --------------------------------------------------------------------------- #
note ""
note "## Routes that must not be reachable, and routes that must"
note ""
metrics_code="$(code_of "$BASE/api/metrics")"
[ "$metrics_code" = "404" ] \
  && ok "/api/metrics is refused at the edge (404)" \
  || fail "/api/metrics returned $metrics_code; the whole series set is reachable from outside"

health_code="$(code_of "$BASE/healthz")"
[ "$health_code" = "200" ] && ok "/healthz is proxied (200)" || fail "/healthz returned $health_code"

ready_code="$(code_of "$BASE/readyz")"
ready_body="$(curl -sS --max-time 30 "$BASE/readyz")"
if [ "$ready_code" = "200" ]; then
  ok "/readyz is proxied and reports ready (200): \`$ready_body\`"
elif [ "$ready_code" = "503" ]; then
  fail "/readyz reports degraded (503): \`$ready_body\` — database reachability or migration head"
else
  fail "/readyz returned $ready_code"
fi

# Proves the API is proxied *and* answered by Central rather than by the edge.
login_code="$(code_of -X POST "$BASE/api/auth/login" \
  -H 'content-type: application/json' -d '{"username":"nobody","password":"nope"}')"
[ "$login_code" = "401" ] \
  && ok "/api is proxied and answered by Central (401 on bad credentials)" \
  || fail "/api/auth/login returned $login_code, expected 401 from Central"

# --------------------------------------------------------------------------- #
note ""
note "## Release artifacts (FR-INSTALL-002, tech §23 #12)"
note ""
manifest_code="$(code_of "$BASE/api/releases/manifest")"
if [ "$manifest_code" = "200" ]; then
  ok "/api/releases/manifest answers 200 (a daemon can tell 'no update' from 'no endpoint')"
else
  fail "/api/releases/manifest returned $manifest_code; it must never 404"
fi
install_code="$(code_of "$BASE/api/install-script")"
checksums_code="$(code_of "$BASE/api/downloads/checksums.txt")"
if [ "$install_code" = "200" ] && [ "$checksums_code" = "200" ]; then
  ok "the installer and checksums.txt are published"
elif [ "$install_code" = "404" ] && [ "$checksums_code" = "404" ]; then
  skip "artifact publication (both endpoints 404: CLIORA_ARTIFACTS_DIR is empty — the documented pre-RW-08 state; the one-line install command must not be published yet)"
else
  fail "artifact endpoints disagree: install-script=$install_code checksums=$checksums_code"
fi
# Two separate properties, because one request cannot test both.
#
# The first version of this check asked for `/api/downloads/..%2f..%2fetc%2fpasswd` and
# expected 404. It got 200 — and that 200 was the *console's* index.html: nginx decodes
# `%2f` and resolves the dot segments **before** matching a location, so the request becomes
# `/etc/passwd`, falls through to `location /`, and the SPA fallback answers it. Nothing
# leaked, but the check was asserting a status code produced by a component it was not
# aiming at, and would have kept passing if Central's allowlist were removed entirely.
#
# So: (a) prove nothing from the filesystem comes back for an encoded traversal, and
# (b) test Central's allowlist with a name that survives normalization and therefore
# actually reaches it.
traversal_body="$(curl -sS --max-time 30 "$BASE/api/downloads/..%2f..%2fetc%2fpasswd")"
if printf '%s' "$traversal_body" | grep -qE '^(root|daemon|nobody):'; then
  fail "an encoded traversal returned what looks like a system file"
else
  ok "an encoded traversal returns no filesystem content (the edge normalizes it away)"
fi
for name in passwd agentd_1.0.0_linux_riscv.tar.gz checksums.txt.bak; do
  denied_code="$(code_of "$BASE/api/downloads/$name")"
  [ "$denied_code" = "404" ] \
    && ok "/api/downloads/$name is refused by the allowlist (404)" \
    || fail "/api/downloads/$name returned $denied_code; the closed allowlist is not holding"
done

# --------------------------------------------------------------------------- #
note ""
note "## WebSocket path (tech §23 #11)"
note ""
# One request covers two properties: the handshake completing proves a WebSocket traverses
# both proxies, and the 1008 close proves the ws-ticket check still gates it. An unauthorized
# socket that stayed open would be the more alarming result of the two.
ws_result="$(VERIFY_BASE="$BASE" uv run --project "$ROOT/backend" python - <<'PY' 2>&1
import asyncio
import os
import sys
import uuid
from urllib.parse import urlsplit

try:
    from websockets.asyncio.client import connect
except ImportError:  # websockets < 13
    from websockets.client import connect

base = urlsplit(os.environ["VERIFY_BASE"])
scheme = "wss" if base.scheme == "https" else "ws"
url = f"{scheme}://{base.netloc}/ws/sessions/{uuid.uuid4()}/terminal"


async def main() -> int:
    try:
        async with connect(url, open_timeout=20, ping_interval=None) as socket:
            try:
                await asyncio.wait_for(socket.recv(), timeout=10)
            except asyncio.TimeoutError:
                print("OPEN-AND-SILENT")
                return 1
            except Exception:
                pass
        code = socket.close_code
        print(f"CLOSED {code}")
        return 0 if code == 1008 else 1
    except Exception as exc:  # handshake refused outright
        print(f"REFUSED {type(exc).__name__}: {exc}")
        return 2


sys.exit(asyncio.run(main()))
PY
)"
ws_status=$?
case "$ws_result" in
  "CLOSED 1008"*)
    ok "an unticketed terminal socket completes the handshake through both proxies and is then closed 1008" ;;
  "REFUSED"*)
    fail "the terminal WebSocket handshake did not complete through the edge: $ws_result" ;;
  "OPEN-AND-SILENT"*)
    fail "an unticketed terminal socket stayed open; the ws-ticket check is not gating the handshake" ;;
  *)
    fail "unexpected WebSocket result (status $ws_status): $ws_result" ;;
esac

IDLE="${CLIORA_VERIFY_IDLE_SECONDS:-90}"
if [ -n "${CLIORA_VERIFY_ADMIN:-}" ] && [ -n "${CLIORA_VERIFY_PASSWORD:-}" ]; then
  note ""
  note "Holds an authenticated, idle node socket for ${IDLE}s. Two things had to be true"
  note "before this measured anything (learned by \`scripts/p4/verify-edge.sh\`): the socket"
  note "must be **authenticated**, or Central closes it at \`hmac_challenge_ttl_seconds\` (30 s)"
  note "and it reads as a proxy failure; and the client must send no pings, or its own"
  note "keepalive resets the proxy's read timeout and the check passes on any value."
  note ""
  idle_result="$(VERIFY_BASE="$BASE" VERIFY_ADMIN="$CLIORA_VERIFY_ADMIN" \
    VERIFY_PASSWORD="$CLIORA_VERIFY_PASSWORD" VERIFY_IDLE="$IDLE" \
    uv run --project "$ROOT/backend" python "$ROOT/scripts/railway/idle_socket_probe.py" 2>&1)"
  case "$idle_result" in
    SURVIVED*) ok "an idle authenticated WebSocket survived ${IDLE}s through the edge ($idle_result)" ;;
    *)         fail "idle WebSocket check: $idle_result" ;;
  esac
else
  skip "idle-WebSocket survival (prerequisite: CLIORA_VERIFY_ADMIN and CLIORA_VERIFY_PASSWORD, so the probe can enroll a node — an unauthenticated socket measures Central's challenge timeout, not the proxy)"
fi

# --------------------------------------------------------------------------- #
note ""
note "## Body limit (the 8 MiB filesystem contract)"
note ""
# A limit below the contract turns a legal read into a 413 from a component that knows
# nothing about the protocol. A 9 MiB POST exercises the limit without needing a node.
#
# From a file, not an argument: a 9 MiB command line overflows, and the first version of the
# equivalent check in verify-edge.sh reported **ok** on the resulting empty status code — a
# passing check that measured nothing. Hence the numeric validation below.
BODY_FILE="$(mktemp)"
{ printf '{"username":"x","password":"'; head -c $((9 * 1024 * 1024)) /dev/zero | tr '\0' 'x'; printf '"}'; } >"$BODY_FILE"
body_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 60 -X POST "$BASE/api/auth/login" \
  -H 'content-type: application/json' --data-binary "@$BODY_FILE")"
rm -f "$BODY_FILE"
if ! [[ "$body_code" =~ ^[0-9]{3}$ ]]; then
  fail "the 9 MiB body check produced no status code ('$body_code'); it measured nothing"
elif [ "$body_code" = "413" ]; then
  fail "a 9 MiB body was refused with 413; the 8 MiB filesystem contract would break"
else
  ok "a 9 MiB body is not refused by the edge (got $body_code, not 413)"
fi

# --------------------------------------------------------------------------- #
note ""
note "## Not covered here"
note ""
note "- **8 MiB file read through the edge, end to end** — the body limit is checked above,"
note "  but the read path itself needs an enrolled node with a large file in an allowed"
note "  root (RW-11)."
note "- **Deploy drain** — needs a deployment to be triggered while a browser is subscribed;"
note "  the procedure and the log assertions are in \`docs/deployment-railway.md\`."
note "- **Monaco actually rendering** — the CSP is asserted above, but only a browser can"
note "  show the editor is not blank (RW-11)."
note ""
note "checks: $CHECKS · failures: $FAILURES · skipped: $SKIPS"

echo
echo "report: $REPORT"
echo "checks: $CHECKS · failures: $FAILURES · skipped: $SKIPS"
exit "$FAILURES"
