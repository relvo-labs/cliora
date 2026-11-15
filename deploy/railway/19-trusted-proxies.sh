#!/bin/sh
# Run before envsubst. Railway requires an explicit trust choice; Compose explicitly permits
# direct clients. See docs/deployment-railway.md#trusted-client-ip-railway-edge-contract-184.
set -efu
# The only spelling that means "trust X-Real-IP from any socket peer". It names the
# platform contract (Railway's HTTP edge overwrites X-Real-IP on every request) rather than
# a network, so a hand-typed 0.0.0.0/0 or ::/0 stays an error below.
RAILWAY_EDGE=railway-edge
mode=${1:-}
case "$mode" in
  '')
    if [ -z "$(printf '%s' "${CLIORA_TRUSTED_PROXY_CIDRS:-}" | tr -d '[:space:],')" ]; then
      echo "CLIORA_TRUSTED_PROXY_CIDRS is required: set $RAILWAY_EDGE (Railway edge contract) or numeric proxy CIDRs; see docs/deployment-railway.md#trust-upgrade-runbook-59" >&2
      exit 1
    fi ;;
  --allow-direct) ;; # Only the Compose image's entrypoint supplies this literal argument.
  *) echo 'invalid trusted-proxy renderer argument' >&2; exit 1 ;;
esac
out=${CLIORA_TRUSTED_PROXY_DIR:-/etc/nginx/trusted-proxies}
mkdir -p "$out"
tmp=$(mktemp "$out/.realip.XXXXXX")
trap 'rm -f "$tmp"' EXIT HUP INT TERM
# Word splitting below is safe: `set -f` disables globbing.
entries=$(printf '%s' "${CLIORA_TRUSTED_PROXY_CIDRS:-}" | tr ',' ' ')
only_keyword=0 # becomes 1 only when the keyword is the first and the sole entry
for cidr in $entries; do
  if [ "$only_keyword" = 0 ] && [ "$cidr" = "$RAILWAY_EDGE" ]; then only_keyword=1; else only_keyword=2; fi
done
if [ "$only_keyword" = 1 ]; then
  if [ "$mode" = --allow-direct ]; then
    echo "invalid CLIORA_TRUSTED_PROXY_CIDRS: $RAILWAY_EDGE is the Railway platform contract and has no meaning in Compose" >&2
    exit 1
  fi
  # Railway's HTTP edge replaces X-Real-IP on every request; the socket peer is not a stable
  # or published range. Trust rests on: no TCP proxy on this service and nothing else in the
  # environment that can reach it (scripts/railway/check-trust-topology.sh).
  {
    echo "# $RAILWAY_EDGE (#184): X-Real-IP from Railway's HTTP edge, any socket peer"
    echo 'set_real_ip_from 0.0.0.0/0;'
    echo 'set_real_ip_from ::/0;'
  } > "$tmp"
else
  # Numeric addresses/CIDRs only: never let an env value inject nginx directives.
  # nginx validates address syntax and prefix lengths when it loads the include.
  for cidr in $entries; do
    case "$cidr" in
      "$RAILWAY_EDGE") echo "invalid CLIORA_TRUSTED_PROXY_CIDRS: $RAILWAY_EDGE must be the only entry" >&2; exit 1 ;;
      *[!0-9a-fA-F:./]*|*/0*) echo "invalid CLIORA_TRUSTED_PROXY_CIDRS (numeric non-global ranges, or exactly $RAILWAY_EDGE, required)" >&2; exit 1 ;;
    esac
    printf 'set_real_ip_from %s;\n' "$cidr" >> "$tmp"
  done
fi
mv "$tmp" "$out/realip.conf"
