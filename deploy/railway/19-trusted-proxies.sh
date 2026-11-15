#!/bin/sh
# Run before envsubst. Empty means trust no platform peer until verified after deploy.
set -efu
out=${CLIORA_TRUSTED_PROXY_DIR:-/etc/nginx/trusted-proxies}
mkdir -p "$out"
tmp=$(mktemp "$out/.realip.XXXXXX")
trap 'rm -f "$tmp"' EXIT HUP INT TERM
# Numeric addresses/CIDRs only: never let an env value inject nginx directives.
# nginx validates address syntax and prefix lengths when it loads the include.
for cidr in $(printf '%s' "${CLIORA_TRUSTED_PROXY_CIDRS:-}" | tr ',' ' '); do
  case "$cidr" in
    *[!0-9a-fA-F:./]*|*/0*) echo 'invalid CLIORA_TRUSTED_PROXY_CIDRS (numeric non-global ranges required)' >&2; exit 1 ;;
  esac
  printf 'set_real_ip_from %s;\n' "$cidr" >> "$tmp"
done
mv "$tmp" "$out/realip.conf"
