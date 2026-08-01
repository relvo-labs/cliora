# Release note — port forwarding preview (Pinggy integration)

Two audiences, and the two things they need to know are different. Platform administrators
decide whether the organisation uses this at all; node owners keep a veto they can exercise
without asking anyone. Both halves are below; read the one that applies to you, and read the
other one before assuming what it says.

Reference: ADR 0022, PRD §8.10 (`FR-TUNNEL-001`–`004`), `SCOPE-013`.

---

## For platform administrators

Port forwarding lets a user expose one port of a web application running on a node, and open
it in a browser, for **previewing applications under development**. It is delivered as an
integration with a third-party tunnel service (Pinggy), not as a proxy inside Cliora.

**Nothing is enabled by this upgrade.** The capability arrives switched off, and turning it on
is a decision with consequences that are stated on the settings page rather than in a link.

### Before you enable it

1. **An encryption key must exist.** The provider credential is the one secret Cliora stores
   that it must be able to read back, so it is encrypted rather than hashed:

   ```bash
   openssl rand -base64 32   # set as CLIORA_SECRET_ENCRYPTION_KEY, then restart Central
   ```

   Without it, enabling the integration is refused (`SECRET_KEY_MISSING`) — deliberately, rather
   than storing the token in plain text "for now". Check with
   `curl -s <central>/readyz | jq .tunnel_integration`.

2. **Nodes need outbound TCP 443 to the provider**, and the pinned provider host key must be
   deployed with the daemon (`deploy/pinggy_known_hosts`). A node answers for itself with
   `agentd doctor`.

3. **The subscription is yours.** Cliora does not resell, hold an account, or call the
   provider's management or billing API. You obtain a token from the provider and paste it into
   **Integrations**; it is stored encrypted and never returned by any API — the page shows an
   8-character fingerprint so you can tell which token is installed.

4. **Decide who renews it.** A lapsed subscription does not look like an error: the provider
   answers an unusable credential by silently issuing an anonymous free tunnel. Cliora rejects
   that and reports `TUNNEL_PROVIDER_UNAUTHORIZED`, but somebody has to own the renewal. Write
   the name in `docs/release-checklist.md`.

### What enabling it means

Enabling requires a one-time acknowledgement of four facts, because each one is something people
assume is otherwise:

* Forwarded traffic passes through the provider's servers.
* The provider can see the unencrypted HTTP content, including `Cookie` and `Authorization`
  headers. **No control in Cliora changes this** — it is why the feature is for previews.
* The platform has no access log for these previews: the traffic never reaches Cliora, so
  "who opened this URL" is unanswerable.
* On the free tier, the URL contains the node's public IP address and changes every hour.

### Things worth knowing before somebody asks

| | |
|---|---|
| **Who can do what** | Admin and Developer hold `tunnel.view` and `tunnel.manage`; a Viewer holds neither, because seeing a URL is being able to reach the application behind it. Only Admin holds `integration.manage` — a Developer may open tunnels, not decide whose service and whose account. |
| **Concurrency** | The fleet-wide budget defaults to 8 and must match your plan. Exceeding a provider plan does not queue: it evicts somebody else's tunnel. The settings page shows the live count against the budget. |
| **Disabling** | Stops new tunnels; does **not** close the ones already running (some nodes may be offline, and an action that can partly fail must not look like a switch). The page then offers a separate "close all" that reports each tunnel individually. |
| **Per-node limits** | Which ports a machine may forward, and how many tunnels it may hold, live on that node's port-forwarding page — editable by any `tunnel.manage` holder, because it is day-to-day work. |
| **Audit** | `integration.enable`, `integration.disable`, `integration.credential_set`, `integration.node_settings_updated`, `tunnel.create`, `tunnel.close`, `tunnel.public_acknowledged`. The token never appears — only its fingerprint. Neither does a tunnel's URL: it is part of the access credential, and the audit trail is readable by every `audit.view` holder. |
| **If the key is lost** | The stored credential cannot be decrypted, and there is no recovery: paste the token again. See `docs/runbooks/tunnel-pinggy.md`. |

---

## For node owners

**Requires agentd 0.4.0 or newer.** An older daemon reports nothing about port forwarding, and
the console shows the node as unsupported with "upgrade this node's agentd" rather than as
failing — "we do not know" and "not ready" are deliberately different states.

**This upgrade does not expose anything.** No port on your machine becomes reachable by
installing or updating agentd, and the platform cannot open a tunnel until an administrator has
enabled the integration for the whole deployment.

Once it is enabled, **your node takes part by default**. That mirrors the shell runtime
(ADR 0021): a node that has been enrolled already grants the platform the ability to run
processes as the daemon's user, so a second per-machine opt-in would be form rather than
substance.

### Your veto

```yaml
# /etc/agentd/config.yaml
tunnel:
  enabled: false          # absolute. No platform setting overrides this.
```

Then `systemctl restart agentd`. The console will show your node as vetoed locally and say that
the platform cannot override it. You can also narrow instead of refusing:

```yaml
tunnel:
  allowed_ports: ["5173", "3000-3999"]   # may only be narrower than the platform's list
  max_tunnels: 1
```

Ports below 1024 are never forwarded, at any layer, by any configuration.

### What runs on your machine

One `ssh` child process per tunnel, started by agentd, connecting **outbound** to the provider.
There is no inbound listener and no port opened by the tunnel itself. `agentd doctor` tells you
whether the prerequisites are present; `ls /run/agentd/tunnels/` shows what is running.

### What is *not* on your machine

The provider credential is the platform's, delivered per tunnel and held only in memory and in
the `ssh` process's arguments — never written to disk, never logged, never in a pid file. Note
the flip side honestly: a process running as the **same user** on your machine can read that
process's arguments while a tunnel is open. The daemon not running as root is both the
protection and the limit of it.
