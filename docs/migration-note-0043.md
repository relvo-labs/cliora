# Migration `0043` — what it does, how to go back, and what going back costs

- Applies to: `v2.0.0-beta.1`
- Revision: `0043_work_views_and_rank`, from `0042_knowledge_tables`
- Reversible: **yes.** Lossless: **no** — see below.

## Forward

One migration, one transaction, entirely additive.

1. **`work_views`** — a saved question about a project's cards. JSONB filter, two scopes,
   three constraints (`ck_work_views_scope`, `uq_work_views_default`, `uq_work_views_name`).
2. **Four columns on `tasks`** — `rank`, `is_blocked`, `blocking_reason`,
   `blocking_message`. **Not five**: `attention_primary` is never created, because two of
   the eight attention levels are not in the database at all (ADR 0040 §2).
3. **Four indexes** — `(project_id, rank)`, a partial one on `is_blocked`,
   `(project_id, owner_user_id)` and `(project_id, updated_at DESC)`.
4. **A rank backfill**, ordering by `updated_at DESC, id DESC` — *word for word* what the
   old board displayed, so the first screen after the upgrade looks like the last screen
   before it. There is a test for that equivalence.
5. **An `is_blocked` backfill** from `stage='blocked'`, with a derived reason or `unknown`.
6. **Five seeded views per project**, through the same function
   `ProjectService.create()` calls for new projects.

### What the backfill cannot know, and says so

Two of the seven derivation steps the plan listed need to know whether a node is currently
connected. **`alembic upgrade` runs in a process with no node registry**, and ADR 0029 §1
refuses to keep a stored copy of one. Implementing those two steps literally would not
error — it would go quiet: the branch would never be true, its cards would fall through to
`unknown`, and nothing would say why.

So they are absent, and the cards they would have claimed are honestly `unknown`.
`scripts/px/ambiguous-report.py` lists them with their last five activity kinds. On the
fixed dataset that is 20 cards out of 200, all `unknown` — correctly, because they have no
dependency, no waiting run, no verification report and no gate history.

**A card on that list is not held up by being on it.** The read model renders `unknown` as
"blocked, reason unknown" rather than pretending. What the list gates is `beta.2`'s
`HD-06`, the migration that removes the legacy `blocked` stage — that one cannot be
written until somebody has read this.

## Backward

```
alembic downgrade 0042_knowledge_tables
```

Drops the four indexes, the four columns and the table. Verified down-and-up by
`GATE-PX-MIGRATION-ROUNDTRIP` and by `scripts/px/rollback-drill.sh`.

### **Export `work_views` first.**

This is the part to read twice. `plan/26` D117 removed the version flag, so **there is no
switch that turns the new interface off**. `downgrade 0043` is the only rollback, and it
drops the table holding every saved view anybody made.

`scripts/px/rollback-drill.sh` makes the export step 1 and compares before and after, so
that the loss is something somebody chose rather than discovered. Its step 4 passes when a
project has only the five seeded views and **fails when somebody had made one** — which is
the point.

| Lost on rollback | How bad |
|---|---|
| saved views | **Product data somebody made.** Export first. |
| `rank` | Harmless. A re-upgrade rebuilds it from `updated_at`, so the order returns to what it was. |
| `is_blocked` and friends | Harmless. `stage='blocked'` is still there and the old board reads it. |

Three mitigations survive a rollback: the full task page
(`/projects/:id/tasks/:taskId`) is untouched, `/board` is deprecated but still serving, and
wave 0 shipped its visible change three waves early precisely so that feedback arrived
before there was this much to roll back.
