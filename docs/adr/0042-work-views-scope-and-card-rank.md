# ADR 0042 — Saved views, who owns them, and the string that orders a board

- Status: **accepted** (2026-08-27) — with SR-3 and ADR 0040, recorded from the repository
  owner's instruction of 2026-08-27. Adopted as `plan/26`'s D50, D101, D103, D105, D112 on
  2026-08-23.
- **Carried open by SR-3**: `RANK_NEIGHBOR_STALE`'s cross-project case is a 409 today and
  **must become a 404** the day per-project membership lands, because a 409 confirms the
  existence of a card in a project the caller cannot see
  (`docs/security-review-v2p1.md` §3).
- Date: 2026-08-23
- Related: ADR 0028 §1 (the internalised process, whose lanes the default views are
  expressed in), ADR 0033 §5 (`process_overrides` is a JSONB column for the same reason
  `filter_json` is one — a table invites somebody to put a custom item in it),
  ADR 0040 (the read model these views select over), ADR 0016 (RBAC — **no action is
  added here**).
- Requirements: `FR-WORK-006`, `-008`, `-009`.
- Contract: **v1.13.0, unchanged.**
- Ships in: Central (minor), frontend, migration `0043`. `agentd` **0.14.1, zero diff**.

## Context

Two absences, and they are unrelated except that one migration closes both.

**A board has no order.** `tasks` has no `rank`, no `position` and no `order_index` —
`epics` and `user_stories` have one, `tasks` does not. The board is
`ORDER BY updated_at DESC`, so touching any card reshuffles the lane, and there is no way
for a person to say "this one first". There is also no index behind that ordering:
`0023` created `(project_id, stage)` and `(project_id, user_story_id)`, `0039` added one
for proposals, and `(project_id, updated_at)` has never existed.

**A board has no saved question.** Everybody sees the same six lanes containing every
card. "Which of these are waiting on me", "which have no runner", "which are in review"
are questions people answer by scanning, every time, and cannot share.

## Decision

### 1. `work_views` is one table with a JSONB filter, not a filter schema

The filter is a value object: read and written whole, and **no query ever asks "which
views use `priority=urgent`"**. A child table would turn one read into a join and would
need a schema change for every new filter dimension. That reasoning is taken from
kintra's `p2_01_board_views` and is repeated in the migration's docstring, because "why
is this JSONB" is a question every reader asks once.

Three constraints, each removing a state that has no meaning:

| constraint | what it removes | why in the database |
|---|---|---|
| `ck_work_views_scope` | personal-without-owner, project-with-owner | otherwise the permission check is an `if` rather than a join, and the `if` has two call sites within a phase |
| `uq_work_views_default` | two defaults in one project | a partial unique index, so a failed transaction cannot leave two behind and the UI cannot pick one at random |
| `uq_work_views_name` | duplicate names for one owner | partial on `deleted_at IS NULL`, so a deleted view's name is reusable — kintra's shape, kept including that detail |

`uq_work_views_default` forces "change the default" to be **two updates in one
transaction** — clear the old, set the new — which is exactly the pair the audit entry
records.

`layout` admits `roadmap` from the first migration although only `board` and `list` are
implemented. Same reasoning as `BoardDTO.has_more`: a value added later forces every
existing client to handle its absence, while a value present from the start is merely
unwritten.

### 2. Scope is two words, and a view never grants anything

```text
personal   owner_user_id set,  project_id may be NULL (cross-project)
project    owner_user_id NULL, project_id required
```

Creating or changing a **project** view needs `project.manage`. A **personal** view is
editable only by its owner. **No RBAC action is added** — the count stays at 27. A view
is a saved question, and a saved question about cards you may already read is not a new
power.

The load-bearing half is the negative: **a view does not change anybody's permissions.**
A shared view whose filter matches cards the caller cannot see returns those cards
missing, not an error, and not the cards. `visible_fields` shapes the response and
**takes no part in authorization** — there is a test for exactly that, because a field
list is the most natural place for somebody to eventually put a permission.

Deletion is asymmetric on purpose (D112): a **project** view is soft-deleted, because
other people's links point at it and a hard delete turns a colleague's bookmark into a
404 with no explanation. A **personal** view is deleted outright — nobody else has a link
to it, and a graveyard of one person's abandoned views is a table that only grows.

### 3. Every project has views before anybody asks

The migration seeds five project views for existing projects and
`ProjectService.create()` seeds the same five for new ones, **through one function**. A
project without views opens on an empty board, and "the default views only exist on
projects created after the upgrade" is the kind of split nobody notices until a customer
does.

| name | layout | default |
|---|---|---|
| Active Work | board | ✅ |
| Backlog | list | |
| Waiting for Me | list | |
| Blocked | list | |
| Verification | list | |

Seeding is idempotent, because both callers can reach the same project.

### 4. A quick filter changes the URL and nothing else

Clicking a chip writes the URL's filter parameter. It does **not** write the view. The
toolbar then says *modified* and offers **Save as…** and **Revert**. The alternative —
chips that quietly rewrite a shared view — means one person's scan changes what everyone
else sees, and there is no undo for it.

A URL is therefore shareable and reproduces the same question for anybody with the same
permissions. When the encoded filter is too long for a URL the page falls back to
"view id + local storage" and **says so** ("this filter is not included in the link"),
because a link that silently carries less than it appears to is worse than one that
admits it.

### 5. Rank is a sortable string, and a move sends neighbours

`tasks.rank` is a lexicographically ordered string (kintra's `ranking.py`, ported as
pure functions with their three invariants and both test suites). It is **scoped to the
project, not to the lane** (D50): a card that moves between lanes keeps its rank, so
crossing a boundary is one write rather than a renumbering.

A move sends **the identifiers of the cards it lands between**, never an index. On a
filtered board an index does not mean what the server would take it to mean — position 3
of a filtered list is not position 3 of the lane — and the bug that produces is a card
that lands somewhere the person did not point at. One move produces **one**
`UPDATE tasks`, asserted by counting statements.

Ranks are rebalanced when they grow too dense to insert between, and **rebalancing does
not change any card's relative order**. That is the property the invariant tests exist
for; it is easy to write a rebalance that is correct on average.

### 6. `0043` also adds the index the existing board always needed

`(project_id, updated_at DESC)` is the only change in this phase that makes an *existing*
query faster, and it is measured before and after at two sizes. `required_labels` gets
**no GIN index**: a project's cards are in the hundreds, the arrays are short, and GIN's
maintenance cost lands on every card update. If the `contains` operator turns out to be
hot, that is a later migration with a measurement behind it.

## Consequences

**Good.** A board has a stable order that survives a refresh, and moving a card is one
write. Saved questions are shareable without being a permission. The default views exist
on day one for every project, from one function. The constraints make three impossible
states impossible rather than merely refused.

**Bad, and the worst of it is the rollback.** `0043` is fully reversible and **not
lossless**: `downgrade` drops `work_views`, and after `plan/26` D117 removed the version
flag, downgrade is the *only* rollback path — there is no switch to turn off. So the
rollback drill must **export `work_views` to JSON first**, and the drill report has to say
"rolling back loses saved views unless you export them". Losing `rank` is harmless (a
re-upgrade rebuilds it from `updated_at`), and losing `is_blocked` is harmless
(`stage='blocked'` is still there).

**Also bad.** `filter_json` is opaque to the database, so a filter referencing a field
that later disappears fails at read time rather than at write time. The mitigation is the
allowlist compiler (`FILTER_FIELD_NOT_ALLOWED` names the field), not a foreign key.

**Rejected: a filter schema with child tables.** It buys a query nobody runs and costs a
schema change per filter dimension.

**Rejected: per-lane rank.** Moving between lanes would renumber, and a cross-lane drag
would be two writes with a visible intermediate state.

**Rejected: a `view.manage` RBAC action.** Twenty-seven actions is already a matrix
people have to hold in their heads, and this one would be held by exactly the roles that
hold `project.manage`.
