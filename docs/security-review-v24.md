# Security review — V2.4 delivery, verification and the Done Gate

- Date: 2026-08-14
- Scope: `plan/21` (`DV-00`…`DV-11`), ADR 0033, amendments to ADR 0029/0031/0032
- Triggers (`research/02/10` §6): **a new outward side effect**, **the first use of a
  stored credential flow**, and **a new ability to execute processes on a node**. Three
  triggers, three sections, and they are deliberately not merged into one — the failure
  modes have nothing in common, and a single section would let the weakest analysis set
  the tone for all three.

Verification state at the time of writing: `make check` green (1648 backend, 649
frontend, 213/192 contract), `scripts/dv/gates.sh` **13/13**, `go test ./...` 17
packages including `-race`.

---

## §1 — The outward side effect: Central calls somebody else's API

### What is new

Until this phase Central spoke to nodes over an authenticated WebSocket and to nothing
else. It now makes an outbound HTTPS request to a provider's public API and, on success,
**leaves a pull request on a repository the platform does not own**, under an identity
that is not the person who dispatched the card.

### Assets and boundaries

| Asset | Where it lives | Who can reach it |
|---|---|---|
| `provider_token` | `project_secrets`, envelope-encrypted | Central's pull-request worker only. **Never delivered to a node** — it is in `UNDELIVERABLE_KINDS`, and ADR 0032 amendment A1 records that as permanent rather than pending |
| The outbound socket | `services/providers.py` | One module. `staticGuards`' successor — the narrowed SCOPE-013 — asserts no other module in `app/` imports an HTTP client |
| The repository being written to | somebody else's account | Reached only through `owner/repo` taken from `ProjectRepository.path`, never from parsing a URL |

### Findings and their resolutions

**F1. The scope guard SCOPE-013 forbade this outright, and was narrowed.**
That guard existed to stop Central becoming a reverse proxy to a node's HTTP service
(ADR 0022), and it was enforced as "no HTTP client anywhere in `app/`" — a good proxy
for the rule until this phase, and not the same statement as it.

The narrowing is **stricter than a carve-out**: an HTTP client may be imported by
exactly one module; that module must consult the deployment's host allowlist before
every request; and it may not interpolate any repository column into a URL. Three
assertions in `test_scope_guards.py` enforce all three. Widening the allowlist to a
node's address would still be proxying — which is why the allowlist lives in settings,
defaults to a single public host, and is not reachable from data.

**F2. SSRF is closed by construction rather than by validation.** The API base is a
deployment setting (`CLIORA_PROVIDER_API_BASE` / `provider_api_hosts`). No repository
row, card field or request body can influence where Central connects; a repository
supplies `owner/repo` and nothing else. `test_a_host_outside_the_allowlist_is_refused`
asserts the refusal happens **before** the request, not by inspecting a response.

**F3. A timeout is not retried, and that is the security-relevant choice.**
Retrying a timed-out creation is the HTTP convention and would open a second pull
request on somebody's repository, because creation is not idempotent and a timeout may
mean the request arrived while the reply did not.
`test_a_timeout_sends_exactly_one_request` counts requests rather than checking a flag —
a retry added later would still pass a flag assertion written today.

**F4. The credential does not reach a log, an error, or an audit row.**
The highest-risk surface is not a log line but the **provider's own error body**, which
is the string a person pastes into a ticket. `_safe_detail` masks the token there;
`test_the_token_never_appears_in_an_error` runs a provider that reflects the header back
and asserts the token is absent from the raised message and from every `caplog` record.
The `pr.create` audit row carries repository, number, head and base — **not the token,
and not its length**, asserted in `test_a_created_pull_request_is_recorded_and_audited`.

**F5. Red line 5 is verified by absence.** The adapter has three actions: create a pull
request, find one, comment on one. `GATE-DV-PROVIDER-VERBS` asserts that `merge`,
`approve`, `review`, `close`, `delete`, `release` and `tag` do not appear in the module
at all — as method names, as URL fragments, or as strings. A check can be bypassed by a
second call site; a table that does not contain the word cannot.

**F6. The backlog is bounded and visible.** `provider_pending_limit` (50) stops the
worker taking new work, and it logs rather than silently accumulating. Without it, a
provider outage becomes fifty pull requests the moment it recovers.

**F7. A traceability question V2.3 never had to answer.** The pull request's author is
the token's owner, not the dispatcher. Three things carry the link: the last line of the
PR body says so in words, the `pr.create` audit row records the run, and the run page
links the card. This is a disclosure rather than a control — accepted, and recorded in
ADR 0033 §Consequences.

### Residual risk accepted

A card with a wrong `target_branch` opens a correctly-authorised pull request against
the wrong branch. The platform guarantees the repository and the namespace; the target
is the card author's, and a person reviews the result.

---

## §2 — The new execution capability: verification commands

### What is new

The daemon now runs commands that are **not** the agent's runtime, inside the run
directory, and reports their real exit codes.

### The five questions, answered

**Q1. What bounds the capability?**
The run's own directory; argv arrays from two platform-side stores; **no shell**; a
per-command timeout (300 s) and a group timeout (900 s); and the group is skipped, with
an explanation, when too little of the run's wall clock remains. There is no API that
executes a command on a node — no request field names one, and the absence is
assertable rather than promised.

**Q2. Was SEC-002 amended again?**
**No.** The revised invariant from ADR 0032 §1 — *no request payload may name a command
or carry a secret's value* — holds word for word. Both stores are columns in Central's
database, written by an authorised request and read back by Central when it assembles an
offer. That is structurally identical to the argument ADR 0032 made for `spec.secrets`,
and ADR 0032 amendment A4 records that nothing needed permitting.

**Q3. Who can change what runs?**
Two stores, two actions, **neither of them an agent's**:

| store | action | reachable by a run token |
|---|---|---|
| `projects.verification_commands` | `project.manage` | no |
| `tasks.verification_commands` | **`task.approve`** | **no** |

`RUN_TOKEN_SCOPES` is `{project.view, task.update}`, and `services/agent_auth.py`
records that `task.approve` is the half a run credential can never hold. The card store
is deliberately **not** in `EDITABLE_FIELDS` and has its own endpoint — through the card
patch it would have been writable with `task.update`, which a run token *does* hold, and
the agent being verified would choose what verifies it. `test_authz`'s route matrix pins
both actions.

**Q4. Can a command's output leak a secret?**
It could, and does not. `output_tail` passes through the redactor because the redactor
wraps `send` rather than the log sink (V2.3's decision, first benefiting here).

⚠️ **This was a real defect during implementation, not a theoretical one.** `RunChecks`
returns `[]CheckResult`, and `Redactor.value()` recurses through maps and `[]any` while
returning anything else untouched — so the typed slice travelled **past a redactor that
was working correctly**. `CheckPayload()` now converts to the shape the redactor
understands, and `TestACheckOutputPassesThroughTheRedactor` fails without it. The
general lesson is recorded in `plan/21/09` §3 item 10: "wrapping `send` covers new
fields automatically" holds only for shapes the walker recognises.

**Q5. Can `machine_verified` be forged?**
One writer (`VerificationService.record_machine_verified`), reachable only from
`RunService.finish()`, which requires a valid node credential **and** a run belonging to
that node (`_run_for_node`). Two assertions guard it:
`GATE-DV-MACHINE-VERIFIED-ONE-WRITER` and a test that scans for a second caller.
Everything submitted over HTTP is `agent_reported` regardless of what the payload
claims, and a claimed level is **recorded as discarded** — without that record, an agent
overstating its evidence and an agent with a typo leave identical traces.

### Residual risk accepted

**Two cards in one project may assert completion against different standards.** That is
the flexibility the 2026-08-14 ruling bought, and it is converged rather than forbidden:
`origin` is visible in four places, `require_project_verification` can require a
project-level check, and a metric reports the card-declared share. **This is accepted
explicitly rather than passed over** — it is the one risk this phase added after the
plan was written.

---

## §3 — The completion judgement: its bypass and its integrity

### What is new

A card entering `done` is now checked, and there is one authorised way around the check.

### The four questions, answered

**Q1. How many entrances does the gate have?**
One. `TaskService.update()` is the only writer of `task.stage`, and
`GATE-DV-SINGLE-DONE-PATH` plus a test assert that `services/runs.py` never advances a
card into `done`.

⚠️ The invariant is narrower than "a run never assigns `stage`": V2.2 legitimately moves
a card to `blocked` when attempts are exhausted, and that is a report rather than a
completion claim. A guard written too strictly gets relaxed on first reading, and
relaxing usually means deleting.

**Q2. Who may bypass it?**
`task.force_done` only — a new Admin-only action, deliberately not a reuse of
`task.approve`. A run credential cannot: it does not travel the user authentication path
at all, the field is refused explicitly on the agent route, and the CLI has no such verb
(asserted against command declarations, not against the substring, so the comment
explaining the absence is allowed to exist).

**Q3. What does a bypass leave behind?**
Three things, none removable by an API: the reason on the card
(`force_done_{reason,by,at}`), a `task.forced_done` timeline row, and an audit row. The
console renders the card mark permanently and outside any disclosure. The only way to
clear it is to take the card out of `done` and through the gate.

**Q4. Can configurability reach the gate?**
No. `process_overrides` disables readiness items and review gates and adjusts WIP; the
six conditions are constants in `services/done_gate.py` and are absent from
`process_definitions`. `test_overrides_cannot_reach_the_done_gate` asserts both that the
condition keys never appear in the process document and that a card still needs its
evidence after every gate is disabled.

> This is the most important answer in §3. If the gate were configurable, the first
> person who found it inconvenient would switch it off — and switching it off leaves no
> trace, while `--force` leaves three and is counted.

### Two integrity properties

**Append-only, enforced where it can be checked.** The three tables have no update path
and `GATE-DV-APPEND-ONLY` scans for one. A database trigger was considered and rejected:
it fires on the statement, so the first legitimate correction becomes an unreadable
error, and somebody drops the trigger rather than reading it.

**`kind` decides `source`.** A single mapping binds them, so an agent-written machine
fact is *unrepresentable* rather than merely refused — a level stronger than checking
the writer's identity, because a check has a second call site and a mapping does not.

### Residual risk accepted

The gate is bound to `CLIORA_AGENT_RUNS_ENABLED` and skipped for cards that were never
dispatched. Both are necessary — every condition asks for evidence the runner layer
produces — and both mean a hand-managed card reaches `done` on a person's judgement, as
it did before this phase. What changed is that a card which *was* run is now checked.

---

## Verification summary

| Property | How it is asserted |
|---|---|
| No merge / approve / close / tag, anywhere | `GATE-DV-PROVIDER-VERBS`, `GATE-DV-PUSH-CONSTRAINTS`, `test_the_verb_table_is_closed` |
| No HTTP in the node receive loop | `GATE-DV-NO-HTTP-IN-LOOP` + `test_nothing_in_the_receive_loop_reaches_a_provider` |
| One entrance to `done` | `GATE-DV-SINGLE-DONE-PATH` + `test_a_run_never_advances_a_card_into_done` |
| One writer of `machine_verified` | `GATE-DV-MACHINE-VERIFIED-ONE-WRITER` + `test_machine_verified_has_exactly_one_writer` |
| No shell for a verification command | `GATE-DV-NO-SHELL` (production code only) |
| A command's output is redacted | `TestACheckOutputPassesThroughTheRedactor` |
| The token is absent from errors, logs and audit | `test_the_token_never_appears_in_an_error`, `test_a_created_pull_request_is_recorded_and_audited` |
| A timeout creates exactly one request | `test_a_timeout_sends_exactly_one_request` |
| Card-declared checks need `task.approve` | route matrix + `test_authz` |
| Append-only holds | `GATE-DV-APPEND-ONLY` + `test_the_three_tables_have_no_third_verb` |

## Outstanding before release

1. **The first real pull request on `Lei-k/Traqora`** (exit condition 3). Every provider
   path so far has been exercised against a fake; failure shapes only the real
   counterparty produces have not been seen.
2. **ADR 0033 acceptance** — gate two, a person's approval. It remains `proposed`.
3. **The provider token's custody**: a fine-grained PAT with `pull request: write` and
   nothing more, and a written record of whose identity will appear on every pull
   request the platform opens.
