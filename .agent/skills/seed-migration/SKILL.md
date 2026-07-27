---
name: seed-migration
description: >-
  Manage Cliora versioned seed data for roles, permissions, and required system records through idempotent Alembic migrations. Use when adding, renaming, tightening, or removing authorization data that must reproduce after alembic upgrade head.
---

# Seed Migration

Use `cliora-project-context`; inspect models, revisions, authorization checks, and deployment flow. Define stable natural keys and upgrade/downgrade effects. Make upgrades idempotent without startup seeding. Preserve assignments when renaming or tightening permissions. Use explicit transactions and aware timestamps. Test clean, repeated, and prior-data upgrades, permission contraction, and supported downgrade. Do not mix demo data or unrelated schema work.
