# Runbook — heartbeat loss

**Alerts:** `ClioraNodeHeartbeatLoss` (warning), `ClioraFleetOffline` (critical),
`ClioraAuthorizationDenialSpike` (warning — see §8).
**Drill:** `scripts/p4/drills/heartbeat-loss.sh`

---

## 1. Symptom

A node holds an open WebSocket but its last heartbeat is older than
`node_online_within_seconds` (30 s), so Central stops counting it as online:
`cliora_online_nodes < cliora_active_daemon_connections`.

This is the state that neither "connected" nor "offline" describes — the daemon process
is reachable but not doing its job. It is the exact case the Dashboard's freshness rule
marks `stale` rather than papering over.

## 2. Immediate impact

| | |
|---|---|
| Running CLI sessions | **Unaffected.** tmux owns them; the daemon only attaches. |
| Terminal streaming | Broken for that node while the link is stale. Browsers show the disconnect and retry. |
| New operations on that node | Refused with `NODE_OFFLINE` once the socket actually drops. |
| Other nodes | Unaffected. Nothing is shared between node connections. |

## 3. Diagnose

Start with which of the two alerts fired — they mean different things.

**`ClioraFleetOffline`** — Central is being scraped (so it is up) but *no* node is
connected. Suspect the network path or Central's WebSocket route, not the nodes:

```sh
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics | grep -E 'active_daemon_connections|online_nodes'
curl -s https://<central>/readyz
```

If `/readyz` reports `degraded`, work the database first — the daemon handshake needs it
to verify credentials, so a database outage presents as a fleet-wide disconnect.

**`ClioraNodeHeartbeatLoss`** — some node is stale. Find it, then look at it:

```sh
# Which nodes does Central consider unhealthy, and why?
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" https://<central>/api/dashboard/summary \
  | jq '.blocks.unhealthy_nodes.data.items'
```

On the node itself:

```sh
sudo systemctl status agentd
sudo journalctl -u agentd -n 200 --no-pager | grep -E 'central disconnected|node_auth_failed|registered'
sudo agentd doctor
sudo agentd metrics | grep daemon_
```

`daemon_reconnect_total` rising with `daemon_heartbeat_sent_total` flat is a flapping
link. Both flat means the heartbeat loop is not running — look for a panic or a wedged
process in the journal.

## 4. Common causes, in the order they actually occur

1. **Network path.** A proxy idle timeout below the heartbeat interval silently closes
   the socket. nginx defaults `proxy_read_timeout` to 60 s, which is why the deployment
   config sets it explicitly — check it was not reverted.
2. **The node was suspended or its clock jumped.** Status is computed from a monotonic
   gap, so a clock change cannot cause this — but a suspended VM genuinely stops
   sending.
3. **Credential revoked or rotated.** The daemon reconnects and fails auth. The journal
   shows the refusal; `node_auth_failed` also appears in Central's audit trail.
4. **The daemon is wedged.** No reconnects, no heartbeats, process alive.
5. **Central restarted.** Expected and transient: nodes reconnect with backoff, and the
   Dashboard reports `stale` for the first heartbeat interval rather than claiming the
   fleet is offline.

## 5. Mitigate

- Flapping link → fix the proxy timeout, then `sudo systemctl restart agentd`.
- Wedged daemon → `sudo systemctl restart agentd`. **tmux sessions survive**; users see
  a reconnect and an explicit gap marker if scrollback was dropped.
- Auth failure → rotate the credential from the node detail page, or re-enrol the node.
- Database outage → work `db-exhaustion.md`; the fleet recovers on its own afterwards.

## 6. Verify recovery

```sh
sudo agentd doctor                     # on the node: all [ OK ]
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics | grep online_nodes
```

`cliora_online_nodes` should equal `cliora_active_daemon_connections`, and the node's
Dashboard entry should leave `unhealthy_nodes`. Confirm a user-visible path too: open a
session's terminal and check input echoes.

## 7. Afterwards

- If a proxy timeout caused it, the fix belongs in the deployment config, not in a
  restart.
- If the daemon wedged with no explanation, capture the journal before restarting next
  time — a restart destroys the evidence.

## 8. On `ClioraAuthorizationDenialSpike`

Grouped here because it shares the "something changed about who can talk to Central"
diagnosis, not because it is the same fault.

Check the `reason` label first:

- **`action`** — a role does not hold the permission. Usually a UI regression showing a
  control it should not, or a role changed under a user. Compare against
  `docs/permission-matrix.md`.
- **`scope`** — cross-owner attempts: someone trying to act on another user's session.
  Genuine probing looks like this. Query the audit trail for the actor:

```sh
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://<central>/api/audit?action=authz.denied&limit=50" | jq '.items[] | {created_at, actor, metadata}'
```

A single user generating all of them is a misconfiguration; many users at once is a
deployment problem; unauthenticated bursts are scanning and are already being refused.
