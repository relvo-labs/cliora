# `v2.0.0-beta.1` — Collaborative Project Workspace

> **Not released.** This note exists so the release it describes can be reviewed before it
> happens. Three exit conditions are open and two of them are somebody's signature; see
> **Known limitations** and `plan/26/12` §1.

## What this version is

One sentence:

> **The same fact does not get six different renderings.** Board, Backlog, List, Task
> Drawer, My Work and Project Overview all ask one function how a card is doing, and
> "which things are waiting for a person, and that person is me" now has an entrance that
> does not require opening a project.

`alpha.2` made a sentence happen once. `alpha.3` made every sentence an agent reads say
where it came from. This one makes every screen agree.

## What is new

**Attention, in eight levels with one order.** Every card can say why it needs a person:
waiting for your reply, pending approval, verification failed, run failed, no eligible
runner, assigned runner offline, dependency blocked, stalled. The order is defined once,
in the server, and no screen re-derives it.

**Two of those eight are not in the database, and the product says so.** Whether a runner
is online is a fact about *this process*, not a column — ADR 0029 §1 refuses to store a
copy that goes stale. So attention is evaluated in two phases, those two levels cannot be
sorted on, and when the process cannot answer, the interface says *we could not look*
rather than showing zero. That distinction is the difference between a person going to do
something else and a person reloading.

**A work board with saved questions.** Filter over fifteen fields with eight operators,
group by eight things, sort by seven, save any of it as a personal or a shared view, and
share the URL. Quick filters change the URL and never somebody else's saved view.

**A card has a position.** `tasks.rank` is a sortable string, so moving one card writes one
row instead of renumbering a lane — and refreshing the board no longer reshuffles it.

**A Drawer instead of a navigation.** Opening a card keeps the board, the filter and the
scroll. The conversation is second in the Drawer rather than last, because the thing people
do is *scan → open → answer → carry on scanning*.

**My Work.** Six sections across every visible project, answering the one question this
product exists to answer.

## What is deliberately absent

* **No new outbound connection, and no new inbound channel.** Freshness is a twenty-second
  poll of one endpoint, paused when the tab is hidden. A browser WebSocket would be a new
  authenticated channel, a new subscription-authorization problem and a new backfill
  problem — `beta.2`.
* **No new permission.** Twenty-seven RBAC actions, unchanged. Six new endpoints, all
  answering questions about cards the caller can already read.
* **No daemon change.** Zero diff, `agentd` 0.14.1, contract 1.13.0 — asserted by a gate
  rather than claimed.
* **No `stage` migration.** `blocked` is still a legal stage and the read model projects
  it; unpicking the transition is `beta.2`'s `HD-06`.

## Known limitations

**Two exit conditions are open, and this is the important part of the note.**

1. **SR-3 has no named sign-off.** A security review signed by the person who wrote the
   code is not a review.
2. **`v2.0.0-alpha.3` was never tagged**, because *its* two exit conditions are open — the
   Railway `pg_trgm` check and SR-2's signature. `beta.1` was built on top of that anyway,
   by explicit human decision, and the consequence is recorded rather than hidden: **SR-3's
   scope now contains UI built on an unsigned knowledge layer** (`plan/26/12` §2.7). If
   SR-2 asks for changes to `KN-11`, `PX-62` changes with it — on a surface SR-3 has
   already reviewed.
**All six journeys have now run** and all six pass: J2, J10 and J16 in a browser, and J1
(32/32), J4 (13/13) and J15 (8/8) against a real daemon — a real `agentd` 0.14.1 node
claiming real runs. J1 is the non-degradable one: one vague sentence walks to `done`, and
the last assertion is that this project's `terminal_sessions` count is zero.

An earlier draft of this note said those three "need a real daemon" as though the machine
could not provide one. It could. **Running them found three defects** no in-process test
could reach — the first two had been shipped and unnoticed:

* `derive_attention` showed **no attention** for a card whose agent asked a question and
  then exited, which is the shape the CLI recommends. The person it was waiting for could
  not see that it was waiting;
* the console's "send this requirement to an agent" button had been silently dropping
  `card_kind` and `requirement_id` **since V2.5**, so the requirement flow never started;
* nothing in the console could tick a readiness item, so PX-30's "fill it in" had nowhere
  to go.

All three are fixed in this release. The browser half of the same suite found four more,
all of them things a person would have hit on the first afternoon:

* the Drawer's "this setting is why the card is stuck" block read the *winning* badge, so
  it stayed collapsed on a card that was both waiting for approval and had no eligible
  runner — the situation was true and the interface refused to say why;
* the board could not be un-filtered at all: selecting 全部卡片 deleted the URL key, and an
  absent key means "apply the project's default". `?view=all` says it now;
* every selected view was labelled 已修改 with a Revert button beside it, because an
  untyped filter compared unequal to the view's saved one;
* three of the browser specs were asserting against a landing route and a board component
  this release replaced — a baseline test is the one most likely to rot, because nobody
  re-reads a screenshot.

Also true, and smaller:

* **`ProjectRunsView` does not exist.** The plan listed it; there is no endpoint that lists
  a project's runs, and adding one is a new endpoint rather than a view.
* **A rollback loses saved views** unless they are exported first. There is no feature flag
  to turn the new interface off — that was a deliberate choice — so `downgrade 0043` is the
  only rollback, and it drops `work_views`. `scripts/px/rollback-drill.sh` makes the export
  step 1.
* **`changes_requested` is not a value the platform can produce.** The plan listed four
  human-decision states; the data supports three. Un-approving a gate deletes the key, so
  "a reviewer asked for changes" and "nobody has looked" are the same row.
* **Attention's two runtime levels are per-process.** Central runs one worker today, which
  is the only reason that is currently harmless.
* **The staleness threshold is a guess.** Seven days, chosen because it is a working week,
  and listed as an open measurement.

## Security delta

**Zero new trust boundaries.** That is a short sentence for a security section, so here is
why the list is empty rather than unwritten:

* no new outbound connection (`httpx` still reaches one module);
* no new inbound channel — no browser WebSocket, no webhook;
* no new credential, no new secret path;
* no new RBAC action, and the run token's scope is unchanged at two actions;
* **three fields were added to the agent's deny list**, not removed from it: an agent may
  not set `is_blocked`, `blocking_reason` or `rank` on its own card. The first two would
  clear the dependency gate; the third would make the queue's first-in-first-out advisory.

What did grow is the **read** surface: six endpoints that can return cards from more than
one project. The predicate that decides which projects is in one function with an AST gate
on it, and the honest limit of that guarantee is written down: this deployment has no
per-project membership, so an isolation test here cannot fail. The gate defends the number
of places that change when membership arrives, which is what can actually be promised
today.

## Upgrading

One migration, `0043`, entirely additive: a `work_views` table, four columns on `tasks`,
four indexes, a rank backfill and five seeded views per project. It is reversible.

**The rank backfill orders by `updated_at DESC, id DESC`** — the same order the old board
displayed — so the first screen after the upgrade looks like the last screen before it.

**Old links keep working.** `/projects/:id?tab=board` redirects to
`/projects/:id/work` and keeps every other query key, including `?task=`.

## Data retention delta

* **`work_views` is new long-lived data.** A shared view is soft-deleted (colleagues hold
  links to it); a personal one is deleted outright.
* **`rank`, `is_blocked`, `blocking_reason` and `blocking_message` are part of the card**
  and follow its lifetime.
* Nothing here has a retention timer, and nothing here is deleted by one. The question to
  ask of each is "who cleans this up", and the answer for all four is "the card's owner,
  by deleting the card".
