# Runbook — terminal queue saturation

**Alerts:** `ClioraTerminalQueueNearLimit` (warning), `ClioraTerminalQueueOverflow` (warning)
**Drill:** `scripts/p4/drills/queue-saturation.sh`

---

## 1. Symptom

Terminal output is arriving faster than a browser can consume it. Each browser has its
own bounded queue (`terminal_queue_max_bytes`, 4 MiB; `terminal_queue_max_frames`,
1024). When one fills, that connection is closed with an explicit `terminal.gap` and
WebSocket code 1013 — it is **not** allowed to grow.

The two alerts are a sequence, not alternatives:

- `ClioraTerminalQueueNearLimit` — p95 depth above 80% of the byte bound. The warning
  you can still act on.
- `ClioraTerminalQueueOverflow` — it already happened; a connection was dropped.

## 2. Immediate impact

| | |
|---|---|
| The affected browser | Disconnected, then reconnects automatically. Sees an explicit gap marker — the UI never pretends the stream was continuous. |
| Its CLI session | **Unaffected.** tmux keeps running and keeps its scrollback. |
| Other browsers on the same session | Unaffected: the bound is per connection, so one slow client cannot starve the others. |
| Central memory | Bounded by construction. This alert is the bound *working*, not a leak. |

That last point matters for triage: an overflow is contained by design. Treat a
*sustained rate* as the problem, not any single occurrence.

## 3. Diagnose

```sh
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics | grep -E \
  'terminal_client_queue|terminal_queue_overflow|active_terminal_connections'
```

Read them together:

| Pattern | Reading |
|---|---|
| Overflow on one connection, depths otherwise low | One slow client: a laptop asleep, a throttled background tab, a bad network. Contained; no action. |
| Depths high across many connections | Output volume changed — a CLI in a verbose loop, a build streaming to stdout. |
| Overflow with `reason="control"` | Different and more serious: a *control* frame was dropped, so a browser may never learn its session exited. Check for a client that stopped reading entirely. |
| Depths high and `cliora_active_terminal_connections` also high | Capacity, not a fault. Compare against the P4-11 numbers in `capacity.json`. |

Find the noisy session from the log rather than from metrics — session ids are
deliberately not metric labels:

```sh
journalctl -u cliora-central --since '15 min ago' | grep -E 'terminal_gap|queue_overflow'
```

## 4. Mitigate

- **One slow client:** nothing. It reconnects; the gap is marked.
- **A runaway CLI:** the user (or an Admin) terminates that session. Output stops at the
  source, which is the only real fix — a bigger queue just delays the same failure.
- **Systemic volume:** raising `terminal_queue_max_bytes` trades memory for tolerance.
  Do it with a number from `capacity.json`, not by doubling until the alert stops:
  every byte is per connection, so 500 connections multiply it.
- **Never** remove the bound. Unbounded queues turn one slow reader into an
  out-of-memory kill that takes every other session with it.

## 5. Verify recovery

```sh
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics \
  | grep terminal_queue_overflow_total
```

The counter is cumulative, so it will not fall — check that it has stopped *rising*, and
that p95 depth is back under the 80% line. Then attach to a terminal and confirm typing
echoes without a gap marker appearing.

## 6. Afterwards

- A recurring runaway CLI is a user-education or a tooling issue, not an infrastructure
  one.
- If the bound was raised, record the new value and the evidence in the deployment notes
  — the next person needs to know it was a measured decision.
- Sustained `reason="control"` overflows deserve a bug report: the control budget is
  separate from the output budget precisely so a flood of output cannot starve it, so
  exhausting it means something is wrong beyond volume.
