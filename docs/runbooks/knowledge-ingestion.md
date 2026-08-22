# Runbook — project memory has stopped keeping up

**Alerts:** `ClioraKnowledgeDeadLetterAging` (warning),
`ClioraKnowledgeIngestLagHigh` (warning),
`ClioraKnowledgePendingBacklog` (warning)
**Drill:** none — see §6.

---

## 1. Symptom

All three alerts describe one thing from three angles: **facts that exist in the
platform are not reaching the search index.**

| Alert | What it means |
|---|---|
| `ClioraKnowledgeDeadLetterAging` | A job gave up over an hour ago and nobody has looked. That source type has been stale ever since. |
| `ClioraKnowledgeIngestLagHigh` | Jobs are running, but P95 from "fact happens" to "fact is findable" is over a minute. The budget is 10 s. |
| `ClioraKnowledgePendingBacklog` | Over 5000 hints queued for half an hour. Either a backfill, or nothing is draining. |

**None of these produces an error anywhere a user can see.** Search returns fewer
results; an agent cites less. A project with genuinely little written about it looks
exactly the same. That is why these are alerts rather than something to notice.

## 2. Immediate impact

| | |
|---|---|
| Agent runs | Continue normally. A context pack with fewer sources is still a valid pack. |
| Correctness of what *is* indexed | Unaffected. Nothing here writes a wrong version — the failure is absence, never staleness in place. |
| A decision approved just now | May not be in the next dispatch's context pack. If the approval matters to a run about to start, hold the dispatch. |
| The card, the board, delivery | Unaffected. This subsystem has no write path into any of them. |

## 3. Diagnose

**Start here.** The first query separates the three causes, and they need different
actions:

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT state, source_type, count(*), min(created_at) AS oldest
  FROM knowledge_jobs
  GROUP BY 1, 2
  ORDER BY 1, 3 DESC;"
```

- **Lots of `pending`, oldest is minutes old, `running` present** → the worker is alive
  and behind. Usually a project that was just switched on: enabling knowledge is also
  the backfill trigger (ADR 0038 §7), so a large project produces one hint per entity
  all at once. Confirm with §3.1 and wait.
- **Lots of `pending`, no `running`, oldest is hours old** → the worker is not running.
  Go to §4.1.
- **Any `dead`** → go to §3.2.

### 3.1 Is this a backfill?

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT p.slug, count(*) AS pending
  FROM knowledge_jobs j JOIN projects p ON p.id = j.project_id
  WHERE j.state = 'pending' GROUP BY 1 ORDER BY 2 DESC LIMIT 5;"
```

One project holding almost all of it, and its `knowledge_enabled` was set recently, is a
backfill. It drains at roughly `BATCH / INTERVAL_SECONDS` ≈ 10 jobs a second per Central
replica. Ten thousand entities is a few minutes, not hours.

### 3.2 Why did a job give up?

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT source_type, external_id, attempts, dead_lettered_at, last_error
  FROM knowledge_jobs WHERE state = 'dead'
  ORDER BY dead_lettered_at LIMIT 20;"
```

`last_error` is a type name and one line by design — the Source health panel shows it to
anyone holding `project.view`, so it never carries a traceback or the entity's content.
For the full picture, find the same job in the application log:

```sh
grep knowledge_job_failed /var/log/cliora/central.log | tail -20
```

## 4. Act

### 4.1 The worker is not running

It starts in `lifespan` and a start failure is logged rather than fatal — Central serves
without it, deliberately (ADR 0038: stale memory is not worth refusing to boot for).

```sh
grep knowledge_worker_start_failed /var/log/cliora/central.log | tail -5
```

A restart re-runs the sweep before entering the loop, so nothing queued is lost:

```sh
systemctl restart cliora-central      # or: railway restart
```

### 4.2 Jobs in the dead letter

Fix the cause first, then re-queue. Re-queuing is safe at any time and any number of
times: **a job is a hint, not content** — the worker re-reads the entity's current state,
so replaying one cannot write anything stale.

```sh
psql "$CLIORA_DATABASE_URL" -c "
  UPDATE knowledge_jobs
  SET state = 'pending', attempts = 0, next_attempt_at = NULL,
      dead_lettered_at = NULL, last_error = NULL
  WHERE state = 'dead' AND source_type = '<type>';"
```

### 4.3 Nothing is dead but a source type is stale anyway

The reconciler is the correctness path and runs every five minutes. It also enqueues
anything the event path missed, so if a source type is stale with an empty queue, the
watermark query for that type is the thing that is wrong — not the worker. Reproduce it
directly:

```sh
uv run --project backend python -c "
import asyncio, uuid
from app.db.engine import get_database
from app.services.knowledge import sources
async def main():
    async with get_database().session() as s:
        print(await sources.WATERMARKS['ticket'](s, uuid.UUID('<project-id>'), 10))
asyncio.run(main())"
```

An empty list when a card is visibly missing from search means the watermark believes it
is already indexed. Check `knowledge_sources` for that card's `source_updated_at`.

## 5. Verify

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT state, count(*) FROM knowledge_jobs GROUP BY 1;"
curl -s -H "Authorization: Bearer $SCRAPE_TOKEN" localhost:8000/metrics \
  | grep -E 'knowledge_(pending_jobs|dead_letter_age_seconds)'
```

Recovered means: no `dead`, `pending` shrinking round over round, and
`cliora_knowledge_dead_letter_age_seconds` back to `0`. Then confirm from the product
side — the project's Knowledge page, "Recently learned" — because the queue being empty
and the index being right are two different claims.

## 6. Why there is no drill

The five drills in `scripts/p4/drills/` each simulate a condition that is hard to
reproduce on purpose. This one is not: switching `knowledge_enabled` on for a project
with content produces the backlog alert, and a job whose entity was deleted mid-flight
produces the dead letter. A script would add nothing that
`UPDATE knowledge_jobs SET state='dead'` does not already do in one line.

## 7. What this runbook does not cover

**Search returning poor results is not this.** These alerts are about facts not being
*present*. A fact that is indexed but not found is a ranking question — the query
degraded to the trigram channel, or the wording differs from the source's, which is
D40's accepted cost. The Knowledge page's "why" line on each result is where that
diagnosis starts.
