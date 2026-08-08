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
6. Test normal operation, reconnect, timeout, process failure, invalid paths, shutdown, and races. For write paths also test escape attempts, a hijacked target directory (a symlink or a non-directory), quota exhaustion, the mode the file lands with, and that a refusal leaves the existing bytes and mtime untouched — asserting the error code alone would not catch a refusal that arrives after the damage.
7. Classify text over the whole read buffer, on rune boundaries; a fixed prefix window misjudges valid UTF-8 and misses what follows it (ADR 0015 amendment 2026-08-01).

Run non-root — on a privileged node `NoNewPrivileges` is dropped and the service user holds passwordless sudo, so the identity stays non-root while its ceiling is root (ADR 0023); own the tmux socket and its generated config rather than the node owner's default server; initiate authenticated WSS to Central; protect credentials; keep browser and CLI lifetimes separate; derive tmux names from internal IDs; enforce canonical allowed-root paths after symlink resolution; route every workspace write through `workspace.Root` (never a bare `os.WriteFile`/`os.Create`/`os.MkdirAll` on a workspace path); on the image path generate the stored filename in the daemon and publish via a temp file plus rename, but on a path that accepts a client-supplied name create the **final** name with `O_EXCL` instead — `renameat` replaces its destination and `os.Root` exposes no `RENAME_NOREPLACE`, so temp-plus-rename would silently clobber a file that appeared after the check (ADR 0026); fix the mode through the file's own descriptor (`f.Chmod`, not `Root.Chmod` — the path form races on a symlink swap, and `fchmod` also escapes the umask); ship a new write path together with its quota, and with either an expiry or a guarantee that every byte lands somewhere the user chose and can see — retrofitting any of them means changing the data model (ADR 0024, ADR 0026); deny sensitive, oversized, and binary previews; assign a single terminal writer; and redact secrets and terminal content from logs.

Run existing checks, including `go test ./...` and `go test -race ./...` for concurrency when available.
