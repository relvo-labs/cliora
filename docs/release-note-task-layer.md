# Release note — V2.1: the task layer, and the tools an agent needs to use it

Ships with `agentd` **0.8.0**, contract **v1.10.0**, migrations `0023`–`0028`.
Design decisions: [ADR 0028](adr/0028-v21-task-layer-session-token-and-projection.md).
Security review: [`security-review-v21.md`](security-review-v21.md).

## What it does

Work becomes something the platform holds. Epics, user stories and task cards live in
six lanes; a card moves by dragging or by a menu; and the process Cliora internalised
from Monstrare stops being prose and starts refusing things.

**It refuses exactly one thing**, and the narrowness is the design: a card cannot enter
`ready` or beyond while a dependency is unfinished, and the refusal names the blocking
cards. The seven Definition-of-Ready items and the WIP advice *report*. Enforcing all
seven from day one is how a board stops being written to, and a board nobody writes to
is a source of truth that lies.

An agent working in a session can now see its card and move it. Opening a session
projects a context pack, the process notes and a **session credential** into
`.cliora/`, and `cliora` — which is the same binary as `agentd` — reads them.

## For operators

- **`agentd` 0.8.0 is required to receive task context.** Older nodes keep working:
  sessions start and run exactly as before, and the console says which version would be
  needed. Nothing is auto-upgraded.
- **`CLIORA_PROJECTS_ENABLED` gates all of it**, as it does the project layer. Off means
  every route 404s, no credential is issued and no projection is sent.
- New: `CLIORA_SESSION_TOKEN_TTL_H` (default 24) — the ceiling on a session
  credential's life. The *first* thing that ends it is the session ending.
- Three new stores, three different answers to "who cleans this up": `activity_events`
  has no retention (product content), the projected files are cleaned by the daemon
  after 30 days, and revoked credential rows are kept 90 days because the audit trail
  names them.
- Removing a node now ends every active session before revoking the node identity.
  An offline node's sessions are failed locally as `NODE_REMOVED`; historical rows
  remain for investigation but leave the fleet Session list and stop consuming quota.
  Migration `0028` repairs rows left active by older Central versions.

## For anyone reading a board

- Six lanes; a card can be dragged, or moved with the **移動到…** menu — the menu is
  the accessible path and the one the tests drive.
- A card's **執行設定** (`source`, `delivery`, …) is an **intent**. Nothing acts on it
  in this release; delivery arrives in V2.3/V2.4. The card says so.
- A review gate records **who** approved it and **when**. An agent cannot approve one —
  its credential does not carry the action, and the endpoint is not on the surface it
  can reach at all.
- The mockup gate shows as **disabled with a reason** when tunnel integration is off,
  rather than sitting there permanently unsatisfiable.

## For an agent inside a session

```
cliora context show                 # reads a local file — works with Central down
cliora task list
cliora task get TASK-12
cliora task update TASK-12 --stage implementing --note "開始"
```

When Central is unreachable the write commands fail immediately — no queue — and say:

> 無法連線到 Cliora（Session 可繼續工作）。
> 你的變更未被記錄，恢復連線後請重新執行。

The second line is the point. The platform being down does not stop the work.

## Known limits, stated rather than discovered

- A card declaring `delivery: pull_request` produces no pull request in this release.
- The credential lands in the workspace, so anyone who can read that directory can read
  it. Contained by a 24-hour ceiling, revocation on session end, and a scope of two
  actions in one project — not fixable, because the agent has to read it.
- Only `dependsOn` is enforced; the Done Gate's verification clauses arrive in V2.4.
- The Requirements tab has intake, review and acceptance. The *clarification* screen is
  V2.5: it reuses the card message thread, which V2.2 builds.
