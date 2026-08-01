# ADR 0022 — Port forwarding through a third-party tunnel provider

- Status: accepted
- Date: 2026-08-01
- Supersedes: nothing. Extends the daemon's outbound-only connection model with a second,
  independent outbound path.
- Related: ADR 0008 (node credential), ADR 0016 (RBAC/audit), ADR 0020 (deployment topology),
  ADR 0021 (system terminal — same "the daemon's identity is the privilege ceiling" argument)
- Plan: `plan/11/`. **Rejected alternative:** `plan/10/` (self-hosted reverse proxy), retained
  in full as the design to return to if this decision is reversed.
- Requirements: `FR-TUNNEL-001` … `FR-TUNNEL-004`, `SCOPE-013`, `SEC-008`

## Context

A user developing a web application on a node has no way to see it. The CLI panel shows the
log, the read-only preview (`FR-FILE-002`) shows the source, and nothing shows the running
page. The workaround people reach for is to run ngrok (or an SSH reverse tunnel) on the node
themselves — a path the platform cannot see, cannot authorize, cannot audit, and whose
certificates a third party holds. That is the thing this platform exists to replace, so the
choice is not "tunnel or no tunnel"; it is "an unmanaged tunnel or a managed one".

Two designs were specified in full before choosing.

**Self-hosted (plan/10).** Central proxies the traffic itself. It needs a wildcard domain, a
DNS-01 wildcard certificate, an HTTP/WebSocket proxy with a stream manager and backpressure, a
second data-plane WebSocket per node, two new binary frame kinds, a host gate, a cookie
handshake, and a relaxed CSP — 15 tickets, and every request flows through our own
infrastructure.

**Third-party integration (plan/11, this ADR).** The daemon supervises an `ssh -R` child
process against a tunnel provider (Pinggy). No wildcard domain, no certificate, no proxy, no
second socket, no binary frames, no edge change — 14 tickets, of which none touches the edge.

## Decision

Deliver port forwarding by integrating a third-party provider. The platform manages the
lifecycle, authorization, limits, and audit; the provider carries the traffic.

### 1. What this costs, stated plainly

**The previewed application's unencrypted HTTP content passes through the provider's servers.**
Pinggy's `http` tunnel type processes the traffic (it offers header rewriting and live
debugging), and TLS terminates on their side. No control in this design changes that. The
consequence is a scope statement, not a caveat:

> **This feature is for previewing applications under development. It is not for any
> environment holding real data.**

That sentence belongs in the UI, the runbook, and the release note, because it is the only
honest summary of the trust boundary.

Two further consequences follow from the traffic not passing through Central:

- The platform **cannot** answer "who accessed this preview" — there is no access log to keep.
  This is a capability gap, not a privacy design.
- The platform **cannot** apply content policy, body limits, or header policy to the traffic.

### 2. The credential is held by the platform

The integration is enabled by an Admin in the platform's integration settings, and enabling it
means supplying a provider token. Keeping the token on each node instead would make the
platform's "enabled" switch a promise it cannot keep — Central would have no idea which nodes
had a token, or which token.

So Central stores it, and pays for that:

| Control | Detail |
|---|---|
| Encryption at rest | AES-GCM, key from `CLIORA_SECRET_ENCRYPTION_KEY` (32 bytes, base64), fresh nonce per write. Uses the existing `cryptography` dependency. |
| No key, no feature | With the key unset, enabling the integration is refused (`SECRET_KEY_MISSING`). Storing plaintext "for now" is not an option: there is no way back from plaintext already on disk. |
| Write-only | No API returns the token or any part of it. The UI shows `configured` plus an 8-hex fingerprint of the plaintext, which answers "is this the key I rotated last week" without disclosing a character. |
| Character set | `^[A-Za-z0-9]{8,128}$`, enforced in the API, the wire schema, and the daemon. **This is a security control, not tidiness**: the token is concatenated into `ssh`'s `<token>@<host>` field, and Pinggy separates modifiers with `+` and the host with `@`. A token containing `+tcp` changes the tunnel type; one containing `@evil.host` changes where the node connects. |
| Delivery | In each `tunnel.open`. The node keeps it in memory and in the child's argv, and **never writes it to disk**. Rotating the token therefore affects only tunnels opened afterwards. |
| Loss of the key | Stored credentials become undecryptable. The remedy is to enter the token again, not to recover it. The runbook says so in its first paragraph. |

**Accepted residual risk:** the token appears in the `ssh` process's argv, so another process
running as the same user on that node can read it. The daemon runs non-root, which bounds this
to that user; it is listed in the security review rather than papered over.

### 3. Three layers of settings, and they only narrow

| Layer | Owner | Contents |
|---|---|---|
| Integration settings | Admin (`integration.manage`) | on/off, credential, plan tier, concurrent budget, default protection and TTL, global port ceiling |
| Per-node settings | `tunnel.manage` | whether this node participates, its port range, its tunnel cap |
| Node-local veto | node owner (`/etc/agentd/config.yaml`) | `tunnel.enabled: false` is absolute; `allowed_ports` may only narrow |

Effective policy is the intersection. **"The platform may override the node" was considered and
rejected** — it would turn the node owner's veto into a suggestion.

The node-local default is *not* to veto. The argument: this machine already grants the platform
a `shell` runtime (ADR 0021, enabled by default), so a platform that can already run `bash`
there does not become meaningfully more dangerous by forwarding a port, and requiring a second
per-machine file edit would be form rather than substance. The veto exists for machines whose
owners need it.

The concurrent budget is **fleet-wide** and is checked as a global count, not folded into the
per-node minimum. Conflating them would mean a budget of 8 with a per-node cap of 3 silently
allows 3 × N tunnels — more than the paid plan permits, which the provider answers by
displacing someone else's tunnel.

### 4. A tunnel URL is public; protection is a provider option

The provider's URL is reachable by anyone who has it. `plan/10` could promise "the URL is not a
credential"; this design cannot, so protection is selected per tunnel:

- **`basic`** (default) — provider-enforced HTTP basic auth (`b:user:pass`). The password is
  generated by Central, shown once, and stored as an Argon2 hash.
- **`ipallow`** — provider-enforced source IP allowlist (`w:`).
- **`public`** — no protection. Requires an explicit acknowledgement, which is audited.

`x:https` is always passed, so plaintext requests are redirected to HTTPS.

### 5. Host key pinning is the one transport control we own

Everything else about the transport is Pinggy's. The connection itself is ours to verify, so it
is pinned: `-o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/agentd/pinggy_known_hosts
-o GlobalKnownHostsFile=/dev/null`. Without pinning, anything on the node's egress path could
read every byte of every preview, and the symptom would be "it works".

`StrictHostKeyChecking=no` and `UserKnownHostsFile=/dev/null` are forbidden, with a CI grep gate
behind the rule. A missing or empty pinned file refuses to start the tunnel; it never degrades
to trust-on-first-use.

## What was measured, and what it changed

`PG-01` ran twelve checks against the live service on 2026-08-01
(`scripts/tunnel/verify-provider.sh`, evidence in `artifacts/pg/local/provider-verify.json`).
Three of them contradicted the vendor documentation and changed the design:

| Measurement | Consequence |
|---|---|
| **A PTY must not be requested.** With `-t` the service renders a full-screen ANSI TUI (19 KB of escape sequences in 15 s) and the URL is unparseable. Without a PTY, stdout is four clean lines. | The daemon never allocates a PTY, and does not use `creack/pty` here. Test-gated. |
| **An invalid credential is not rejected.** The service silently downgrades to an anonymous free tunnel and still returns a URL. | Authorization failure cannot be detected from an exit code. The daemon detects "credential supplied *and* stdout says `You are not authenticated.`", reports `TUNNEL_PROVIDER_UNAUTHORIZED`, **and tears the tunnel down** — a Pro user must not silently receive a 60-minute anonymous tunnel. |
| **The app receives the tunnel domain as `Host`.** Dev servers with host allowlists (Vite, Next) refuse such requests. | An opt-in Host rewrite (`u:Host:localhost:<port>`) is offered, default off. This is one header, chosen by the user so their own dev server will answer; it is not content rewriting. |

Two further measured facts that the documentation does not mention:

- **The free-tier hostname embeds the node's public IP** (`<slug>-114-32-49-189.…`). The UI must
  disclose this before a free-tier tunnel is created.
- **`Cookie` and `Authorization` reach the app unchanged.** An application behind the tunnel can
  therefore keep its own session — something `plan/10` explicitly could not offer.

Host keys: RSA 4096 only (`SHA256:nFd5rfJMGuZXvfeRzJ/BtT3TfksAxTWMajcrHRcI7AM`), the same key on
`free`, `pro`, and `a.pinggy.io`; the service offers no ed25519 or ecdsa key to pin.

Still unverified, and therefore staging-gated: the free tier's behaviour at the 60-minute mark,
the Pro persistent-subdomain hostname, and a paid plan's real concurrency limit.

## Compensating controls, and what each does not cover

| Control | Stops | Does not stop |
|---|---|---|
| Integration disabled by default; Admin must enable and acknowledge | the platform gaining outbound forwarding without anyone deciding | any `tunnel.manage` holder creating tunnels once enabled |
| Node-local veto, not overridable | the platform deciding for a machine with compliance constraints | machines that have not vetoed (the default) |
| Credential encrypted, write-only, fingerprint-only display | the credential leaking through the API, a DB dump, audit, or logs | the platform itself being compromised (remedy: revoke at Pinggy) |
| Credential character set restricted | injecting `+tcp` or `@host` to change tunnel type or destination | — |
| Provider host chosen by the daemon, never by Central | the protocol gaining "tell a node to connect anywhere" | — |
| `port ≥ 1024` and per-node allowlist (four layers: API, DB CHECK, wire schema, daemon) | forwarding system services or databases | whatever the app itself exposes |
| Protection mode, `basic` by default | someone who merely found the URL | Pinggy, which sits behind TLS termination |
| Host key pinning | a MITM on the node's egress path | Pinggy's own servers |
| TTL, explicit close, orphan reaping | forgotten long-lived exposure; `ssh` surviving a daemon restart | — |
| Two acknowledgements (Admin at enable, creator at first use per node) | "nobody told me the traffic leaves" | — |
| Daemon runs non-root | privilege escalation | **the ceiling is the daemon's own identity** — if that ever becomes root, the risk class of this feature changes |

## Rejected alternatives

- **Self-hosted reverse proxy (`plan/10`).** Correct design, disproportionate cost (§Context).
  Reopen if the third-party trust boundary becomes unacceptable, or if access logging and
  content policy become requirements. `plan/10` is kept as the ready specification.
- **Running ngrok/cloudflared on the node with the platform only storing the URL.** The
  credentials and traffic sit with a third party *and* the lifecycle is invisible to RBAC and
  audit. This is the status quo the decision replaces.
- **Central dialling into the node.** Violates the outbound-only model (tech §3.2) and does not
  work behind NAT.
- **A Go SSH client (`golang.org/x/crypto/ssh`) instead of the `ssh` binary.** Full control of
  authentication and host keys, at the price of a new cryptographic dependency for one
  integration. `PG-01` #1 showed `BatchMode=yes` works with auth method `none`, so the binary is
  sufficient — the daemon already supervises `tmux` and `systemctl` the same way. Reopen if the
  non-interactive path becomes unreliable.
- **Per-node credentials.** One platform credential (D18). If a plan's concurrency turns out to
  be lower than the configured budget, the answer is to lower the budget, not to introduce
  multi-credential management.
- **Calling Pinggy's management or billing API.** Would require holding a
  higher-privilege credential and tracking their API, to save an Admin one form field.
  Subscriptions stay with the user (`SCOPE-013`).
- **A "test connection" endpoint.** It would have to open a real tunnel and close it, creating an
  exposure nobody asked for, and would fail for exactly the same reasons a real creation does.
  The first real creation is the test.
- **iframe embedding by default.** Chrome does not show basic-auth prompts inside a cross-origin
  iframe, so embedding is only compatible with the weaker protection modes, and it would put the
  provider's domain into our CSP. Left as an optional ticket (`PG-12`), default not done.

## Consequences

- New requirements `FR-TUNNEL-001` … `FR-TUNNEL-004`, new non-goal `SCOPE-013`, new security
  requirement `SEC-008`.
- Contract v1.6.0 adds five control message types and six error codes. **No binary frame kind and
  no new WebSocket endpoint** — the data path does not exist inside the platform.
- `tunnel.open` is the first protocol message that carries a secret. It must never be logged, and
  golden fixtures use obviously fake credential values.
- Three new tables, three new actions (`tunnel.view`, `tunnel.manage`, `integration.manage` — the
  last Admin-only), seven new audit actions.
- A new deployment prerequisite: `CLIORA_SECRET_ENCRYPTION_KEY`, plus outbound TCP 443 from each
  participating node to the provider, plus `openssh-client` on those nodes.
- Nodes gain nothing on upgrade: the integration is off until an Admin enables it.
