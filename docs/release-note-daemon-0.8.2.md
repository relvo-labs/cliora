# Daemon 0.8.2 — Go 1.26.11 security rebuild (#162)

0.8.2 changes no daemon behaviour. It rebuilds agentd with **Go 1.26.11** instead of
1.26.5, picking up the Go standard-library security releases published between
2026-05 and 2026-11 (23 advisories against 1.26.5). The ones on agentd's own call paths:

- `crypto/tls` — unbounded post-handshake messages (GO-2026-6090) and malformed ECH
  outer extensions (GO-2026-6607), on the WSS connection to Central and on update
  downloads.
- `crypto/x509` — distrust of the emSign intermediate CAs whose keys were compromised
  (GO-2026-6809, 2026-10-21).
- `encoding/asn1` recursion depth (GO-2026-5972), `net/url` quadratic `resolvePath`
  (GO-2026-6218), `net/textproto` MIME header limits (GO-2026-6608) and several
  `net/http` client/HTTP/2 transport fixes (GO-2026-6605, GO-2026-6610).

`golang.org/x/sys` moves from v0.34.0 to v0.44.0 (GO-2026-5024 is Windows-only and was
never reachable from the Linux builds).

`daemon/go.mod` now requires `go 1.26.11`, so CI jobs that select Go from `go.mod`
build with the same patched toolchain as `.go-version`, and an older toolchain run with
`GOTOOLCHAIN=local` (as the official Go images do) fails instead of silently producing
an unpatched binary. Central's image builds agentd on `golang:1.26.11-bookworm` for
the same reason.

## Upgrading

Nothing to change on the node. `sudo agentd update --version 0.8.2` (or the normal
update path once Central serves 0.8.2). Everything in
[the 0.8.1 release note](release-note-daemon-0.8.1.md) still applies.
