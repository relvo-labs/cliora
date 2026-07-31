# plan/08 report — Workspace tabs and the system terminal

Date: 2026-07-31 · Plan: `plan/08/` · ADR: [0021](./adr/0021-system-terminal-and-shell-runtime.md)
· Security review: [security-review-p8.md](./security-review-p8.md)

## Verdict

**Go for the layout work (WT-01 – WT-03), conditional Go for the system terminal
(WT-04 – WT-11).** The condition is no longer "nothing here has met a real node" —
that gap is closed for the happy path: a TERMINAL tab now opens a real `bash` on a
real node in the browser E2E suite, runs a command, and reads the output back
through the relay, on Chromium and Firefox. What remains is deployment, not
verification: the three items in [Before this reaches production](#before-this-reaches-production),
of which the two documents are now written and the third is a check on your fleet.

## What shipped

### Layout (no new data-plane surface)

| | |
|---|---|
| WT-01 | Left `Sessions` rail removed — it had been placeholder text with no list since the first frontend commit, while occupying 200 px. Grid is now `1fr 300px`. Seven specification documents updated, including the two that recorded P2-12 as complete without disclosing the placeholder |
| WT-02 | `mount()` can re-mount. It previously returned early on an existing terminal and was called once from `onMounted`, so any render that replaced the host left xterm writing into a detached node — reachable today by *failed load → Retry*. The terminal is now moved, not rebuilt, so scrollback and the socket survive. Hidden hosts (0×0) are no longer measured, and a rows/cols under 2 is never sent |
| WT-03 | Centre pane is a tablist: `CLI` and at most one `[filename]`. The 45 % split is gone. The CLI panel is hidden, never unmounted |

### System terminal

| | |
|---|---|
| WT-04 | ADR 0021; `SCOPE-011` narrowed in the PRD (both anchors preserved); `FR-SHELL-001` added with eight criteria |
| WT-05 | Contract **v1.5.0** — `runtime` gains `shell` in two schemas. No payload field was added anywhere. Seven allowlist sites synchronised; `terminal.shell` action; migrations `0012` (seed) and `0013` (parent column + partial unique index) |
| WT-06 | Daemon `shell` runtime. No new runtime type was needed: the existing `--version`-probing adapter fits `bash`. `applyRuntimeDefaults()` enables it when the config is silent and never overrides an explicit `enabled: false` |
| WT-07 | `POST /api/sessions/{id}/shell`; four authz predicates narrowed for shells; parent binding with two cascade paths; idle reaper; list filtering; `runtime` in the audit metadata |
| WT-08 | `TERMINAL` tab — lazily created, closed means terminated, three error codes with their own copy, and a standing notice that this pane is outside the workspace boundary |
| WT-09 | `FR-SHELL-001` registered: 8 criteria × 4 primary links, all `verifiable`. `SCOPE-011.AC-01` is `deprecated` with a `supersedes` link and a recorded rationale |
| WT-10 | Twelve-row attack table, three findings |
| WT-11 | `scripts/wt/evidence.sh`, `.github/workflows/wt.yml`, this report |

## Evidence

`scripts/wt/evidence.sh` — 13 gates executed, all exit 0; 1 skipped and named.

```
backend format / lint / typecheck / unit (594)   frontend lint / typecheck / unit (330)
contract, 3 languages                            daemon go test -race
migrations up → down → up                        backend db suite (253)
browser e2e, chromium + firefox (30)             incl. the system terminal on a real node
make traceability: 379 criteria, 248 verifiable, 0 blocking
```

The browser leg is no longer conditional on someone else standing up a stack:
`E2E_STACK_DATABASE_URL=<spare database>` makes the pack start Central, a node and
the Fake CLI itself (`scripts/e2e/run-stack.sh`), which is why the two skips this
pack used to carry are down to one.

Skipped, with the reason recorded rather than the gate omitted: **WebKit**, whose
system libraries need root to install. It is probed before the suite rather than
allowed to fail it, so an unavailable browser lands in `skipped.txt` instead of
turning the gate red — and it is the engine that has historically differed on
WebSocket behaviour, so CI must run it.

## What this phase found

**1. A green scope guard hid a scope change.** `SCOPE-011` ("使用者不得從前端執行任意
Shell Command", criticality `must`) is verified by a test asserting that
`session.start` carries no command field. Adding a `shell` runtime leaves it green:
CI, coverage and the release gate all stay quiet while a recorded product non-goal is
overturned. This is a limit of what an automated guard can express about scope, and it
is why WT-04 was made a blocking gate that produces a document rather than code.

**2. Two tickets that looked separable were not.** `test_every_action_is_enforced_somewhere`
fails the moment an action exists with no enforcement, so WT-05 (define
`terminal.shell`) cannot merge without WT-07 (enforce it). The plan had them as
independent tickets. The test is right and the plan was wrong.

**3. A hand-written row in a generated file.** The plan called for adding
`SHELL_ALREADY_OPEN` to `docs/error-catalog.md`. That file is generated from
`error_catalog.py`, and `test_the_published_catalog_is_current` caught it. The
frontend has a matching catalogue with a bidirectional consistency test, which caught
the second half.

**4. An index narrower than the states it was meant to cover.** The plan specified the
partial unique index over three live statuses; `ACTIVE_STATES` has four. The missing
one is `terminating` — precisely the window in which a double-click would have created
a second live shell.

**5. Two Go tests asserted "exactly two runtimes".** Not anticipated by the plan.
Updated to three, with the reason a disabled runtime is still reported.

**6. The browser E2E suite had been red for some time, and nobody could see it.**
Standing the stack up locally for the first time found `session.spec.ts` failing
before its first assertion: `signIn()` expected login to land on `/nodes`, but the
landing page became `/dashboard` when the dashboard shipped in P4-08. `files.spec.ts`
and `nodes.spec.ts` carried the same stale expectation. Two more breakages were
this phase's own: the shell's xterm instance is mounted from page load, so every
unscoped `.xterm-rows` locator now matches two elements, and `expect(tabs)
.toHaveCount(1)` is wrong the moment a TERMINAL tab exists — count-based tab
assertions are now label-based. **The common cause is not any of these bugs.** It is
that a gate whose skip is unconditional records the same green either way, so the
suite rotted at the speed of the app. The pack can now stand the stack up itself,
which is what makes the leg cheap enough to actually run.

## Deliberate gaps

- **Shell commands are not recorded.** ADR 0004 and `TECH-SEC-08` forbid terminal
  bytes in the database or logs, and the first thing such a log would capture is a
  password typed at a prompt. The audit trail says a shell existed, not what ran in it.
- **An unattended shell can live for up to 15 minutes** (`shell_idle_terminate_seconds`,
  default 900) after a browser crash. Traded against reload and suspend churn; revisit
  with real usage data.
- **Permissive defaults.** `terminal.shell` is held by Developer, and the runtime is
  enabled by default including on nodes that upgrade into it. Both were decided
  explicitly on 2026-07-31. The consequence is that the boundary rests entirely on
  ownership, the non-root daemon, bounded lifetime and audit — see the security review.

## Before this reaches production

All three are now checklist items with somewhere to look, rather than paragraphs in
a report: `docs/release-checklist.md` §4.5.

1. **Confirm the daemon does not run as root.** This is no longer a best practice: the
   shell escalates nothing, so the daemon's execution identity is the ceiling of the
   feature. Deployment blocker (`plan/08/00-execution-plan.md` §8). Code cannot check
   it for you — `agentd` refuses to start as root and the shipped unit sets `User=`,
   but a hand-edited unit or a container running the binary directly gets there.
2. **Send `docs/release-note-system-terminal.md` before upgrading existing nodes.**
   They gain remote shell on upgrade, because an absent `runtime.shell` block means
   enabled. That is a capability change and must not be silent. Operational detail
   lives in `docs/runbooks/system-terminal.md`.
3. **Run the CI legs.** Chromium and Firefox now pass locally, including the real-node
   shell path. **WebKit has still never executed** — it needs root to install its
   system libraries, and it is the engine that has historically differed on WebSocket
   behaviour, so a green Chromium is not the claim the PRD makes.
