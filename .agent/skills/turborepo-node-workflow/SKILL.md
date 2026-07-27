---
name: turborepo-node-workflow
description: >-
  Detect and follow the actual Node, TypeScript, Vue, package-manager, workspace, and optional Turborepo workflow in Cliora. Use when installing frontend dependencies, running scripts, changing workspace config, debugging CI, or choosing lint, typecheck, test, build, and E2E commands; never assume React, Next.js, or Turborepo.
---

# Node Workspace Workflow

Inspect `.nvmrc`, package files, lockfiles, workspace files, `turbo.json`, package scripts, TypeScript/Vite/Vitest/Playwright config, and CI. Determine Node version, package manager, topology, affected package, and scripts. Use the lockfile manager and smallest package-scoped command. Keep lockfile changes intentional. Use Turborepo only when config proves it. Run risk-appropriate existing lint, typecheck, unit, build, and E2E tasks; report commands and workspace.
