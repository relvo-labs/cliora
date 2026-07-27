# ADR 0003: P0 limits

Status: accepted for measurement (2026-07-22)

Control and binary payloads are capped at 64 KiB. Browser queues allow 2 MiB/256 terminal frames; daemon queues allow 4 MiB/512 frames; control queues allow 64 frames. Snapshots retain at most the newest 2 MiB. Queue accounting reserves before enqueue and releases on dequeue or close. Overflow isolates the consumer, emits gap when possible, and preserves tmux.
