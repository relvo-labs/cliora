#!/usr/bin/env bash
# Execute the Railway console edge's client-IP contract in Docker (#184). No Railway access.
#
# Runs the real template and renderer in nginx:1.30-alpine in front of an echo "Central"
# that reports the forwarding headers it receives, then asserts:
#   railway-edge  -> a caller's X-Real-IP is the resolved client (Railway's edge overwrites
#                    it in production), and Central receives exactly that one address in
#                    both X-Real-IP and X-Forwarded-For (overwritten, never appended), on the
#                    API and WebSocket locations; without the header, the socket peer;
#   numeric list  -> X-Real-IP from a peer outside the list is ignored;
#   0.0.0.0/0, ::/0, empty -> the console refuses to start.
#
#   scripts/railway/edge-trust-smoke.sh [nginx-image]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${1:-nginx:1.30-alpine}"
ID="cliora-edge-trust-$$"
WORK="$(mktemp -d)"
FAILURES=0
cleanup() {
  docker rm -f "$ID-console" "$ID-central" >/dev/null 2>&1 || true
  docker network rm "$ID" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
ok()   { printf 'ok: %s\n' "$*"; }
fail() { FAILURES=$((FAILURES + 1)); printf 'FAIL: %s\n' "$*" >&2; }

mkdir -p "$WORK/html"
echo '<!doctype html><title>x</title>' >"$WORK/html/index.html"
cat >"$WORK/central.conf" <<'CONF'
events {}
http {
    server {
        listen 8080;
        location / {
            default_type text/plain;
            return 200 "xri=$http_x_real_ip xff=$http_x_forwarded_for\n";
        }
    }
}
CONF
docker network create "$ID" >/dev/null
docker run -d --name "$ID-central" --network "$ID" --network-alias central \
  -v "$WORK/central.conf:/etc/nginx/nginx.conf:ro" "$IMAGE" >/dev/null

console() { # <CLIORA_TRUSTED_PROXY_CIDRS> [docker run args...]
  local trust="$1"; shift
  docker run --name "$ID-console" --network "$ID" "$@" \
    -v "$ROOT/deploy/railway/nginx.conf.template:/etc/nginx/templates/nginx.conf.template:ro" \
    -v "$ROOT/deploy/railway/19-trusted-proxies.sh:/docker-entrypoint.d/19-trusted-proxies.sh:ro" \
    -v "$WORK/html:/usr/share/nginx/html:ro" \
    -e NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx -e NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    -e PORT=8080 -e CLIORA_BACKEND_HOST=central -e CLIORA_BACKEND_PORT=8080 \
    -e CLIORA_TRUSTED_PROXY_CIDRS="$trust" "$IMAGE"
}
get() { # <path> [header...]; the request comes from 127.0.0.1 inside the console container
  local path="$1"; shift
  local args=()
  for header in "$@"; do args+=(--header "$header"); done
  docker exec "$ID-console" wget -q -O - "${args[@]}" "http://127.0.0.1:8080$path"
}
expect() { # <description> <expected> <actual>
  if [ "$3" = "$2" ]; then ok "$1"; else fail "$1: expected '$2', got '$3'"; fi
}
start_console() {
  console "$1" -d >/dev/null
  for _ in $(seq 1 50); do
    [ "$(get /edge-health 2>/dev/null)" = ok ] && return 0
    sleep 0.2
  done
  docker logs "$ID-console" >&2 || true
  return 1
}

FORGED_XFF='X-Forwarded-For: 198.51.100.1, 192.0.2.1'

# --- railway-edge ---
start_console railway-edge || { fail "console did not start with railway-edge"; exit 1; }
expect "railway-edge renders both global entries" \
  "$(printf 'set_real_ip_from 0.0.0.0/0;\nset_real_ip_from ::/0;')" \
  "$(docker exec "$ID-console" grep -v '^#' /etc/nginx/trusted-proxies/realip.conf)"
if docker exec "$ID-console" nginx -t >/dev/null 2>&1; then
  ok "nginx -t accepts the railway-edge render"
else
  fail "nginx -t rejects the railway-edge render"
fi
expect "railway-edge: X-Real-IP is the resolved client" \
  "203.0.113.7" "$(get /edge-client-ip 'X-Real-IP: 203.0.113.7' "$FORGED_XFF")"
for path in /api/edge-trust-probe /ws/nodes/edge-trust-probe; do
  expect "railway-edge: Central gets only \$remote_addr on $path" \
    "xri=203.0.113.7 xff=203.0.113.7" \
    "$(get "$path" 'X-Real-IP: 203.0.113.7' "$FORGED_XFF")"
  expect "railway-edge: without X-Real-IP, Central gets the socket peer on $path" \
    "xri=127.0.0.1 xff=127.0.0.1" "$(get "$path" "$FORGED_XFF")"
done
docker rm -f "$ID-console" >/dev/null

# --- numeric list (the peer 127.0.0.1 is not in it) ---
start_console 192.0.2.10/32 || { fail "console did not start with a numeric list"; exit 1; }
expect "numeric list: X-Real-IP from an untrusted peer is ignored" \
  "127.0.0.1" "$(get /edge-client-ip 'X-Real-IP: 203.0.113.7')"
expect "numeric list: Central gets the socket peer" \
  "xri=127.0.0.1 xff=127.0.0.1" "$(get /api/edge-trust-probe 'X-Real-IP: 203.0.113.7' "$FORGED_XFF")"
docker rm -f "$ID-console" >/dev/null

# --- refusals ---
for trust in "" "0.0.0.0/0" "::/0" "railway-edge,10.0.0.1/32"; do
  if output="$(console "$trust" --rm 2>&1)"; then
    fail "console started with CLIORA_TRUSTED_PROXY_CIDRS='$trust'"
  elif printf '%s' "$output" | grep -q 'CLIORA_TRUSTED_PROXY_CIDRS'; then
    ok "console refuses to start with CLIORA_TRUSTED_PROXY_CIDRS='$trust'"
  else
    fail "console failed for another reason with '$trust': $output"
  fi
  docker rm -f "$ID-console" >/dev/null 2>&1 || true
done

printf '\n%s\n' "failures: $FAILURES"
[ "$FAILURES" -eq 0 ]
