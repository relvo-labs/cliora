# Release note — the V2.0 project layer

**Off by default. Upgrading changes nothing until you switch it on.**

With `CLIORA_PROJECTS_ENABLED` unset or `false`, this release behaves exactly as the
one before it: the project endpoints answer 404, the navigation rail is unchanged
for every role, and no existing API field moved. That claim is checked rather than
asserted — see *How we know* below.

---

## Read this first: `project.view` is held by every role

The one thing in this release that changes what people can see.

Turning the layer on gives **Viewer, Developer and Admin** a new read: the list of
projects, each project's description, and the **names and absolute workspace paths**
of the directories bound to it, on every node.

None of that is a new *category* of information — a Viewer already sees node names
(`node.view`) and session workspace paths (`session.view`). What is new is the
**aggregation**: one page that collects, per project, which machines and which
directories are involved. Aggregation is sometimes disclosure even when each part
was already visible, so it is worth deciding about rather than discovering.

There is no per-project membership in this release. Every holder of `project.view`
sees every project, exactly as `node.view` already works. If two teams share one
Cliora, they will see each other's project names, descriptions and bound paths.
Project-level membership is designed but not built (ADR 0027, *Consequences*).

**What is *not* newly visible:** who did what. The project timeline shows the
action and the instant to everyone, but the actor's name only to holders of
`audit.view` — the same rule the Dashboard's recent activity already follows.

---

## What you get

| | |
|---|---|
| **Projects** | Create, rename, pause, archive. No delete — archiving refuses new sessions and new bindings while leaving everything already running untouched |
| **Workspace bindings** | One project can span directories on several nodes. A binding is re-authorized on every use, so a directory whose allowed root is later withdrawn shows as unusable instead of failing at session start |
| **Sessions** | A session may name a project. **Optional, and permanently so** — a session belonging to no project is an *ad-hoc* session, which stays a first-class part of the product |
| **Activity timeline** | What happened on this project: created, renamed, bound, unbound, sessions started and ended |
| **Navigation** | Three groups — Projects, Sessions, Infrastructure. **Every existing URL is unchanged**; bookmarks still work |

## What it does not do

Tasks, boards, agents, secrets and delivery are later phases. This release adds no
protocol message, does not change `agentd` (still 0.7.0), and reads or writes no
file on any node.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLIORA_PROJECTS_ENABLED` | `false` | The whole project layer. Off means the endpoints answer 404 and the rail is unchanged |

Two migrations: `0021` (three tables plus one nullable column on
`terminal_sessions`) and `0022` (the two new actions). Both are reversible, and
`alembic downgrade 0020_node_file_upload` restores the previous schema exactly.

Two new RBAC actions, seeded by `0022`:

| Action | Viewer | Developer | Admin |
|---|:--:|:--:|:--:|
| `project.view` | ✓ | ✓ | ✓ |
| `project.manage` | — | — | ✓ |

`project.manage` sits with enrollment and node management: deciding which projects
exist, and which machines and directories they cover, is an organisation-level call.
A Developer cannot create a project, so the empty state tells them to ask an Admin.

Five new audit actions: `project.create`, `project.update`, `project.archive`,
`project.workspace_bind`, `project.workspace_unbind`. Archiving is separate from
updating because "who archived that project" is a question asked on its own.

---

## How we know the flag-off promise holds

Captured before any code changed, and compared afterwards:

| Claim | Instrument |
|---|---|
| No existing API field moved | `scripts/pj/openapi_diff.py` — only new paths and **optional** new fields pass. Result: 5 paths, 8 schemas, 4 optional fields, **0 refused** |
| No existing table changed | `scripts/pj/schema_snapshot.py --diff` — column by column, including defaults and `ON DELETE` behaviour |
| The migration is reversible | `scripts/pj/gate-migration-roundtrip.sh` — downgrade must land on the baseline exactly |
| The rail is unchanged | `scripts/pj/nav-shot.mjs` — per-role screenshots **and** a structural dump. Pixel-identical for all three roles |
| Nothing in the risk surface was touched | `scripts/pj/gate-no-wire.sh` — no diff under `daemon/`, `contracts/`, `backend/app/api/ws/`, the file/terminal/tunnel services, or `deploy/` |
| The flag is exercised both ways | `.github/workflows/v2-projects.yml` runs check, DB, daemon integration and the complete live-stack Chromium suite once with the layer on and once off |
| Project detail remains bounded | `scripts/pj/measure-project-detail.py` — 50 bindings, 30 samples, p95 53.917ms against a 200ms budget |

`scripts/pj/evidence.sh` runs all of it; `scripts/pj/browser-evidence.sh` runs the
checks that need a live stack, including the complete flag-on and flag-off browser suites.

## Known limitations

- **A binding cannot tell you the directory was deleted.** It reports "machine
  offline" and "this machine no longer allows this directory", because both are
  answerable from data Central already holds. Whether the path still *exists* needs
  a round trip to the node, and this release adds no protocol message — so a deleted
  directory surfaces when the session is created, exactly as for a path typed by
  hand.
- **A session's project is matched exactly, not by prefix.** To work in a
  subdirectory of a bound path, bind the subdirectory.
- **No per-project membership** (see above).
