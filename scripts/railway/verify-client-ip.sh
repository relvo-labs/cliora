#!/usr/bin/env bash
# Check nginx identity, then correlate HTTP/WS client scope using operator-only Central logs.
set -euo pipefail
base=${1:?usage: verify-client-ip.sh BASE EXPECTED_IP}
expected=${2:?expected public source IP required (obtain independently)}
out=${3:?usage: verify-client-ip.sh BASE EXPECTED_IP OUT}
mkdir -p "$out"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
curl_args=(-fsS --max-time 20)
if [ "${CLIORA_VERIFY_INSECURE:-0}" = 1 ]; then curl_args+=(-k); fi
for forged in '' '203.0.113.59' '198.51.100.59'; do
  actual=$(curl "${curl_args[@]}" "$base/edge-client-ip" \
    -H "X-Forwarded-For: $forged, 192.0.2.59" -H "X-Real-IP: $forged")
  [ "$actual" = "$expected" ] || {
    echo "FAIL: resolved client '$actual', expected '$expected'" >&2; exit 1;
  }
done
echo 'ok: nginx resolved client IP survives forged headers (3 requests); Central not yet verified'
uv run --project "$root/backend" python "$root/scripts/railway/central_client_probe.py" \
  send "$base" "$expected" "$out/central-client-receipt.json"
if [ -z "${CLIORA_VERIFY_CENTRAL_LOG:-}" ]; then
  echo 'PENDING: set CLIORA_VERIFY_CENTRAL_LOG to operator-collected Central logs, or use central_client_probe.py verify RECEIPT LOG' >&2
  exit 3
fi
# A live operator log collector may need a few seconds to flush the correlated lines.
for attempt in $(seq 1 10); do
  if uv run --project "$root/backend" python "$root/scripts/railway/central_client_probe.py" \
    verify "$out/central-client-receipt.json" "$CLIORA_VERIFY_CENTRAL_LOG"; then
    exit 0
  fi
  [ "$attempt" = 10 ] || sleep 1
done
exit 1
