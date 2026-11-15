#!/usr/bin/env bash
# Public echo of the resolved address; source CIDRs must ALSO be checked in console logs.
set -euo pipefail
base=${1:?usage: verify-client-ip.sh BASE EXPECTED_IP}
expected=${2:?expected public source IP required (obtain independently)}
curl_args=(-fsS --max-time 20)
if [ "${CLIORA_VERIFY_INSECURE:-0}" = 1 ]; then curl_args+=(-k); fi
for forged in '' '203.0.113.59' '198.51.100.59'; do
  actual=$(curl "${curl_args[@]}" "$base/edge-client-ip" \
    -H "X-Forwarded-For: $forged, 192.0.2.59" -H "X-Real-IP: $forged")
  [ "$actual" = "$expected" ] || {
    echo "FAIL: resolved client '$actual', expected '$expected'" >&2; exit 1;
  }
done
echo 'ok: resolved client IP survives forged X-Forwarded-For and X-Real-IP (3 requests)'
