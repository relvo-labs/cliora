# ADR 0044 — Deleting `/board`, and keeping the measurement that justified its shape

- Status: **accepted** (2026-08-28) — `plan/27`'s D126, executed by `HD-07`.
- Date: 2026-08-28
- Amends: ADR 0028 (**amendment D** — §1 there introduced the board read as the project's
  single card query; this removes it and names its replacement).
- Related: ADR 0040 (the read model that replaced it), ADR 0042 (the views selecting over
  that model), `plan/26`'s D48 (which chose a new endpoint over extending this one),
  `plan/26`'s D118 (which deprecated it and scheduled this deletion).
- Requirements: none new. `FR-TASK-004` is served by `work-items` from this release.
- Contract: unchanged (**1.13.0**). `/board` is HTTP, not protocol; no node sees it.

## 1. What is deleted

```text
GET /api/projects/{project_id}/board          api/http/tasks.py::read_board
BoardDTO / BoardLaneDTO / BoardCardDTO        api/http/schemas.py
TaskRepository.board_cards()                  repositories/tasks.py
TaskService.board()                           services/tasks.py
BoardCard                                     repositories/tasks.py
ApiClient.getBoard() + Board types            frontend/src/api/client.ts
GATE-PX-BOARD-UNCHANGED                       scripts/px/gates.sh
test_the_board_card_stays_a_summary           backend/tests/db/test_tasks_api.py
```

`work-items` replaces it. The last runtime consumer left with `ProjectDetailView.vue` in
V2-P1; `getBoard()` had **zero call sites** when this was written, which is the evidence
that made the deletion a deletion rather than a migration.

## 2. Why this ADR exists at all

Deleting an endpoint does not normally need one. This one does, because the thing being
deleted **carries a measurement that three later decisions were built on**, and that
measurement lives in the docstring of a test that is going away with it.

Recorded here so it survives the file:

> **M1** (`plan/17/10-…md` §1). At 200 cards the full card shape is **439 KB** and at 500
> cards it is over a megabyte. The summary shape — no acceptance criteria, no gate detail
> — is **74 KB** at 200 and **180 KB** at 500.
>
> That difference is what **replaced pagination**. `BoardDTO.has_more` was shipped
> permanently `false` for exactly this reason: the shape was made small enough that a
> cursor, a scroll loader and an e2e for both were not needed.
>
> **After `plan/19`** added three columns (active run status, runner name, a fixed
> waiting-reason enum) the same 200-card fixture measured **89,251 bytes against a 90,000
> byte budget** — 99.2% of it.

Three decisions read that measurement and are still live:

| Decision | What it took from M1 |
|---|---|
| `plan/26` D48 | Do not extend `BoardCardDTO` with the 13 proposed fields; open `WorkItemCardDTO` instead. The pinned test *was* the argument |
| `plan/26` D94 | Do not copy the upstream 160 KB budget for the new DTO. **Measure first**, then pin at measured + 15% — because the 74 KB the upstream figure doubled was four months stale |
| `plan/27` D126 | This ADR |

**A number that three decisions depend on should not live only in a deleted file's
docstring.** That is the whole content of this ADR.

## 3. What replaces the pin

`BoardCardDTO`'s byte budget was enforced by `test_the_board_card_stays_a_summary` and by
`GATE-PX-BOARD-UNCHANGED` (which asserted the field count stayed at 16). Both go.

The equivalent pin on the replacement already exists and stays:

```text
backend/tests/db/test_work_items_size.py     WorkItemCardDTO, measured then pinned (D94)
```

So the *property* — a card that renders a board must stay a summary — keeps an enforcer.
What is lost is the enforcement on a shape nothing renders any more.

## 4. What is deliberately **not** deleted

**The `?tab=` redirect** (`frontend/src/router/index.ts`). Its consumers are bookmarks,
chat logs and other people's documents — a set no static analysis can enumerate.

`plan/27` D126 said to measure it with a `legacy_route_hit_total` counter and delete it at
zero. **That mechanism does not exist and cannot**: the redirect runs inside vue-router,
and the SPA is served by nginx (`deploy/nginx/nginx.conf`, `location /`). The FastAPI app
is never asked for `/projects/:id?tab=board`, so no counter in `app/metrics.py` could ever
increment. Adding one anyway would have produced a permanent zero that reads as "nobody
uses this" — the strongest possible evidence for a deletion, manufactured by the
instrument. That is the `plan/26` D97 defect (a machine code with no raise point) wearing
a different hat, and it is worse here because the empty metric would have been *believed*.

**So the condition is announcement, not measurement:**

1. The `beta.2` release note states that `?tab=` is deprecated and names `rc.1` as its
   removal.
2. It is removed in `rc.1` **regardless of usage**, because usage is not observable from
   inside this system.
3. If an operator wants evidence before then, it is in the nginx access log and nowhere
   else: `grep -c 'tab=' access.log`. That is written down here because "check the logs"
   is not a plan unless somebody has said which log and which string.

The general rule, restated with what this cost to learn:

```text
consumers are code                  → grep reaches zero → delete
consumers are links, and the server
  sees them                         → measure, delete at zero
consumers are links, and the server
  never sees them                   → announce a date, delete on it
```

`legacy_blocked_at` (ADR 0040's amendment, arriving with `HD-06`) is the first class.
`/dashboard`'s alias is the third, not the second — it is also client-side routing, and
the same correction applies to it.

## 5. Rollback

`/board` is a read endpoint over unchanged tables. Restoring it is reverting a commit;
no data was migrated and no column was dropped for it. The four callers listed in §1 are
the whole of it.

**One thing does not come back by reverting**: the two tests deleted in §1 pinned a shape
that, after this release, nothing produces. Re-adding them would require re-adding the
DTO, which is the point of the deletion.
