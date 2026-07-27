---
name: terminal-websocket-protocol
description: >-
  Design Cliora's versioned WebSocket contract across Vue, FastAPI, and Go. Use when changing message envelopes, correlation, binary terminal frames, heartbeat, resize, scrollback, timeout, reconnect, resume, backpressure, error codes, or compatibility tests.
---

# Terminal WebSocket Protocol

Treat this as a low-freedom cross-runtime contract.

1. Use `cliora-project-context`; inspect every browser, Central, and daemon producer and consumer.
2. Read `research/tech.md` sections 7.2-7.4 and 9-12 plus matching PRD requirements.
3. Specify direction, version, envelope, encoding, ordering, correlation, timeout, retry, idempotency, and errors before coding.
4. Use text frames for control and binary frames for terminal bytes.
5. Model reconnect with bounded retry, resume semantics, and duplicate/gap handling.
6. Update all implementations and contract tests atomically or define a compatibility window.

Require stable types, typed payloads, bounded frames/queues/scrollback, explicit backpressure, safe error codes, and idempotent retries. Test malformed and unknown frames, delay, disconnect, duplicates, bursts, resume gaps, and unauthorized access with cross-language fixtures.
