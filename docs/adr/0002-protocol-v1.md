# ADR 0002: Protocol v1

Status: accepted (2026-07-22)

Control traffic is UTF-8 JSON text with integer version 1, typed payloads, ULID correlation, canonical UUIDs, and UTC `Z` timestamps. Terminal traffic is binary. The daemon link prepends version, kind, and 16 UUID bytes; the browser link is URL-bound and contains opaque terminal bytes only.

Ordering is guaranteed only on one session and transport. P0 has no replay sequence. Reattach uses bounded tmux snapshot followed by live output and explicitly reports a gap at the boundary. Malformed, unknown, and oversized input fails with stable codes and safe WebSocket closes.
