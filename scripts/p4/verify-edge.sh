#!/usr/bin/env bash
# Execute the edge configuration instead of reading it (P4-12 / tech §23 #1).
#
# This exists because `docs/p4-report.md` §4.1 recorded a real gap: every claim about
# nginx — HTTP redirects, the CSP, the WebSocket timeout — rested on having read
# `deploy/nginx/nginx.conf`. Two of the most likely regressions would both have shipped
# green:
#
#   * a CSP that blocks Monaco's blob workers, so the editor renders blank;
#   * `proxy_read_timeout` back at nginx's 60 s default, so every idle terminal dies on
#     the minute and it looks like a Cliora bug.
#
# Writing that gap down was honest but it did not close it. The first run of this script
# also found that the config **did** proxy `/api/metrics` while a comment two lines above
# claimed it was "deliberately not exposed here" — a comment is not a rule.
#
# Brings up the real nginx image with the real config, a self-signed certificate and the
# real built console, in front of a throwaway Central, then asserts against it over the
# wire.
#
#   scripts/p4/verify-edge.sh [output-dir]      # default artifacts/p4/local
#
# Requires: docker, uv, a built frontend (`npm run build --prefix frontend`) or it builds
# one. The idle-WebSocket assertion takes just over 60 s by construction — that is the
# threshold being tested, so it cannot be shortened.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

OUT="${1:-$ROOT/artifacts/p4/local}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"          # absolute: subshells below cd elsewhere
REPORT="$OUT/edge-verification.md"

HTTP_PORT="${EDGE_HTTP_PORT:-8880}"
HTTPS_PORT="${EDGE_HTTPS_PORT:-8443}"
CENTRAL_PORT="${EDGE_CENTRAL_PORT:-8000}"   # nginx.conf hard-codes backend:8000
PG_CONTAINER="${PG_CONTAINER:-cliora-pg}"
PG_USER="${PG_USER:-cliora}"
NGINX_NAME="cliora-edge-verify"
DB="cliora_edge_$(date -u +%Y%m%d%H%M%S)"
TLS_DIR="$(mktemp -d)"
FAILURES=0
CHECKS=0

note() { printf '%s\n' "$*" >>"$REPORT"; }
ok()   { CHECKS=$((CHECKS+1)); note "- ok — $*"; echo "ok: $*"; }
fail() { CHECKS=$((CHECKS+1)); FAILURES=$((FAILURES+1)); note "- **FAIL** — $*"; echo "FAIL: $*" >&2; }

cleanup() {
  docker rm -f "$NGINX_NAME" >/dev/null 2>&1
  pkill -f "uvicorn app.main:app --host 0.0.0.0 --port $CENTRAL_PORT" 2>/dev/null
  for _ in $(seq 1 20); do pgrep -f "port $CENTRAL_PORT" >/dev/null || break; sleep 0.25; done
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$DB\"" >/dev/null 2>&1
  rm -rf "$TLS_DIR"
}
trap cleanup EXIT

command -v docker >/dev/null || { echo "docker is required" >&2; exit 2; }
docker exec "$PG_CONTAINER" true 2>/dev/null || { echo "PostgreSQL container '$PG_CONTAINER' is not running" >&2; exit 2; }

: >"$REPORT"
note "# Edge verification (nginx executed, not reviewed)"
note ""
note "- generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
note "- config under test: \`deploy/nginx/nginx.conf\` (the file the deployment ships)"
note "- nginx: $(docker run --rm nginx:1.27-alpine nginx -v 2>&1 | tr -d '\n')"
note ""

# --- a throwaway Central on the port nginx expects ---
# Bound to 0.0.0.0, not 127.0.0.1: nginx runs in a container and reaches the host through
# `--add-host backend:host-gateway`, so a loopback-only listener answers nothing and every
# proxied route returns 502. (This is a property of the test rig, not of the deployment —
# in compose both are on the same bridge network.)
if pgrep -f "port $CENTRAL_PORT" >/dev/null; then
  echo "port $CENTRAL_PORT is in use; the checks would target another process" >&2
  exit 2
fi
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
  -c "CREATE DATABASE \"$DB\" OWNER $PG_USER" >/dev/null || exit 1
DB_URL="postgresql+asyncpg://${PG_USER}:cliora@127.0.0.1:5432/${DB}"
(cd backend && CLIORA_DATABASE_URL="$DB_URL" uv run --project . alembic upgrade head) \
  >"$OUT/edge-setup.log" 2>&1 || { fail "could not migrate the edge database"; exit 1; }
# `--ws-ping-interval 600`: uvicorn's default is **20 s**, and those server pings travel
# upstream→client through nginx and reset `proxy_read_timeout` on every one. With the
# default the idle check below could never fail — verified by setting
# `proxy_read_timeout 20s` and watching it still pass. Raising the ping interval above the
# idle window makes the connection genuinely idle, so the only thing that can close it is
# the proxy, which is what the check claims to measure.
#
# Production keeps the 20 s ping and is therefore *strictly more robust* than what is
# tested here. The invariant that actually matters is `proxy_read_timeout > ws_ping_interval`,
# and this tests the weaker condition on purpose.
(cd backend && CLIORA_DATABASE_URL="$DB_URL" \
  uv run --project . uvicorn app.main:app --host 0.0.0.0 --port "$CENTRAL_PORT" \
  --ws-ping-interval 600 --ws-ping-timeout 600 \
  --log-level warning >"$OUT/edge-central.log" 2>&1) &
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$CENTRAL_PORT/readyz" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$CENTRAL_PORT/readyz" >/dev/null 2>&1 \
  && ok "throwaway Central is up behind the edge" \
  || { fail "throwaway Central did not start"; exit 1; }

# --- certificate and console build ---
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout "$TLS_DIR/privkey.pem" -out "$TLS_DIR/fullchain.pem" \
  -subj "/CN=cliora.test" -addext "subjectAltName=DNS:cliora.test,DNS:localhost,IP:127.0.0.1" \
  >/dev/null 2>&1 && ok "self-signed certificate generated" || fail "openssl failed"

if [ ! -d frontend/dist ]; then
  echo "==> building the console (frontend/dist is absent)"
  npm run build --prefix frontend >"$OUT/edge-build.log" 2>&1 \
    && ok "console built" || fail "console build failed (see edge-build.log)"
fi

# --- the real nginx image, the real config ---
# host-gateway makes `backend` resolve to the host, so the upstream line in the shipped
# config is exercised verbatim rather than rewritten for the test.
docker run -d --name "$NGINX_NAME" \
  --add-host "backend:host-gateway" \
  -p "127.0.0.1:$HTTP_PORT:80" -p "127.0.0.1:$HTTPS_PORT:443" \
  -v "$ROOT/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$TLS_DIR:/etc/nginx/tls:ro" \
  -v "$ROOT/frontend/dist:/usr/share/nginx/html:ro" \
  nginx:1.27-alpine >/dev/null 2>&1

for _ in $(seq 1 40); do
  curl -sS -o /dev/null "http://127.0.0.1:$HTTP_PORT/" 2>/dev/null && break
  sleep 0.5
done
if docker ps --filter "name=$NGINX_NAME" --filter "status=running" -q | grep -q .; then
  ok "nginx started with the shipped configuration"
else
  fail "nginx did not start: $(docker logs "$NGINX_NAME" 2>&1 | tail -5)"
  exit 1
fi

BASE="https://127.0.0.1:$HTTPS_PORT"
CURL=(curl -sS -k --resolve "cliora.test:$HTTPS_PORT:127.0.0.1")

note ""
note "## Checks"
note ""

# --- 1. HTTP is redirected, never served ---
code=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HTTP_PORT/anything")
location=$(curl -sSI "http://127.0.0.1:$HTTP_PORT/anything" | grep -i '^location:' | tr -d '\r')
[ "$code" = "301" ] && ok "HTTP returns 301 (got $code, $location)" \
                    || fail "HTTP returned $code, expected 301"
grep -qi 'https://' <<<"$location" \
  && ok "the redirect target is https" \
  || fail "the redirect does not point at https: '$location'"

# ACME must survive the redirect, or a certificate renewal cannot complete.
acme=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HTTP_PORT/.well-known/acme-challenge/x")
[ "$acme" != "301" ] && ok "the ACME path is not redirected (got $acme)" \
                     || fail "the ACME path is redirected; certificate renewal would fail"

# --- 2. Security headers arrive verbatim ---
headers=$("${CURL[@]}" -D - -o /dev/null "$BASE/")
check_header() {
  local name="$1" expect="$2"
  local value
  value=$(grep -i "^$name:" <<<"$headers" | head -1 | tr -d '\r')
  if grep -qi "$expect" <<<"$value"; then
    ok "$name present ($(cut -c1-70 <<<"$value"))"
  else
    fail "$name missing or wrong: '${value:-absent}' (expected to contain '$expect')"
  fi
}
check_header "strict-transport-security" "max-age=31536000"
check_header "x-content-type-options" "nosniff"
check_header "x-frame-options" "DENY"
check_header "referrer-policy" "strict-origin"
check_header "content-security-policy" "default-src 'self'"

# --- 3. The CSP clauses that are load-bearing ---
csp=$(grep -i '^content-security-policy:' <<<"$headers" | tr -d '\r')
# Monaco instantiates language workers from blob: URLs. Without this the editor renders
# blank with only a console error — the single most likely CSP regression.
grep -q "worker-src 'self' blob:" <<<"$csp" \
  && ok "CSP allows Monaco's blob workers" \
  || fail "CSP has no 'worker-src self blob:'; the editor would render blank"
grep -q "frame-ancestors 'none'" <<<"$csp" \
  && ok "CSP forbids framing" || fail "CSP allows framing"
grep -q "object-src 'none'" <<<"$csp" \
  && ok "CSP forbids plugins" || fail "CSP allows object-src"
# No external origin anywhere. `wss:`/`ws:` in connect-src are schemes, not hosts.
# Gated on the header existing. In the first run this check *passed* while the CSP was
# absent altogether: "no external origin" is trivially true of a header that never
# arrived, and a vacuous pass on a security control is worse than a failure.
if [ -z "$csp" ]; then
  fail "the external-origin check did not run: no CSP header was present at all"
else
  external=$(grep -oE 'https?://[A-Za-z0-9.-]+' <<<"$csp" | sort -u)
  [ -z "$external" ] && ok "CSP names no external origin" \
                     || fail "CSP names external origin(s): $external"
fi

# The same set must survive on `/assets/`, which also declares its own `add_header` and
# therefore also discards the server-level set. Checking only `/` would leave half the
# regression uncovered.
asset=$("${CURL[@]}" -sS "$BASE/" | grep -oE '/assets/[A-Za-z0-9._-]+\.js' | head -1)
if [ -n "$asset" ]; then
  asset_headers=$("${CURL[@]}" -D - -o /dev/null "$BASE$asset")
  grep -qi '^x-content-type-options:' <<<"$asset_headers" \
    && ok "security headers survive on $asset" \
    || fail "security headers are absent on $asset (its add_header discards the server set)"
  grep -qi 'immutable' <<<"$asset_headers" \
    && ok "hashed assets are cached immutably" || fail "hashed assets are not cached immutably"
else
  fail "could not find a hashed asset in index.html; the header check on /assets/ did not run"
fi

# --- 4. /api/metrics is refused at the edge ---
# `location /api/` is a prefix match, so without an exact-match block this proxies
# straight through. It did, while a comment claimed otherwise.
metrics=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/api/metrics")
[ "$metrics" = "404" ] && ok "/api/metrics is refused at the edge (404)" \
  || fail "/api/metrics returned $metrics; the whole series set is reachable from outside"

# --- 5. The API and the console are actually served through the proxy ---
ready=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/readyz")
[ "$ready" = "200" ] && ok "/readyz is proxied (200)" || fail "/readyz returned $ready"
login=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/login" \
  -H 'content-type: application/json' -d '{"username":"nobody","password":"nope"}')
[ "$login" = "401" ] && ok "/api is proxied and answers from Central (401 on bad credentials)" \
  || fail "/api/auth/login returned $login, expected 401 from Central"
index=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/")
[ "$index" = "200" ] && ok "the console is served (200)" || fail "the console returned $index"
# index.html must never be cached, or a browser keeps loading a bundle whose assets a
# deploy has already removed.
cache=$("${CURL[@]}" -D - -o /dev/null "$BASE/" | grep -i '^cache-control:' | tr -d '\r')
grep -qi 'no-store' <<<"$cache" && ok "index.html is not cached ($cache)" \
                                || fail "index.html cache policy is '$cache', expected no-store"

# --- 6. A genuinely idle WebSocket survives past nginx's 60 s default ---
# The reason this script is slow. Nothing short of holding a real idle connection for longer
# than the timeout can distinguish the two configurations, so the ~70 s cannot be shortened.
#
# Note what this does *not* claim: that a 60 s default would kill idle terminals in
# production. It would not — uvicorn's 20 s server ping resets the timeout on every one. The
# check below deliberately removes that ping so the proxy is the only thing left that can
# close the connection, i.e. it tests a weaker condition than production actually runs.
note ""
note "### Idle WebSocket"
note ""
IDLE="${EDGE_IDLE_SECONDS:-70}"
note "Holds a **fully authenticated, idle** node socket for ${IDLE}s through the proxy."
note "nginx's default \`proxy_read_timeout\` is 60 s, so a run that passes at ${IDLE}s cannot"
note "be passing on the default."
note ""
note "Two things had to be true before this check measured anything:"
note ""
note "1. **the socket must be authenticated.** The first version used an unauthenticated one"
note "   and it closed at exactly **30 s** — \`hmac_challenge_ttl_seconds\`, i.e. *Central*"
note "   timing out a node that never answered its challenge. That measured Central, not"
note "   nginx, and read as an nginx failure."
note "2. **the server's WebSocket keepalive must be out of the way.** uvicorn pings every"
note "   **20 s** by default, and those pings reset \`proxy_read_timeout\` on every one — so"
note "   the check passed even with \`proxy_read_timeout 20s\`, which was confirmed by"
note "   actually setting it. Central therefore runs with \`--ws-ping-interval 600\` here."
note ""
note "The real invariant is \`proxy_read_timeout > ws_ping_interval\`; production keeps the"
note "20 s ping and is strictly more robust than the condition tested below."

# An admin, so the check can mint an enrollment token and register a node.
EDGE_ADMIN_PW="Edge-$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
(cd backend && CLIORA_DATABASE_URL="$DB_URL" uv run --project . python -m app.bootstrap \
  create-admin --username edgeadmin --password "$EDGE_ADMIN_PW") >>"$OUT/edge-setup.log" 2>&1 \
  && ok "admin created for the idle-socket check" || fail "could not create the edge admin"

ws_result=$(EDGE_HTTP="http://127.0.0.1:$CENTRAL_PORT" \
            EDGE_WSS="wss://127.0.0.1:$HTTPS_PORT" \
            EDGE_ADMIN=edgeadmin EDGE_PW="$EDGE_ADMIN_PW" EDGE_IDLE="$IDLE" \
  uv run --project backend python - <<'PY_IDLE' 2>&1
"""Hold an authenticated, idle daemon socket open through nginx.

Setup goes straight to Central over plain HTTP — enrolling a node is not what is under
test, the proxy is. Only the WebSocket goes through the edge, and only that connection
uses an unverified TLS context (the certificate is self-signed by this script). The
insecure context is deliberately local to this file rather than added as an option to
`scripts/p4/load/_common.py`, so no "skip verification" switch exists in the load harness.
"""
import asyncio, base64, json, os, ssl, sys, time, urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

try:
    from websockets.asyncio.client import connect
except ImportError:
    from websockets.client import connect

HTTP = os.environ["EDGE_HTTP"]
DOMAIN = b"cliora-node-auth-v1\n"


def post(path, body, token=None):
    request = urllib.request.Request(
        f"{HTTP}{path}", data=json.dumps(body).encode(), method="POST"
    )
    request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


async def main() -> int:
    token = post("/api/auth/login",
                 {"username": os.environ["EDGE_ADMIN"], "password": os.environ["EDGE_PW"]}
                 )["tokens"]["access_token"]
    enrollment = post("/api/enrollment-tokens", {"ttl_seconds": 600, "max_uses": 2}, token)["token"]

    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    ).decode()
    node_id = post("/api/nodes/register", {
        "token": enrollment, "name": "edge-idle", "hostname": "edge.idle",
        "os": "linux", "os_version": "6.0", "architecture": "amd64",
        "daemon_version": "0.0.0-edge", "run_user": "agentd", "public_key": public,
        "runtimes": [], "workspace_roots": [],
    })["node_id"]

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE          # self-signed, generated by this script

    url = f"{os.environ['EDGE_WSS']}/ws/nodes/{node_id}"
    # ping_interval=None: keepalive frames would keep the connection non-idle from nginx's
    # point of view, which is exactly the condition under test.
    async with connect(url, ssl=context, open_timeout=30, ping_interval=None) as socket:
        challenge = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        if challenge["type"] != "node.challenge":
            print(f"unexpected first frame: {challenge['type']}")
            return 1
        challenge_id, nonce = challenge["request_id"], challenge["payload"]["nonce"]
        signature = base64.b64encode(
            key.sign(DOMAIN + f"{node_id}\n{challenge_id}\n{nonce}".encode())
        ).decode()
        await socket.send(json.dumps({
            "version": 1, "type": "node.auth", "request_id": challenge_id,
            "node_id": node_id, "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"challenge_id": challenge_id, "signature": signature},
        }))
        authenticated = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        if authenticated["type"] != "node.authenticated":
            print(f"auth rejected: {authenticated}")
            return 1

        # Now go silent. No heartbeat, no ping. Central's control loop waits without a
        # timeout once authenticated, so anything that closes this is the proxy.
        idle = float(os.environ["EDGE_IDLE"])
        started = time.monotonic()
        try:
            await asyncio.wait_for(socket.recv(), timeout=idle)
            print("received an unexpected frame while idle")
            return 1
        except asyncio.TimeoutError:
            pass
        except Exception as error:
            print(f"closed after {time.monotonic() - started:.1f}s idle: {type(error).__name__}")
            return 1

        try:
            await asyncio.wait_for(socket.ping(), timeout=10)
        except Exception as error:
            print(f"dead after {time.monotonic() - started:.1f}s idle: {type(error).__name__}")
            return 1
        print(f"alive and responsive after {time.monotonic() - started:.1f}s fully idle")
        return 0


sys.exit(asyncio.run(main()))
PY_IDLE
)
if [ $? -eq 0 ]; then
  ok "an authenticated idle WebSocket survives ${IDLE}s through the proxy — $ws_result"
else
  fail "the idle WebSocket did not survive ${IDLE}s: $ws_result"
fi

# --- 7. Body limit is at or above the filesystem contract ---
# nginx's client_max_body_size must not be the thing that refuses a legal 8 MiB read.
# From a file: a 9 MiB argument overflows the command line, and the first version of this
# check reported **ok** on the resulting empty status code — a passing check that had
# measured nothing, which is precisely what this script exists to prevent. The status is
# now validated as a number before being judged.
BODY_FILE="$(mktemp)"
{ printf '{"username":"x","password":"'; head -c $((9 * 1024 * 1024)) /dev/zero | tr '\0' 'x'; printf '"}'; } >"$BODY_FILE"
size=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/login" \
  -H 'content-type: application/json' --data-binary "@$BODY_FILE")
rm -f "$BODY_FILE"
if ! [[ "$size" =~ ^[0-9]{3}$ ]]; then
  fail "the 9 MiB body check produced no status code ('$size'); it measured nothing"
elif [ "$size" = "413" ]; then
  fail "the edge refused a 9 MiB body with 413; the 8 MiB filesystem contract would break"
else
  ok "a 9 MiB body is not refused by the edge (got $size, not 413)"
fi

note ""
note "## Verdict"
note ""
if [ "$FAILURES" -eq 0 ]; then
  note "**PASS** — $CHECKS checks, executed against a running nginx using the shipped"
  note "configuration file. This closes the \`docs/p4-report.md\` §4.1 gap for the"
  note "properties listed above."
else
  note "**FAIL** — $FAILURES of $CHECKS checks failed."
fi

echo
echo "report: $REPORT"
[ "$FAILURES" -eq 0 ] || exit 1
