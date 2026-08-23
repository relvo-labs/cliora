# Runbook — a run finishes, and the card records nothing

**Alerts:** none — this failure produces no alert, which is half of what makes it
expensive. The symptom is a card, not a graph.
**Drill:** point a daemon at a Central that predates `/api/cli/`; see §6.

---

## 1. Symptom

A run is claimed, executes for its full length, and ends **`RUN_DELIVERY_INCOMPLETE`
with zero artifacts and no agent messages.** The timeline looks entirely healthy:

```text
排入佇列 → Runner 認領 → 開始執行 → 執行結束      (13 minutes)
產物：這次執行還沒有附加任何產物。
```

In the run log the agent reports doing the work. On the card there is nothing.

**The work is not lost yet.** It is in the run directory, which has a retention period.
That is the clock this runbook is racing.

## 2. Immediate impact

| | |
|---|---|
| The run's output | Stranded in `/var/lib/agentd/.cliora/runs/<run_id>/`, removed on the retention sweep |
| The card | Reads as though the agent did nothing |
| Other runs | **Every run on this deployment is affected identically.** The cause is configuration, not this card |
| Cost | The full wall-clock of every affected run, and the agent's time re-deriving what it already produced |

## 3. Diagnose

### 3.1 One request settles it

From anywhere that can reach the address in the agent's context pack — **no credential
needed**, and that is the point:

```sh
curl -s -X POST -H 'Content-Type: application/json' -d '{}' \
  "$API_BASE/api/cli/runs/messages"
```

| What comes back | What it means | Go to |
|---|---|---|
| `401` `{"error":{"code":"UNAUTHENTICATED"…}}` | The route exists and the layer is on. The problem is the credential or the card, not the address | §3.3 |
| `404` `{"error":{"code":"NOT_FOUND"…}}` | The route exists; **the project or agent-run flag is off** on this Central | §4.2 |
| `404` `{"detail":"Not Found"}` | **The route does not exist here.** This address is a different or older Cliora | §4.1 |
| `502` / timeout | The edge is up and Central is not | `railway-edge-502.md` |

**The two 404s are different failures and they are identical in a status code.** The
envelope separates them: every refusal Cliora issues carries `{"error":{"code":…}}`. A
bare `{"detail":"Not Found"}` is FastAPI answering for a route that was never mounted.

### 3.2 Which layer is missing

If §3.1 gave a bare 404, find out how much is missing:

```sh
for p in /api/auth/me /api/nodes /api/projects /api/agents /api/cli/tasks; do
  printf '%s -> ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' "$API_BASE$p"
done
```

`auth`/`nodes` answering `401` while `projects`/`agents`/`cli` answer `404` is the
signature of a **V1 Central**: the project layer, the task layer, the agent runner and
the whole `/api/cli/` surface arrived together, and a build without one has none.

### 3.3 If the route exists

Then the address is right and something narrower is wrong:

```sh
head -c 12 /var/lib/agentd/.cliora/runs/<run_id>/.cliora/context/run.token
```

A run token starts `cliora_rt_`. **Do not test it against `/api/sessions/…`** — that
path takes a *session* token and answers `TOKEN_INVALID` for a perfectly good run token.
Worse, `/api/sessions/current` matches `/api/sessions/{session_id}`, so it looks like a
real endpoint rejecting your credential. That misreading is what sent the incident this
runbook came from down an hour of the wrong path.

## 4. Act

### 4.1 The address points at the wrong Cliora

A one-line configuration fault with a whole-deployment blast radius. The context pack
stamps `CLIORA_PUBLIC_BASE_URL` verbatim, and **nothing validates it** — Central may not
call out to check (`SCOPE-013`), and the daemon cannot tell a legitimately different
public hostname from a wrong one.

```sh
# On the Central that dispatches the runs:
echo "$CLIORA_PUBLIC_BASE_URL"     # must be an address that reaches *this* Central
```

Either point it at the Central that is actually running the work, or upgrade the Central
at that address. Then re-dispatch; nothing needs repairing in the database.

### 4.2 A feature flag is off

```sh
CLIORA_PROJECTS_ENABLED=true
CLIORA_AGENT_RUNS_ENABLED=true
```

Both. A deployment that can dispatch a run but answers `NOT_FOUND` on `/api/cli/` has
had one turned off since the run started.

### 4.3 Rescue the output first

Before anything is redeployed or re-dispatched, the run directory is the only copy:

```sh
cp -r /var/lib/agentd/.cliora/runs/<run_id>/artifacts/ ./rescued/
git -C /var/lib/agentd/.cliora/runs/<run_id>/repo log --oneline -5
```

An agent following current guidance leaves its work there and says so. Older agents may
not have; check the repo for unpushed commits before the sweep runs.

## 5. Verify

Re-dispatch the card and confirm the agent can write **before** it does the work:

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT author_kind, kind, left(body, 60)
  FROM task_messages WHERE task_id = '<task-id>' ORDER BY conversation_seq;"
```

One agent message is enough. This failure is total — the channel either works or none of
it does.

## 6. Why there is no alert

No metric separates "this run had nothing to say" from "this run could not say
anything". Both are a run that finished with no messages, and the first is ordinary. The
honest instrument is the card: `RUN_DELIVERY_INCOMPLETE` with zero artifacts on **every**
run, rather than on one, is the signal — and it is a signal a person reads.

A drill is cheap if one is wanted: point a daemon's `CLIORA_PUBLIC_BASE_URL` at any host
that is not a current Central, and dispatch anything.

## 7. What the agent now sees

Since `agentd` 0.14.0 the CLI distinguishes the two 404s itself, names the address, says
that retrying will not help, and tells the agent to keep its output where it is. Before
that it said only `請求被拒絕（HTTP 404）` — unhelpful, and **wrong**: nothing refused
the request. A run showing the old message is running a daemon that predates the fix,
and its output is still worth rescuing (§4.3).
