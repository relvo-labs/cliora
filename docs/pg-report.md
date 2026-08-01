# plan/11 report — port forwarding as a third-party integration

Delivered 2026-08-01. Decision record: ADR 0022. Requirements: `FR-TUNNEL-001`–`004`,
`SCOPE-013`. Security review: `docs/security-review-p11.md`. Ticket status and handoff:
`plan/11/07-implementation-status.md`.

---

## 1. What was delivered

A user with `tunnel.manage` can expose one port of an application running on a node and open it
in a browser, for **previewing applications under development**. The traffic path is
node → provider → viewer; it does not pass through Cliora.

| Layer | What landed |
|---|---|
| Contract | v1.6.0: five control messages (`tunnel.open/opened/close/closed/status`) plus a `node-tunnel-report` object on registration. **No binary frame, no second socket, no new WebSocket endpoint.** Six wire error codes; 11 golden fixtures, 5 of them negative |
| Daemon | A supervised `ssh -R` child per tunnel: pinned host key, no PTY, URL parsed from stdout, reconnect with backoff and a cap, TTL enforcement, pid files and orphan reaping. The node's own config holds an absolute veto and a port allowlist that can only narrow |
| Central | `tunnel_integration` (one row, encrypted credential), `node_tunnel_settings` (per node), `node_tunnels`. A tunnel service that composes the three configuration layers, enforces three independent limits, and keeps the platform's copy of the URL true as the provider reassigns it. Nine REST routes across two routers |
| Console | An integration settings page (Admin) and a per-node port-forwarding page (Admin/Developer) that names *which* layer refused, shows the provider's URL with its age, and shows the one-time password exactly once |
| Verification | 23 traceability criteria, all `verifiable`; a repository-wide host-key gate; a scope guard against a reverse proxy growing back; a credential-leak scanner; an evidence pack |

## 2. What the real provider actually does (PG-01)

Twelve checks against the live service on 2026-08-01, script `scripts/tunnel/verify-provider.sh`,
output `artifacts/pg/local/provider-verify.json`. **Three assumptions were wrong**, and each one
changed the implementation rather than a comment:

| Assumption | Measured | What changed |
|---|---|---|
| A PTY might be needed to read the URL | With `-t` the output is a 19 KB full-screen ANSI TUI and unparseable; without it, four clean lines | No PTY, ever — asserted by a test |
| An invalid credential is refused | The service **silently downgrades to an anonymous free tunnel** and returns a URL | Both the daemon and Central detect it and tear the tunnel down as `TUNNEL_PROVIDER_UNAUTHORIZED` |
| The app receives loopback as `Host` | It receives the **tunnel domain**, which dev servers with host allowlists refuse | An opt-in Host rewrite, off by default |

Two things the documentation did not mention: free-tier hostnames **embed the node's public IP**,
and `Cookie`/`Authorization` pass through unchanged (which the withdrawn self-hosted design could
not have done). Both are disclosed in the UI and the release note.

Also confirmed: basic auth works on the free tier (so protection needs no plan branch), two
tunnels can coexist under one identity, `x:https` answers plain HTTP with a 301 rather than a
refusal, and host key verification produces a reliably distinguishable failure.

## 3. Capability gaps

Not defects. Each is a consequence of the decision in ADR 0022, and each is stated in the UI or
the release note rather than only here.

1. **No access log for a preview.** The traffic never reaches the platform, so "who opened this
   URL" is unanswerable. `SEC-006` says so.
2. **No content policy.** The platform cannot inspect or restrict what the forwarded application
   serves, and the provider can read the unencrypted HTTP either way.
3. **URLs change.** Free tier: a new URL on every reconnect, and the tunnel ends at 60 minutes.
   Any link pasted into a ticket has an hour at most.
4. **The free-tier hostname discloses the node's public IP.**
5. **iframe embedding and password protection are mutually exclusive** (Chrome shows no auth
   dialog in a cross-origin frame), which is one of the reasons `PG-12` was not done.
6. **Provider down means feature down.** No fallback — a fallback is the reverse proxy
   `SCOPE-013` forbids.
7. **A process with the same uid on the node can read the credential** from the `ssh` process's
   arguments while a tunnel is open. The daemon not running as root is the boundary.
8. **Failure classification matches the provider's stderr strings.** If they reword their
   messages, distinguishable failures — the host-key one included — degrade to "unavailable".

## 4. Open items and who owns them

| # | Item | Owner | Note |
|---|---|---|---|
| 1 | Three Pro-tier provider facts unverified (60-minute behaviour observed to completion, persistent-subdomain hostname, a paid plan's real concurrency limit) | central | Needs a paid token. Release-triggered behind `GATE-TUNNEL-PROVIDER`; `concurrent_budget` defaults to 8 with a UI note to match the plan |
| 2 | The browser leg of the stand-in-provider stack has never run on an unprivileged host | frontend | Playwright's system libraries need root. The suite exists (`frontend/tests/e2e/tunnel.spec.ts`) and CI runs it on three engines through `p2.yml`; locally the same path is verified without a browser by `scripts/pg/tunnel-stack-check.sh` (14 assertions, green). What is unverified here is rendering, and the evidence pack says so rather than counting it |
| 3 | A whole-filesystem sweep for the credential on a live node | daemon | Finding F-2 is closed at the level a test can assert honestly (`TestTheCredentialIsNeverWrittenToDiskOrLogged`: the run directory and the log, verified against a deliberate leak). Sweeping an entire filesystem would need a disposable machine, which is a release-environment job |
| 4 | `PG-12` (iframe embedding) | product | **Not done, by decision.** It is the only work here that would relax CSP, and it buys one fewer click. Recorded in `plan/11/07-implementation-status.md` D-5 |
| 5 | Provider subscription renewal | operations | Must be a named person before enabling: a lapsed subscription surfaces as `TUNNEL_PROVIDER_UNAUTHORIZED`, not as an expiry notice. `docs/release-checklist.md` §4.6 |

## 5. Evidence

`scripts/pg/evidence.sh [output-dir]` runs every gate and records each exit status. The
2026-08-01 local run: **18 gates executed, 18 passed**, two honest skips (the browser leg, which
needs root-installed libraries, and the real provider, which needs an account). See
`artifacts/pg/local/summary.md`.

The stack leg is worth naming separately, because it is the one that proves the parts fit
together:

```bash
# Central + a real daemon + a stand-in provider + the app being forwarded, then 14 assertions
# from "the routes are 404 while disabled" to "no provider process survived the close":
CLIORA_DATABASE_URL=postgresql+asyncpg://…/cliora_e2e \
  scripts/e2e/run-stack.sh scripts/pg/tunnel-stack-check.sh
```

The three gates specific to this phase, runnable on their own:

```bash
# Host key verification is never disabled, anywhere in the tree:
uv run --project backend pytest \
  backend/tests/test_security.py::test_no_source_disables_provider_host_key_verification -q
# Central has not grown a reverse proxy:
uv run --project backend pytest \
  backend/tests/test_scope_guards.py::test_scope_013_central_does_not_proxy_to_a_node_http_service -q
# Nothing writes the credential where it could be read back:
scripts/pg/check-no-token-leak.sh
```

## 6. One thing worth carrying forward

The withdrawn design (plan/10) was not wrong; it was disproportionate. Its weight sat in five
places — a wildcard domain, DNS-01 wildcard certificates, a Central-side proxy and stream
manager, a second data-plane socket, and a relaxed CSP — and this phase replaced all five with
"the daemon supervises one `ssh` child process".

What it cost instead is the thing to remember: **the platform became the custodian of somebody
else's credential**, and that is the one secret here that has to be readable rather than hashed.
Every control in the security review's rows 3, 3b, 3c, 3d and 3e exists because of that single
trade, and none of them can undo it.
