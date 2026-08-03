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

Preserve native Claude/Codex terminal semantics, outbound daemon WSS, browser-independent sessions, allowed-root access, and explicit correlation/backpressure/timezone behavior. Do not introduce Central SSH, arbitrary shell commands, PostgreSQL terminal logs, a Web IDE, Git automation, task routing, or multi-agent orchestration without a requirements change. The console reads and adds files; it does not edit, move or remove them.

Workspace write posture (ADR 0024 + ADR 0026, accepted): the workspace is **no longer read-only**; preview stays read-only. Every write path must satisfy four rules: confined by `workspace.Root`, bounded, audited per write, and refusable by the node with the refusal reported. "Bounded" means per-operation size plus cumulative quota plus — for a **platform-owned** destination — a retention period; where the **user** chooses the destination, retention is replaced by **visibility**, because deleting the user's data on a timer is the opposite of what a quota is for. Ask of any new path "who cleans this up", not "what is its retention".

Two paths exist. Image drop (ADR 0024): the request may not name anything, the daemon picks the directory and the name. File upload (ADR 0026): the caller names both, and pays for that with `O_EXCL` (never replaces), a fixed `0644`, and a destination and filename that must pass the *same* `SensitiveClassification` the preview uses — the platform does not write to a location, or under a name, it would refuse to show you. Neither rule generalises to the other; a third path needs its own ADR.

Editing, rename and delete of workspace files are **decided against**, not deferred (2026-08-03): they belong to the CLI and the terminal. `plan/14` designed them and was withdrawn as too large a change. Both remaining write paths only ever *add* a file, so the console cannot be used to lose work — check that property survives before adding to `POST /files`. Download is still unbuilt (`NFR-005.AC-109`).

Node execution posture (ADR 0023, accepted): a node is a disposable isolated VM. codex launches with a fixed daemon-owned flag that disables its approvals and sandbox; the node's only control is the boolean `runtime.codex.sandbox_bypass`, and no config, protocol message or console field may name a launch argument. agentd still runs non-root, and on a privileged node its system terminal reaches root through sudo. The tmux socket and options belong to the daemon. Report posture; never let the platform set it. Do not read "preserve native terminal semantics" as a reason to remove the flag.
