# ADR 0010: P1 node status timing

Status: accepted (2026-07-24)

- **Authority**: node online/offline status is computed by Central, never taken from the daemon's self-report. The heartbeat is only a liveness + resource signal.
- **Clock**: the "time since last heartbeat" that drives status uses a **monotonic** clock captured when each heartbeat arrives, so wall-clock skew or NTP steps between the two hosts cannot flip a node's state. Boundaries (from FR-NODE-002): `≤30 s` Online, `31–90 s` Degraded, `>90 s` Offline. A daemon WS disconnect marks Offline immediately.
- **Disabled** is orthogonal to online/offline: an admin-disabled node (`is_enabled=false`) may still hold a live connection but is shown Disabled and refuses new operations.
- **Display vs decision**: `nodes.last_seen_at` is persisted as an aware wall-clock instant purely for display (transported RFC 3339 UTC, localized in the browser with a full-instant tooltip). It is **not** used for the status decision.
- **Reconnect backoff**: daemon reconnect keeps the P0 ladder `1/2/5/10/30 s`, capped at `60 s`, with ≤250 ms jitter, resetting on a successful authenticated connect.
- **Testing**: status transitions are driven by an injectable fake monotonic clock so the 30 s / 90 s boundaries and Central-restart re-registration are deterministic.
