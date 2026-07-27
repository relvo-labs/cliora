# Alert drills (P4-09)

One script per alert in `deploy/prometheus/alerts.yml`. The acceptance criterion for
P4-09 is not "the rule file parses" but **"the alert can be made to fire on purpose and
its runbook can be followed"** — an alert nobody has seen fire is an alert nobody knows
how to handle, and a runbook nobody has walked is a guess.

Each script:

- states what it will do and asks for confirmation, because several are disruptive;
- makes exactly one alert condition true;
- prints the metric to watch and the runbook to follow;
- restores what it changed (or says plainly what it could not).

Record each run in `artifacts/p4/<run>/drills.md` with the alert's fire time, whether the
runbook steps were executable as written, and the recovery time. A step that could not be
followed is a documentation defect to fix, not a note to leave for the next person.

**Never run these against production.** They deliberately break things.

| Script | Alert exercised |
|---|---|
| `heartbeat-loss.sh` | `ClioraNodeHeartbeatLoss`, `ClioraFleetOffline` |
| `queue-saturation.sh` | `ClioraTerminalQueueNearLimit`, `ClioraTerminalQueueOverflow` |
| `timeout-surge.sh` | `ClioraDaemonRequestTimeoutSurge` |
| `db-exhaustion.sh` | `ClioraDatabasePoolPressure`, `ClioraDatabasePoolExhausted` |
| `update-failure.sh` | `ClioraDaemonUpdateFailed` |
