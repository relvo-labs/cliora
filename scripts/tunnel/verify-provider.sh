#!/usr/bin/env bash
# PG-01 — verify what the tunnel provider (Pinggy) actually does.
#
# This exists because the plan (plan/11) is built on twelve claims about a third party, and a
# third party's behaviour cannot be read out of its documentation: two of the twelve turned out
# to contradict the docs when this script was first run (2026-08-01) — see §"findings" below.
# Every check prints the value it observed, so the output is evidence rather than a verdict.
#
# Usage:
#   scripts/tunnel/verify-provider.sh                 # free tier only
#   PINGGY_TOKEN=xxxx scripts/tunnel/verify-provider.sh   # also runs the Pro checks
#   OUT_DIR=artifacts/pg/local scripts/tunnel/verify-provider.sh
#
# It starts real tunnels to a *throwaway local echo server*, which means it briefly publishes a
# public URL. It never points a tunnel at anything but that echo server, and it kills every
# tunnel it starts (including on failure, via the EXIT trap).
#
# findings that changed the plan (2026-08-01):
#   * A PTY must NOT be requested. With -t the service renders a full-screen ANSI TUI and the
#     URL becomes unparseable; without a PTY stdout is four clean lines.
#   * An INVALID token is not rejected. The service silently downgrades to an anonymous free
#     tunnel ("You are not authenticated."), so authorization failure has to be detected by
#     reading stdout, not by an exit code.
#   * The free-tier hostname embeds the node's public IP (e.g. xxxxx-114-32-49-189.…), which is
#     a disclosure the platform has to surface in its UI.
set -uo pipefail

PORT="${PORT:-18899}"
OUT_DIR="${OUT_DIR:-artifacts/pg/local}"
KNOWN_HOSTS="${KNOWN_HOSTS:-daemon/internal/tunnel/pinggy_known_hosts}"
FREE_HOST="${FREE_HOST:-free.pinggy.io}"
PRO_HOST="${PRO_HOST:-pro.pinggy.io}"
WAIT_SECONDS="${WAIT_SECONDS:-20}"

WORK="$(mktemp -d)"
PIDS=()
FAILED=0
declare -A RESULT

cleanup() {
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null; done
  [ -n "${ECHO_PID:-}" ] && kill "$ECHO_PID" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT

ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; RESULT["$2"]="pass"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; RESULT["$2"]="fail"; FAILED=1; }
skip() { printf '  \033[33mSKIP\033[0m %s\n' "$1"; RESULT["$2"]="skip"; }
note() { printf '       %s\n' "$1"; }

# --- the throwaway target: an echo server that reports what the app actually receives ---
start_echo_server() {
  cat > "$WORK/echo.py" <<'PY'
import http.server, json, socketserver, sys
PORT = int(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _dump(self):
        body = json.dumps({"path": self.path, "headers": dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = do_POST = do_HEAD = _dump
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), H) as s:
    s.serve_forever()
PY
  python3 "$WORK/echo.py" "$PORT" & ECHO_PID=$!
  sleep 1
}

# start_tunnel <outfile> <user@host> [remote options...] -> echoes the pid
start_tunnel() {
  local out="$1" dest="$2"; shift 2
  : > "$out"
  # No -t / -tt: a PTY turns the URL banner into an ANSI TUI (see findings above).
  setsid ssh -p 443 \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS" \
    -o GlobalKnownHostsFile=/dev/null \
    -o IdentitiesOnly=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -R "0:localhost:$PORT" "$dest" "$@" \
    > "$out" 2> "$out.err" < /dev/null &
  local pid=$!
  PIDS+=("$pid")
  echo "$pid"
}

wait_for_url() {  # <outfile> -> echoes the https URL, empty on timeout
  local out="$1" i url
  for ((i = 0; i < WAIT_SECONDS; i++)); do
    url="$(grep -oE 'https://[a-z0-9-]+\.(run\.pinggy-free\.link|free\.pinggy\.net|pinggy\.link)' "$out" 2>/dev/null | head -1)"
    [ -n "$url" ] && { echo "$url"; return 0; }
    sleep 1
  done
  return 1
}

echo "== provider verification: $(date -u +%Y-%m-%dT%H:%M:%SZ) =="
mkdir -p "$OUT_DIR"
start_echo_server

# 1. non-interactive start (BatchMode) --------------------------------------------------------
echo "[1] non-interactive start (BatchMode=yes, no PTY, pinned host key)"
P="$(start_tunnel "$WORK/t1.out" "http@$FREE_HOST" x:https x:xff)"
URL="$(wait_for_url "$WORK/t1.out" || true)"
if [ -n "$URL" ]; then ok "tunnel established without a password prompt: $URL" batchmode
else bad "no URL within ${WAIT_SECONDS}s; stderr: $(grep -v '^debug' "$WORK/t1.out.err" | head -2 | tr '\n' ' ')" batchmode; fi

# 2. URL banner is parseable without a PTY ----------------------------------------------------
echo "[2] URL banner shape"
if [ -n "$URL" ]; then
  note "stdout was: $(tr '\n' '|' < "$WORK/t1.out" | cut -c1-200)"
  if grep -qE '^\s*https://' "$WORK/t1.out"; then ok "https URL appears on its own line on stdout" url_shape
  else bad "no bare https:// line on stdout" url_shape; fi
  if echo "$URL" | grep -qE '[0-9]+-[0-9]+-[0-9]+-[0-9]+\.'; then
    note "DISCLOSURE: the hostname embeds this node's public IP — the UI must say so"
    RESULT[url_embeds_ip]="yes"
  else RESULT[url_embeds_ip]="no"; fi
else skip "no URL to inspect" url_shape; fi

# 3. header passthrough, Host, X-Forwarded-* --------------------------------------------------
echo "[3] what the local app receives"
if [ -n "$URL" ]; then
  BODY="$(curl -s --max-time 25 -H 'Cookie: probe=cookievalue' -H 'Authorization: Bearer probetoken' "$URL/probe?q=1" || true)"
  if [ -n "$BODY" ]; then
    HOST_SEEN="$(echo "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headers"].get("Host",""))' 2>/dev/null)"
    COOKIE_SEEN="$(echo "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headers"].get("Cookie",""))' 2>/dev/null)"
    AUTH_SEEN="$(echo "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headers"].get("Authorization",""))' 2>/dev/null)"
    XFF_SEEN="$(echo "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headers"].get("X-Forwarded-For",""))' 2>/dev/null)"
    note "Host: $HOST_SEEN"
    note "X-Forwarded-For: $XFF_SEEN"
    RESULT[host_seen_by_app]="$HOST_SEEN"
    if [ "$HOST_SEEN" = "127.0.0.1:$PORT" ] || [ "$HOST_SEEN" = "localhost:$PORT" ]; then
      ok "Host is rewritten to the local address" host_header
    else
      ok "Host is the tunnel domain — dev servers with host allowlists (Vite, Next) will refuse it" host_header
      note "mitigation: the platform offers an opt-in Host rewrite (remote option u:Host:...)"
    fi
    [ "$COOKIE_SEEN" = "probe=cookievalue" ] && ok "Cookie reaches the app unchanged" cookie_passthrough \
      || bad "Cookie did not arrive (got: '$COOKIE_SEEN')" cookie_passthrough
    [ "$AUTH_SEEN" = "Bearer probetoken" ] && ok "Authorization reaches the app unchanged" auth_passthrough \
      || bad "Authorization did not arrive (got: '$AUTH_SEEN')" auth_passthrough
    [ -n "$XFF_SEEN" ] && ok "x:xff supplies the caller IP" xff || bad "no X-Forwarded-For" xff
  else bad "no response through the tunnel" host_header; fi
else skip "no tunnel" host_header; fi

# 4. x:https refuses plaintext ----------------------------------------------------------------
echo "[4] x:https"
if [ -n "$URL" ]; then
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "${URL/https:/http:}/plain" || true)"
  case "$CODE" in
    301|302|307|308) ok "plaintext request is redirected ($CODE)" x_https ;;
    40*) ok "plaintext request is refused ($CODE)" x_https ;;
    *)   bad "plaintext request returned $CODE — plaintext ingress is open" x_https ;;
  esac
fi
kill "$P" 2>/dev/null

# 5. basic auth (does it need Pro?) -----------------------------------------------------------
echo "[5] basic auth on this tier"
P2="$(start_tunnel "$WORK/t2.out" "${PINGGY_TOKEN:+$PINGGY_TOKEN@}${PINGGY_TOKEN:+$PRO_HOST}${PINGGY_TOKEN:-http@$FREE_HOST}" x:https b:probeuser:probepass)"
URL2="$(wait_for_url "$WORK/t2.out" || true)"
if [ -n "$URL2" ]; then
  NO="$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "$URL2/p" || true)"
  BADC="$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 -u probeuser:wrong "$URL2/p" || true)"
  GOOD="$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 -u probeuser:probepass "$URL2/p" || true)"
  note "no creds=$NO  wrong creds=$BADC  correct creds=$GOOD"
  if [ "$NO" = "401" ] && [ "$BADC" = "401" ] && [ "$GOOD" = "200" ]; then
    ok "basic auth is enforced by the provider on this tier" basic_auth
  else
    bad "basic auth did not behave as required (401/401/200 expected)" basic_auth
  fi
else skip "no tunnel for the basic-auth check" basic_auth; fi
kill "$P2" 2>/dev/null

# 6. concurrency on one identity --------------------------------------------------------------
echo "[6] two concurrent tunnels on the same identity"
PA="$(start_tunnel "$WORK/t3.out" "${PINGGY_TOKEN:+$PINGGY_TOKEN@$PRO_HOST}${PINGGY_TOKEN:-http@$FREE_HOST}" x:https)"
UA="$(wait_for_url "$WORK/t3.out" || true)"
PB="$(start_tunnel "$WORK/t4.out" "${PINGGY_TOKEN:+$PINGGY_TOKEN@$PRO_HOST}${PINGGY_TOKEN:-http@$FREE_HOST}" x:https)"
UB="$(wait_for_url "$WORK/t4.out" || true)"
if [ -n "$UA" ] && [ -n "$UB" ] && kill -0 "$PA" 2>/dev/null && kill -0 "$PB" 2>/dev/null; then
  ok "both tunnels are alive: $UA and $UB" concurrency
  note "the platform's concurrent_budget must still match the paid plan's real limit"
else
  bad "the second tunnel displaced or blocked the first — concurrent_budget must be 1" concurrency
  grep -iE 'too many|limit|exceed|already' "$WORK"/t3.out "$WORK"/t4.out | head -3 | while read -r l; do note "$l"; done
fi
kill "$PA" "$PB" 2>/dev/null

# 7. invalid credential ----------------------------------------------------------------------
echo "[7] invalid credential"
P5="$(start_tunnel "$WORK/t5.out" "AAAAinvalidtoken0000@$PRO_HOST" x:https)"
U5="$(wait_for_url "$WORK/t5.out" || true)"
if [ -n "$U5" ]; then
  if grep -qi 'not authenticated' "$WORK/t5.out"; then
    ok "an invalid credential DOWNGRADES to anonymous instead of failing" invalid_credential
    note "detection must therefore read stdout: 'You are not authenticated.' while a credential"
    note "was supplied means TUNNEL_PROVIDER_UNAUTHORIZED, and the tunnel must be torn down"
  else
    bad "invalid credential produced a tunnel with no downgrade banner — no way to detect it" invalid_credential
  fi
else
  ok "invalid credential is rejected outright (exit without a URL)" invalid_credential
fi
kill "$P5" 2>/dev/null

# 8. host key pinning ------------------------------------------------------------------------
echo "[8] host key pinning"
printf '[%s]:443 ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7wrongkeywrongkeywrongkeywrongkey\n' "$FREE_HOST" > "$WORK/kh_bad"
timeout 25 ssh -p 443 -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$WORK/kh_bad" -o GlobalKnownHostsFile=/dev/null \
  -R "0:localhost:$PORT" "http@$FREE_HOST" x:https > /dev/null 2> "$WORK/kh_bad.err"
if grep -qi 'host key verification failed' "$WORK/kh_bad.err"; then
  ok "a wrong pinned key refuses the connection ('Host key verification failed.')" host_key_mismatch
else
  bad "a wrong pinned key did NOT stop the connection" host_key_mismatch
fi
: > "$WORK/kh_empty"
timeout 25 ssh -p 443 -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$WORK/kh_empty" -o GlobalKnownHostsFile=/dev/null \
  -R "0:localhost:$PORT" "http@$FREE_HOST" x:https > /dev/null 2> "$WORK/kh_empty.err"
if grep -qi 'host key verification failed' "$WORK/kh_empty.err"; then
  ok "an empty known_hosts refuses the connection (no silent trust-on-first-use)" host_key_missing
else
  bad "an empty known_hosts did NOT stop the connection" host_key_missing
fi

# 9. the pinned file itself ------------------------------------------------------------------
echo "[9] pinned key file"
if [ -s "$KNOWN_HOSTS" ] && ssh-keygen -lf "$KNOWN_HOSTS" > "$WORK/fp.txt" 2>/dev/null; then
  ok "$KNOWN_HOSTS parses; $(wc -l < "$WORK/fp.txt") key line(s)" pinned_file
  while read -r l; do note "$l"; done < "$WORK/fp.txt"
else
  bad "$KNOWN_HOSTS is missing, empty or unparseable" pinned_file
fi

# --- report ---------------------------------------------------------------------------------
{
  echo "{"
  echo "  \"checked_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"free_host\": \"$FREE_HOST\","
  echo "  \"pro_token_supplied\": $([ -n "${PINGGY_TOKEN:-}" ] && echo true || echo false),"
  echo "  \"results\": {"
  first=1
  for k in "${!RESULT[@]}"; do
    [ $first -eq 0 ] && echo ","
    printf '    "%s": "%s"' "$k" "${RESULT[$k]}"
    first=0
  done
  echo
  echo "  },"
  echo "  \"failed\": $FAILED"
  echo "}"
} > "$OUT_DIR/provider-verify.json"

echo
echo "== wrote $OUT_DIR/provider-verify.json =="
[ $FAILED -eq 0 ] && echo "all executed checks passed" || echo "SOME CHECKS FAILED"
exit $FAILED
