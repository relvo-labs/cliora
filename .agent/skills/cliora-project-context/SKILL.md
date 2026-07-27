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

Preserve native Claude/Codex terminal semantics, outbound daemon WSS, browser-independent sessions, allowed-root read-only MVP access, and explicit correlation/backpressure/timezone behavior. Do not introduce Central SSH, arbitrary shell commands, PostgreSQL terminal logs, a Web IDE, Git automation, task routing, or multi-agent orchestration without a requirements change.
