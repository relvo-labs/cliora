---
name: go-daemon-development
description: >-
  Build and review Cliora's Go VM daemon, including outbound WebSockets, runtime launching, PTY and tmux lifecycle, workspace access, installation, updates, and recovery. Use when modifying daemon code, runtime adapters, session processes, filesystem relays, systemd packaging, or Go tests.
---

# Go Daemon Development

1. Use `cliora-project-context`; inspect `go.mod`, layout, tests, and release config.
2. Read relevant `research/tech.md` sections 8-12, 15, and 18-20.
3. Define ownership for every connection, goroutine, process, PTY, tmux session, queue, and cancellation path.
4. Use typed runtime operations and allowlisted arguments; never accept arbitrary command strings.
5. Bound buffers, apply timeout/backoff with jitter, and cancel without leaks.
6. Test normal operation, reconnect, timeout, process failure, invalid paths, shutdown, and races.

Run non-root; initiate authenticated WSS to Central; protect credentials; keep browser and CLI lifetimes separate; derive tmux names from internal IDs; enforce canonical allowed-root paths after symlink resolution; deny sensitive, oversized, and binary previews; assign a single terminal writer; and redact secrets and terminal content from logs.

Run existing checks, including `go test ./...` and `go test -race ./...` for concurrency when available.
