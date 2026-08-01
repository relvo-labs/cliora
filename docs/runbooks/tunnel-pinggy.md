# Runbook — port forwarding (Pinggy integration)

**Read this first: if the encryption key is lost, the stored provider credential cannot be
recovered.** It is encrypted with `CLIORA_SECRET_ENCRYPTION_KEY` and there is no path back to
plaintext. The remedy is for an administrator to paste the token again — not to restore data.
Everything else in this runbook is ordinary diagnosis; that one sentence is the only
irreversible thing here.

Scope: the third-party port-forwarding integration (ADR 0022, plan/11). Traffic on this path
never reaches Central — a tunnel is an `ssh -R` child process on the node — so nothing here is
diagnosed from Central's logs alone.

---

## 1. "I cannot create a tunnel" — five distinguishable causes

The API answers each of these differently on purpose. Read the error code first; it names the
layer, and the layers have different owners.

### 1.1 `TUNNEL_INTEGRATION_DISABLED` (404) — the integration is off

The platform switch lives in the database (`tunnel_integration.enabled`), not in the
environment, so it changes the moment an administrator flips it in **Integrations**.

```bash
# From the console: /settings/integrations. From psql:
psql "$CLIORA_DATABASE_URL" -c \
  "SELECT enabled, plan_tier, token_fingerprint IS NOT NULL AS has_credential,
          concurrent_budget, acknowledged_at FROM tunnel_integration;"
```

No row at all means it has never been configured. Enabling requires the one-time
acknowledgement and, for the paid tier, a stored credential.

### 1.2 `TUNNEL_NODE_DISABLED` (409) — this node does not take part

The message and `error.details.layer` say which of the two layers refused.

* `layer: "node_settings"` — the platform's per-node switch. Turn it on from the node's
  port-forwarding page, or:
  ```bash
  psql "$CLIORA_DATABASE_URL" -c \
    "SELECT node_id, enabled, allowed_ports, max_tunnels FROM node_tunnel_settings;"
  ```
* `layer: "node_local"` — the node's own configuration, **or an agentd too old to support
  port forwarding**. The platform cannot override this one:
  ```bash
  # On the node:
  grep -A4 '^tunnel:' /etc/agentd/config.yaml     # tunnel.enabled: false is an absolute veto
  agentd --version
  ```
  Only the node's owner can change it. There is no platform path that overrides a veto, and
  adding one would be a change to ADR 0022 D17, not a fix.

### 1.3 `TUNNEL_PROVIDER_NOT_CONFIGURED` (409) — prerequisites missing

Answered from what the node last reported, before any connection is attempted. Run the node's
own diagnosis:

```bash
# On the node:
agentd doctor
# It answers four questions: is `ssh` present, is the provider reachable, is the host key
# pinned, and does this node's own config veto port forwarding.
```

The egress check is refreshed at most every five minutes, so a freshly fixed firewall can take
that long to show up. The console shows the report's age next to it for exactly this reason.

### 1.4 `TUNNEL_PROVIDER_UNTRUSTED` (502) — the host key did not match

This is what an intercepted outbound connection looks like. It is *also* what a legitimate key
rotation by the provider looks like, and the two are indistinguishable from here.

**Do not disable host key checking.** A repository-wide gate
(`backend/tests/test_security.py::test_no_source_disables_provider_host_key_verification`)
exists to stop that being the fix, because the symptom of the wrong choice is that everything
works again.

Symptom of a provider key rotation: **every** tunnel on **every** node fails with this code at
about the same time. Symptom of interception: one node, or one network.

Rotation procedure:

```bash
# 1. Get the current key over a path you trust, and compare with the deployed one.
ssh-keyscan -p 443 -t rsa free.pinggy.io 2>/dev/null | ssh-keygen -lf -
ssh-keygen -lf daemon/internal/tunnel/pinggy_known_hosts
# 2. Confirm the new fingerprint against the provider's published value out of band.
#    As measured in PG-01, free/pro/a.pinggy.io share one RSA 4096 key.
# 3a. Out of band, ahead of a release: write the new key to /etc/agentd/pinggy_known_hosts
#     on the affected nodes. A node's own file overrides the keys built into the binary,
#     which is what makes a rotation fixable without shipping one.
# 3b. In the repository, for every node that follows: update
#     daemon/internal/tunnel/pinggy_known_hosts (keep the old line commented with the
#     date). It is embedded at build time, so the next release carries it and the
#     per-node files can be removed again.
# Then on one node:
agentd doctor   # prints which of the two is in effect
```

### 1.5 `TUNNEL_PROVIDER_UNAVAILABLE` (502) — the provider could not be reached

Usually a network path problem on the node, not a platform fault.

```bash
# On the node:
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/free.pinggy.io/443' && echo "443 reachable"
```

Note the fragility recorded in ADR 0022: failure classification matches the provider's own
stderr strings. If the provider rewords its messages, other failures — including the host-key
one — degrade into this code. If `_UNTRUSTED` stops ever appearing, suspect that rather than
concluding the fleet is safe.

---

## 2. Credentials

### 2.1 The encryption key

```bash
openssl rand -base64 32          # 32 bytes, base64. Anything else fails at startup.
# Set CLIORA_SECRET_ENCRYPTION_KEY in Central's environment and restart.
curl -s localhost:8000/readyz | jq .tunnel_integration
# "available" or "unavailable: no encryption key"
```

Rules:

* **Unset** — the integration cannot be enabled and no credential can be stored
  (`SECRET_KEY_MISSING`). Central stays *ready*: one feature being unavailable is not a replica
  being unhealthy, and most deployments do not use this one.
* **Lost** — the stored credential is unreadable. Ask an administrator to enter the token
  again. There is nothing to restore.
* **Rotating the key** — decrypt-and-re-encrypt is not implemented. Procedure: set the new key,
  restart, then re-enter the token in Integrations. Existing tunnels keep running; the
  credential is only read when a *new* tunnel is opened.
* **Platform compromise** — treat the provider credential as disclosed. Revoke it at the
  provider, issue a new one, and paste the new one in. The fingerprint in the audit trail
  (`integration.credential_set`, and `tunnel.create` for each tunnel) is what tells you which
  tunnels were opened with the old one.

### 2.2 The provider token

The subscription is the user's own: the platform stores one token, calls no provider management
or billing API, and holds no account.

```bash
# What is stored, without any of it being readable:
psql "$CLIORA_DATABASE_URL" -c \
  "SELECT token_fingerprint, plan_tier, updated_at, updated_by FROM tunnel_integration;"
```

* Replacing the token affects **new tunnels only**. Existing ones keep running with the
  credential they were opened with, until their TTL or the provider ends them.
* Clearing the token drops `plan_tier` back to `free`, because Pro without a credential is a
  combination that can only fail later.
* **Name the person responsible for renewing it.** A subscription that lapses looks exactly
  like a credential that stopped working: the provider silently issues anonymous free tunnels
  instead of refusing, and the platform tears them down as `TUNNEL_PROVIDER_UNAUTHORIZED`.
  Record the owner in `docs/release-checklist.md` before enabling the integration.

---

## 3. Things that surprise people

| Situation | What is actually happening |
|---|---|
| "The URL stopped working after an hour" | Free tier: the provider ends the tunnel at 60 minutes; the daemon reconnects and the provider assigns a **new** URL. Any link pasted into a ticket or a chat is short-lived by design (D9). |
| "I changed the password and now the link is dead" | `rotate-password` closes the tunnel and opens a new one — the provider fixes its options at connection time, so there is no in-place edit. The response and the UI both carry the new URL. |
| "The app says 'Blocked request. Host not allowed'" | The app receives the *tunnel domain* as `Host` (measured, PG-01 #11), and dev servers like Vite and Next refuse unknown hosts. Tick "rewrite Host" when creating the tunnel — at the cost of the app's own absolute URLs pointing back at loopback. |
| "The URL contains an IP address" | Free tier hostnames embed the node's public IP. Anyone with the link learns the machine's address. |
| "I disabled the integration but tunnels are still up" | Deliberate (04 §0.2). Disabling stops new tunnels; closing the existing ones is a separate button that reports each tunnel, because a node that is offline cannot be told and a switch must not hide a partial failure. |
| "Who opened this preview?" | Unanswerable. The traffic never reaches the platform, so there is no access log — a capability gap, not a privacy feature. |
| "It worked, but the tunnel was anonymous" | The provider answers an unusable credential by downgrading rather than refusing. Both the daemon and Central reject that and report `TUNNEL_PROVIDER_UNAUTHORIZED`; check the credential fingerprint. |

---

## 4. Cleaning up on a node

```bash
# What this daemon believes it is running:
ls -l /run/agentd/tunnels/
pgrep -af 'ssh -p ?443'         # the child processes

# A hard-killed daemon reaps the previous generation on restart; if you must do it by hand,
# match on the pid file rather than on a pattern that also matches your own shell:
for f in /run/agentd/tunnels/*.pid; do kill "$(cat "$f")" 2>/dev/null; done
systemctl restart agentd
```

Closing a tunnel from the platform is recorded immediately, but **the URL may keep answering
for a few seconds**: its validity is the provider's to decide, not ours. Say that to whoever
asks why the link still loads.
