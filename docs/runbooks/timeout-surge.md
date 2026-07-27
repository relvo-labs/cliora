# Runbook — relay timeout surge

**Alerts:** `ClioraDaemonRequestTimeoutSurge` (warning, >10 in 5 min),
`ClioraDaemonRequestTimeoutCritical` (critical, >50 in 5 min)
**Drill:** `scripts/p4/drills/timeout-surge.sh`

---

## 1. Symptom

Requests Central relays to daemons are not being answered within their timeout. Users
see `REQUEST_TIMEOUT` (504) on session, file or update operations.

## 2. Check this first: is it an update?

```sh
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics \
  | grep cliora_daemon_request_timeout_total
```

If the `type` label is `daemon.update`, **this is expected and not a fault.** The daemon
restarts during an update, which drops the socket the reply was travelling on. Central
deliberately treats that timeout as "no answer yet" and leaves the node `in_progress`
until it reports or re-registers — see `update-failure.md` §7.

Only non-update types indicate a problem. Everything below assumes that.

## 3. Immediate impact

| | |
|---|---|
| Running CLI sessions | **Unaffected.** tmux owns them. |
| New sessions, file browsing on affected nodes | Fail with 504 after the per-operation timeout. |
| Central | Bounded: each node's in-flight requests are capped at `pending_requests_max` (128), beyond which callers get `NODE_BUSY` instead of queueing. |

## 4. Diagnose

The `type` label localizes the fault, because the timeouts differ per operation:

| `type` | Timeout | Usual cause when it alone is slow |
|---|---|---|
| `session.start` | 30 s | The runtime binary is slow to launch, or tmux is wedged on the node. |
| `filesystem.list` / `read` / `search` | 15 s | A slow or very large filesystem, or a network mount. |
| `session.attach` | 15 s | tmux attach contention. |
| everything | — | Not the operation: the node or the link. |

Then determine whether it is one node or many:

```sh
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" https://<central>/api/dashboard/summary \
  | jq '.blocks.unhealthy_nodes.data.items, .blocks.nodes.data'
```

**Many nodes at once** → look at Central and the network, not the nodes. Check
`db-exhaustion.md` first: a saturated pool makes every relayed operation slow because the
authorization and session lookups in front of it are queueing.

**One node** → work on that node:

```sh
sudo agentd doctor
sudo journalctl -u agentd -n 200 --no-pager
tmux ls                      # as the node's run user
uptime; df -h                 # load and disk pressure
```

A node under heavy load, out of disk, or with a hung tmux server produces exactly this
pattern. The Dashboard's `resources` block shows the trend if the samples are landing.

## 5. Correlate with the daemon's own view

Central's `request_id` appears in both logs, which is what makes this tractable:

```sh
# Central
journalctl -u cliora-central | grep <request_id>
# On the node
sudo journalctl -u agentd | grep <request_id>
```

If the daemon never logged the request, it did not arrive → link problem. If it logged
receipt but no reply, the daemon is stuck inside the operation → node problem.

## 6. Mitigate

- Wedged tmux → restart the daemon (`sudo systemctl restart agentd`). Sessions survive;
  the tmux server is a separate process.
- Node overloaded → reduce its session count, or disable the node so new sessions go
  elsewhere. Disabling keeps existing sessions running.
- Central-side saturation → `db-exhaustion.md`.
- Raising a timeout is almost never the fix: it converts a visible failure into a slow
  one, and the per-node pending bound then fills instead.

## 7. Verify recovery

```sh
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics \
  | grep -E 'daemon_request_timeout_total|daemon_request_duration_seconds_count'
```

The counter is cumulative — confirm it has stopped rising. Then exercise the operation
that was failing (create a session, browse a file) and watch it complete.

## 8. Afterwards

- If one operation type dominated, its timeout may be genuinely mis-set for this
  environment — record the measured duration before changing it.
- Repeated tmux wedges on one node point at the runtime, not at Cliora; capture the
  daemon log and the tmux server state next time before restarting.
