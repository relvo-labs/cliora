---
name: cliora-project-context
description: >-
  Route Cliora work to the canonical PRD, visual specification, and technical plan while preserving scope and trust boundaries. Use when changing, reviewing, testing, or documenting any Cliora API, frontend, daemon, terminal, workspace, session, authentication, deployment, or product behavior.
---

# Cliora Project Context

Use this as the entry point and pair it with a domain skill.

1. Inspect the repository; do not assume planned directories exist.
2. Read only relevant sources: `research/prd.md` for behavior and scope, `research/style.md` for visual rules, and `research/tech.md` for architecture, protocol, security, tests, and deployment.
3. Find headings or requirement IDs with `rg` before reading large ranges.
4. State governing requirements and material assumptions.
5. Route to the domain skill, make the smallest coherent change, and verify risk-bearing behavior.
6. Report source sections and tests.

Route Central API/data to `backend-developer` and `fastapi`; daemon work to `go-daemon-development`; wire changes to `terminal-websocket-protocol`; Vue work to `vue-naive-ui-workflow`; and reviews to UX, security, and web testing skills.

Preserve native Claude/Codex terminal semantics, outbound daemon WSS, browser-independent sessions, allowed-root access, and explicit correlation/backpressure/timezone behavior. Do not introduce Central SSH, arbitrary shell commands, PostgreSQL terminal logs, a Web IDE, **automatic task assignment**, or multi-agent orchestration without a requirements change. The console reads and adds files; it does not edit, move or remove them.

V2 scope change (ADR 0027, accepted 2026-08-08) — read the three clauses precisely, because each withdraws less than it looks like. **Task routing**: the platform manages task *records* and lets an agent *claim* work; it does no automatic assignment, scheduling optimisation or load balancing, and a card's "assigned agent" is a filter in that agent's own poll query, never a push. **Git automation**: still refused today; from V2.3 it opens only inside the `cliora/<card_ref>-<run_seq>` namespace under five constraints hard-coded in the daemon — never onto a base, target or protected branch, and **never an auto-merge** (`SCOPE-014` guards all four with real gates). **Multi-agent orchestration**: one agent running a whole flow is *not* orchestration; cross-agent collaboration and agents dispatching to each other remain out of scope.

V2 project layer (ADR 0027, accepted): a Project is platform data, not files in the user's repository — `.cliora/` is the only thing ever projected into a workspace, and never `.claude/` or the node's `~`. A workspace binding is a shortcut, never an authorization: `sessions.authorize_workspace()` runs when binding **and again on every use**, because roots get disabled. Node removal is a soft delete, so bindings disappear by service-layer filtering rather than by cascade. The project timeline hides actor identity from anyone without `audit.view`, the same rule `services/dashboard.py::project_for` already applies — `project.view` is held by all three roles, so copying a timeline that carries actor names reopens a channel P4 closed. A feature flag is not a permission: `features` says what the deployment has, `permissions` says what the person may do, and the server checks both.

V2.1 task layer (ADR 0028, accepted): epics, user stories and task cards are platform data, and the internalised process **refuses exactly one thing** — a card entering `ready` or beyond with an unfinished dependency, named by `card_ref` in the error. Definition-of-Ready and WIP report; they do not refuse, because a board that refuses everything stops being written to. A review gate stores `{approved_by, approved_at}`, never a boolean: an agent's output is not an approval. The platform's own write path into a workspace is `.cliora/{context,process,reference}/` and **nothing else** — a second daemon verb, disjoint from the user upload path (which is refused there), never overwriting, cleaned by the daemon after 30 days, and forbidden to touch `.cliora/uploads/` or a `.gitignore` the user may own. The agent's session credential holds two actions and **never resolves into a `User`**: `get_agent_principal` is a separate dependency, `AgentPrincipal` deliberately carries no `user_id`, and an agent write is audited as a non-human actor rather than as the person who opened the session. When Central is unreachable the CLI fails immediately and says the session can keep working — no offline queue, by decision.

Workspace write posture (ADR 0024 + ADR 0026, accepted): the workspace is **no longer read-only**; preview stays read-only. Every write path must satisfy four rules: confined by `workspace.Root`, bounded, audited per write, and refusable by the node with the refusal reported. "Bounded" means per-operation size plus cumulative quota plus — for a **platform-owned** destination — a retention period; where the **user** chooses the destination, retention is replaced by **visibility**, because deleting the user's data on a timer is the opposite of what a quota is for. Ask of any new path "who cleans this up", not "what is its retention".

Two paths exist. Image drop (ADR 0024): the request may not name anything, the daemon picks the directory and the name. File upload (ADR 0026): the caller names both, and pays for that with `O_EXCL` (never replaces), a fixed `0644`, and a destination and filename that must pass the *same* `SensitiveClassification` the preview uses — the platform does not write to a location, or under a name, it would refuse to show you. Neither rule generalises to the other; a third path needs its own ADR.

Editing, rename and delete of workspace files are **decided against**, not deferred (2026-08-03): they belong to the CLI and the terminal. `plan/14` designed them and was withdrawn as too large a change. Both remaining write paths only ever *add* a file, so the console cannot be used to lose work — check that property survives before adding to `POST /files`. Download is still unbuilt (`NFR-005.AC-109`).

Node execution posture (ADR 0023, accepted): a node is a disposable isolated VM. codex launches with a fixed daemon-owned flag that disables its approvals and sandbox; the node's only control is the boolean `runtime.codex.sandbox_bypass`, and no config, protocol message or console field may name a launch argument. agentd still runs non-root, and on a privileged node its system terminal reaches root through sudo. The tmux socket and options belong to the daemon. Report posture; never let the platform set it. Do not read "preserve native terminal semantics" as a reason to remove the flag.
