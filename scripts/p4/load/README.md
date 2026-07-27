# Capacity and boundedness harness (P4-11)

Answers one question with a pass/fail: **does Cliora hold its NFR-003 scale without
anything growing without bound?**

Everything here drives a **real Central over a real socket**. The daemon side is faked at
the protocol level — actual WSS, actual Ed25519 challenge, no tmux — because that is what
lets 100 nodes run on one machine. Real PTY behaviour is covered by the P2/P3 integration
tests; duplicating it here would only make the harness slower and less able to reach the
scale it exists to measure.

## Run it

```bash
# One command, own throwaway database, own port, one verdict.
uv run --project backend python scripts/p4/load/capacity.py --profile smoke   # every PR
uv run --project backend python scripts/p4/load/capacity.py --profile full    # merge / RC
```

Writes `artifacts/p4/local/capacity.json` (override with `--out`) and **exits non-zero if
any bound failed**. That exit code is the point: a harness that only prints numbers stops
being read within a release.

Requires `docker` (for the throwaway PostgreSQL) and the backend venv — the client side
uses `websockets`, which already ships with `uvicorn[standard]`, so measuring the product
adds nothing to its dependency set.

### Scenarios standalone

Each part also runs on its own against a Central you already have listening, which is what
you want while investigating one bound rather than gating a merge:

```bash
uv run --project backend python scripts/p4/load/fake_nodes.py \
    --base-url http://127.0.0.1:8000 --admin-password ... --nodes 100 --central-pid 1234

uv run --project backend python scripts/p4/load/terminal_clients.py \
    --base-url http://127.0.0.1:8000 --admin-password ... --clients 500

uv run --project backend python scripts/p4/load/session_churn.py \
    --base-url http://127.0.0.1:8000 --admin-password ... --cycles 5
```

Pass `--central-pid` when running standalone: RSS is sampled from `/proc/<pid>/statm` of
the **Central** process, and without it the memory-boundedness evidence is absent. The
scenario says so in its notes rather than reporting zeros — a boundedness proof that
quietly measured nothing is worse than no proof.

## What each scenario proves

| Script | Proves |
|---|---|
| `fake_nodes.py` | NFR-003 fleet size, judged from **Central's** node list rather than the harness's socket count; every request to a silenced node resolves rather than hanging, and excess concurrency is shed with a retryable 503 rather than queued; node list and dashboard stay inside their NFR-001 read budgets; Central RSS does not climb across the run |
| `terminal_clients.py` | NFR-001 keystroke round trip p95 **measured while slow and flood clients are active**; a non-reading client is bounded by `terminal_queue_max_bytes`, gets exactly one `terminal.gap`, and is closed; its co-tenants keep receiving (PRD §20.5) |
| `session_churn.py` | `sessions_per_node_max` enforced, and refused with the named `SESSION_LIMIT_REACHED` rather than a generic failure; no session leak after repeated cycles, checked independently on both sides; RSS does not ratchet per cycle |

## Things that are deliberate

**The latency number is a full round trip.** Input carries its own `perf_counter` stamp
and the fake daemon echoes it back, so the measurement spans browser → Central → daemon →
Central → browser. Measuring only the outbound leg would report roughly half the real
figure and pass a budget the product misses.

**Frames carry a tag byte.** Unsolicited filler output is tagged separately from timed
input. Without that, random filler bytes occasionally unpack into a plausible timestamp and
inject fabricated samples into the latency distribution.

**Slow clients need output to stall against.** `--output-rate-bytes` pushes unsolicited
output per session; without it a stalled client sits on an idle socket, never fills the
queue, and the overflow bound goes untested while appearing to pass. When no slow client
reaches overflow the scenario **says so in its notes** instead of counting it as a pass.

**One node is silenced on purpose.** The probe stops a daemon answering *without closing its
socket*, because that is what a hung daemon looks like to Central. Closing the socket would
test the disconnect path instead.

**What that probe actually finds is the database pool, not the pending bound.**
`pending_requests_max` is 128 but `db_pool_size + db_max_overflow` is 20, and a request
cannot occupy a pending slot without first holding a database connection — so the pool
ceiling binds first, by a wide margin, and the excess is shed with a 503. That is correct
behaviour and it is what the check asserts. The harness prints a note saying the pending
bound was **not** reached and cannot be over HTTP at default settings, so nobody reads this
scenario as covering it. If the pool is ever widened past 128 the probe becomes the real
test of the pending bound, which is why both numbers are recorded.

**Its own database, every time.** A load run creates hundreds of nodes and sessions and
deliberately floods and stalls connections. Pointed at a shared database it becomes a
mysterious failure in an unrelated suite later — which has already happened once in this
project, so the harness does not offer the option.

**Bounds are passed in, not discovered.** `pending_requests_max`,
`sessions_per_node_max` and `terminal_queue_max_bytes` are not readable over HTTP, so they
are flags, recorded in the artifact under `bounds_under_test`. If the deployment's settings
differ from the flags the harness is asserting against the wrong numbers — hence recording
them next to the verdict rather than leaving them implicit.

## If you add a script here

Two traps this directory has already sprung, both worth knowing before writing the third
harness:

**Resolve caller-supplied output paths to absolute immediately.** Several scripts run work
inside `(cd backend && ... > "$OUT/log")`, and a redirection to a *relative* path resolves
against `backend/`, not the repo root. The redirect fails, the subshell dies before starting
anything, and the symptom is "the server never became ready" with no log to explain why. It
only appears when the caller passes a relative directory, which is exactly what CI does and
exactly what a hand-run does not.

**Give a scenario a wall-clock budget.** A hung scenario used to hang the whole run and
produce no artifact at all — the worst outcome for a CI gate, because "still running" looks
the same as "passing" to anything watching. `capacity.py` wraps each scenario in
`asyncio.wait_for` and records a timeout as a failed check.

## Reading `capacity.json`

```
verdict.status            pass | FAIL             <- the gate
verdict.failed[]          names of failed checks
environment               host, CPU, RAM, python  <- a capacity number without these is not comparable
bounds_under_test         what the assertions used
scenarios[].checks[]      per-check observed vs limit, including for passes
scenarios[].notes[]       paths that were NOT exercised — read these before trusting a pass
```

`observed` is recorded for passing checks too: a run barely inside its budget is exactly
what the next release needs to know, and a bare `"pass"` throws it away.
