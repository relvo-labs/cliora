---
name: go-daemon-development
description: >-
  Build and review Cliora's Go VM daemon, including outbound WebSockets, runtime launching, PTY and tmux lifecycle, workspace access, installation, updates, and recovery. Use when modifying daemon code, runtime adapters, session processes, filesystem relays, systemd packaging, or Go tests.
---

# Go Daemon Development

1. Use `cliora-project-context`; inspect `go.mod`, layout, tests, and release config.
2. Read relevant `research/tech.md` sections 8-12, 15, and 18-20.
3. Define ownership for every connection, goroutine, process, PTY, tmux session, queue, and cancellation path.
4. Use typed runtime operations and allowlisted arguments; never accept arbitrary command strings. Launch flags belong only in the daemon's compile-time table (`internal/runtime/launch.go`); config and wire may gate them with a boolean, never name them (ADR 0023).
5. Bound buffers, apply timeout/backoff with jitter, and cancel without leaks.
6. Test normal operation, reconnect, timeout, process failure, invalid paths, shutdown, and races. For write paths also test escape attempts, a hijacked target directory (a symlink or a non-directory), quota exhaustion, and that a refusal leaves no partial file.
7. Classify text over the whole read buffer, on rune boundaries; a fixed prefix window misjudges valid UTF-8 and misses what follows it (ADR 0015 amendment 2026-08-01).

Run non-root — on a privileged node `NoNewPrivileges` is dropped and the service user holds passwordless sudo, so the identity stays non-root while its ceiling is root (ADR 0023); own the tmux socket and its generated config rather than the node owner's default server; initiate authenticated WSS to Central; protect credentials; keep browser and CLI lifetimes separate; derive tmux names from internal IDs; enforce canonical allowed-root paths after symlink resolution; route every workspace write through `workspace.Root` (never a bare `os.WriteFile`/`os.Create`/`os.MkdirAll` on a workspace path), generate stored filenames in the daemon rather than accepting one, write via a temp file plus rename so a failure leaves nothing, and ship a new write path together with its quota and its expiry — retrofitting either means changing the data model (ADR 0024); deny sensitive, oversized, and binary previews; assign a single terminal writer; and redact secrets and terminal content from logs.

Run existing checks, including `go test ./...` and `go test -race ./...` for concurrency when available.
