# Runbook — a conversation acted on an answer twice (or not at all)

**Alerts:** `ClioraConversationDuplicateTurn` (critical),
`ClioraConversationQuestionExpirySurge` (warning),
`ClioraConversationTurnsStalled` (warning)
**Drill:** none — see §6, and that absence is deliberate.

---

## 1. Symptom

A ticket's conversation is the platform deciding, on a person's behalf, that answering a
question meant "carry on". Two things can go wrong with that, and this runbook covers
both directions:

| Alert | What it means |
|---|---|
| `ClioraConversationDuplicateTurn` | **One answer started two agent turns.** The agent replied twice, or pushed twice. |
| `ClioraConversationTurnsStalled` | Answers are going in and **no turn is coming out**. |
| `ClioraConversationQuestionExpirySurge` | Questions are ageing out unanswered; those cards are back in `blocked`. |

The first one has **no other symptom**. The platform keeps working, the board looks
normal, and the only trace is that somebody's agent did the same work twice.

## 2. Immediate impact

| | |
|---|---|
| A `delivery: none` or `artifact` card | Duplicated work, wasted compute, two near-identical messages on the card. |
| A `branch` or `pull_request` card | **Two pushes to the same branch.** Check the branch before anything else. |
| The card's readiness | Unaffected. A turn cannot approve anything; only a person can. |
| Other cards | Unaffected — the uniqueness is per `(parent_run_id, resumed_question_id)`. |

## 3. Diagnose

**The first query is the one that matters**, because it separates a real duplicate from a
counter that was incremented wrongly — two very different jobs.

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT parent_run_id, resumed_question_id, count(*)
  FROM task_runs
  WHERE resumed_question_id IS NOT NULL
  GROUP BY 1, 2
  HAVING count(*) > 1;"
```

- **Rows returned** → the uniqueness was actually broken. Confirm the index is still
  there; if it is missing, that is the incident:

  ```sh
  psql "$CLIORA_DATABASE_URL" -c "\d+ task_runs" | grep uq_task_runs_continuation
  ```

- **No rows** → the counter fired without a duplicate existing. Still a defect, but
  nothing was executed twice. Record it and stop paging.

For `ClioraConversationTurnsStalled`, the same split applies. Answers that land on a run
which is **still polling** close the question without creating a turn — that is D67 and
it is correct:

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT r.status, count(*)
  FROM task_questions q JOIN task_runs r ON r.id = q.run_id
  WHERE q.answered_at > now() - interval '1 hour'
  GROUP BY 1;"
```

All `waiting_for_input` → the alert is the known false positive; nothing is wrong.
Anything else → the continuation path is failing, and the next place to look is the
`run.complete`/`run.offer` traffic for that node.

For the expiry surge, list what is now blocked:

```sh
psql "$CLIORA_DATABASE_URL" -c "
  SELECT t.card_ref, q.created_at
  FROM task_questions q JOIN tasks t ON t.id = q.task_id
  WHERE q.state = 'expired' ORDER BY q.created_at DESC LIMIT 20;"
```

## 4. Act

1. **Stop the bleeding**: disable the runner so no further turns start.
   ```sh
   curl -X PATCH "$BASE/api/agents/$RUNNER_ID" -H "authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d '{"enabled": false}'
   ```
2. **Preserve the evidence.** Do not delete runs. The duplicate rows and their logs are
   the only record of what ran twice; run logs expire on their own in 14 days.
3. For a branch or pull-request card, inspect the branch for duplicated commits before
   re-enabling anything.
4. Re-enable the runner only once the first query in §3 returns no rows.

## 5. Verify

```sh
curl -s -H "X-Metrics-Token: $TOKEN" "$BASE/api/metrics" | grep conversation_
```

`cliora_conversation_duplicate_turn_total` must stop increasing. A non-zero total is
permanent — the counter never goes down — so **verification is that the rate is zero**,
not that the number is.

Anything this counter recorded belongs in the next release note: a duplicate turn that
happened once and was fixed quietly is indistinguishable, later, from one that never
happened.

## 6. Why there is no drill

The other five runbooks have one, because their alerts can be provoked without lying:
saturate a queue, stop a daemon, exhaust a pool. This alert fires on a **broken
invariant**, and the only way to provoke it would be to drop
`uq_task_runs_continuation` on a live database — which is the incident, not a rehearsal
of it.

What stands in for a drill is `scripts/cv/journeys/j8_concurrent.py`: ten concurrent
answers to one question, asserting one message and one turn. It exercises the path this
alert watches, in a database nobody depends on.
