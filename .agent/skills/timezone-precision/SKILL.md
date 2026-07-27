---
name: timezone-precision
description: >-
  Enforce explicit timezone and timestamp semantics across Cliora Python, PostgreSQL, Vue, protocols, heartbeats, sessions, tokens, and audit records. Use whenever code or schemas create, compare, serialize, persist, expire, or display dates and times.
---

# Timezone Precision

Use `cliora-project-context`. Create aware timestamps only; persist instants with timezone-aware PostgreSQL types; transport RFC 3339 UTC; reject missing or ambiguous offsets. Compare instants in UTC and localize only for display. Use monotonic time for durations such as heartbeat timeout and retry. Apply this to node last-seen, session lifecycle, token expiry, audit, and reconnect metadata. Test Asia/Taipei, non-whole-hour offsets, DST, round trips, clock skew, and expiry equality. State how legacy naive values are interpreted before migration.
