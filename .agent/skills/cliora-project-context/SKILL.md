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

Preserve native Claude/Codex terminal semantics, outbound daemon WSS, browser-independent sessions, allowed-root access, and explicit correlation/backpressure/timezone behavior. Do not introduce Central SSH, arbitrary shell commands, PostgreSQL terminal logs, a Web IDE, Git automation, task routing, or multi-agent orchestration without a requirements change.

Workspace write posture (ADR 0024, accepted): the workspace is **no longer read-only** — that invariant was withdrawn by product decision and an editable workspace is a stated direction. Preview stays read-only. Every write path, present or future, must satisfy four rules: confined by `workspace.Root`, bounded by per-operation size plus cumulative quota plus retention, audited per write, and refusable by the node with the refusal reported. Exactly one path exists today (image drop); a second needs its own ADR against those four rules. On that path the request may not name the file — the daemon picks the directory and the name — but that is a property of *this* path, not a general law: editing will have to let a client name a file, and will need its own protections instead.

Node execution posture (ADR 0023, accepted): a node is a disposable isolated VM. codex launches with a fixed daemon-owned flag that disables its approvals and sandbox; the node's only control is the boolean `runtime.codex.sandbox_bypass`, and no config, protocol message or console field may name a launch argument. agentd still runs non-root, and on a privileged node its system terminal reaches root through sudo. The tmux socket and options belong to the daemon. Report posture; never let the platform set it. Do not read "preserve native terminal semantics" as a reason to remove the flag.
