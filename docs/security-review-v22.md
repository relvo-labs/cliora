# Security review — V2.2 agent runner

- Scope: `plan/18` (`AR-04`…`AR-11`), ADR 0029 / 0030 / 0031
- Date: 2026-08-11
- Status: **complete for the code as written; two items are deployment posture and are
  named as such rather than closed**

**Five sections, not three.** `research/02/10` §6 lists three triggers for a security
review, and this phase hits all three: a new execution capability, a new storage
surface, and a new credential flow. The 2026-08-10 ruling added a fourth surface — a
directory the platform owns and fills with third-party code — so §5 exists as well.

The order below is the order a person would meet these: who may start work, what the
worker holds, what it can say, what it can leave behind, and where it all happens.

---

## 1. Claiming and "specified"

**What is new.** A card can be queued for unattended execution, and a runner on an
enrolled node claims it by polling. Two things changed about *where code runs*: any
enrolled node's runner may claim any project's card, and the code lands on whichever
machine claimed it.

**The boundary is enrollment, and that is a posture rather than a gap.** V2.2 has no
project↔agent binding. What is **not** new is that people can already see every
project: `api/http/projects.py:109` records that "every holder of `project.view` sees
every project… two teams sharing one Cliora see each other's project names — a real
disclosure, accepted deliberately" (ADR 0027). A person could already open a session on
any node's allowed root and read the code there.

**What is genuinely new is which machine the code lands on.** `project_workspaces` was
an Admin's deliberate record of "this project's code lives on these machines", and a
runner bypasses that record. V2.3's `project_agents` takes it back.

**The blast radius of a card is the machine it lands on.** Combined with §2's credential
posture, a card from project A running on a node holding write credentials for project
B can reach project B. **The premise being accepted is that a runner node should be
dedicated** — ADR 0023 already declares a node a disposable isolated VM, and enrollment
is Admin-only.

| Control | Where |
|---|---|
| Claiming is pull-side; no endpoint assigns work | `test_scope_014_dispatch_is_pull_based.py`, and an AST assertion that `services/runs.py` never reaches a node |
| A card assigned to A is **not a candidate** for B | `test_run_queue.py::test_a_card_assigned_to_one_runner_is_not_a_candidate_for_another` |
| A double claim is impossible | one `UPDATE … WHERE runner_id IS NULL`; `GATE-AR-SINGLE-CLAIM` asserts there is exactly one writer |
| The posture is stated where it is felt | ADR 0029 §3, `rbac.py`, and the Agents page — three places, deliberately |

**Residual, accepted:** any enrolled node may fetch any project's source. Recorded in
ADR 0029's Consequences and shown on the Agents page.

---

## 2. The run credential

**What is new.** A second kind of agent credential, `cliora_rt_…`, delivered once into
the run directory at 0600 and deleted the moment the run ends.

**A separate table, not a nullable column.** `session_tokens.session_id` is NOT NULL
against `terminal_sessions`, and exit condition 12 forbids a run from having a session
row. Making that column nullable would also have made `revoke_for_session`'s promise —
"revoking for a session covers every token" — false.

| Property | How |
|---|---|
| Only the HMAC is stored | same `CLIORA_TOKEN_PEPPER`, same `keyed_hash` as ADR 0008 |
| Scope is snapshotted at issue | `RUN_TOKEN_SCOPES`, written into the row |
| It can never become a `User` | `get_current_user` 401s **both** prefixes; the two paths are structurally disjoint |
| It cannot approve, create, dispatch or cancel | the scope holds two actions; `task.approve`, `task.create`, `run.dispatch`, `run.cancel`, every `file.*` and every `terminal.*` are absent |
| It is issued at the **claim**, not at dispatch | a run nobody picked up never had a credential |
| Four revocation triggers, one method | terminal state, cancel, runner disabled, directory reclaimed — all through `revoke_for_run` |
| Its lifetime cannot exceed the platform's ceiling | asserted at issue; a run that would need longer is **refused** rather than issued a token that expires mid-run |

**`run.dispatch` and `run.cancel` being unreachable is the important pair.** Without it,
one prompt-injected agent could empty the queue.

**Residual, accepted:** the credential travels inside `run.offer`, on the node's
authenticated WSS. The alternative — a second fetch the daemon would have to
authenticate separately — adds a surface rather than removing one.

---

## 3. The run log

**What is new.** The platform stores an agent's output. That is new next to V1's
promise, and ADR 0030 draws the line: **a run log is not terminal content.** It is the
CLI's JSONL event stream, one-way, batched, bounded, and expiring; the interactive
session's promise in ADR 0004 is unchanged.

| Control | Where |
|---|---|
| Bounded, truncated **from the middle**, dropped bytes stated | `CLIORA_RUN_LOG_MAX_BYTES`; `run_logs.truncated` plus `task_runs.log_truncated_bytes` |
| Retention: 3 days success, 14 days failure | `task_runs.logs_expire_at`, swept per run rather than per row |
| A redaction hook exists even with nothing to redact | the daemon's sink is the single path every line passes through |
| It cannot starve the interactive terminal | 32 KiB chunks, not in `LARGE_FRAME_TYPES`, aggregated 64 KiB / 2 s before a database write |

**Residual, accepted and written into the ADR:** a Central crash loses each in-flight
run's last unflushed ≤64 KiB. The log is a diagnostic — re-running produces another —
and the two things that are *not* diagnostics deliberately avoid this path: artifacts
go over HTTP and land one at a time, messages commit per message.

**Residual, not closed:** the log may contain whatever the agent printed, including a
secret it read. Runner-side redaction has a hook and no rules, because this phase
manages no secrets.

---

## 4. Receiving and serving artifacts

**What is new.** Untrusted bytes, uploaded by an agent, stored by the platform, and
served back to a browser. This is the phase's stored-XSS surface.

| Control | Where |
|---|---|
| `content_type` is **determined by the server** | extension **and** magic bytes; anything unrecognised is `application/octet-stream` |
| Download is always a download | `Content-Type: application/octet-stream` even for `image/png`, `Content-Disposition: attachment`, `nosniff`, `CSP default-src 'none'; sandbox` |
| The filename cannot inject a header | RFC 5987 percent-encoding, so `"` and CRLF are unrepresentable rather than filtered |
| Preview is an allowlist of three | images, plain text, and markdown **served as `text/plain`** |
| `text/html` is never previewable | and never will be: single origin means "open in a new tab" is "render inline" (ADR 0020) |
| **No path in the application origin renders one** | two machine assertions: the OpenAPI scan (no response declares HTML; `/api/artifacts/{id}` is GET+DELETE only) and the frontend route-table diff against the pre-phase baseline |
| Artifacts are immutable | no update route exists anywhere; the OpenAPI assertion pins it |
| Deletion needs `project.manage`, a reason, and an audit row | metadata soft-deleted, **bytes hard-deleted** so a quota can actually be freed |
| Three quota layers, none silent | 413 with the layer named; the CLI turns each into a sentence and a non-zero exit code |

**Residual, accepted:** the quota check precedes the write, so two concurrent uploads
can both pass and exceed the project quota by one file. A quota is an operational guard
rail, not a security boundary, and a project-wide lock would make two runs wait on each
other.

**Residual, stated in the UI:** an artifact is **not guaranteed free of secrets**.
Redaction applies to the log's text stream and nothing else.

---

## 5. The run directory, quotas, and git

**What is new.** A directory the platform owns and fills with a third party's
repository, on a machine that may also serve interactive sessions.

**The honest part first.** An earlier draft of this design claimed "the run process
cannot read or write any allowed root". **Nothing implements that**, so the claim was
withdrawn rather than restated. The child runs as the same OS user as agentd, the
allowed roots must be readable by that user or sessions cannot start, and the unit
deliberately does not hide the home directory.

**Three smaller guarantees that are real:**

1. No platform path writes into an allowed root — the run directory is created outside
   them, the context pack is written straight into it, `daemon/internal/files/` has a
   zero diff (`GATE-AR-TOUCH-LIST`).
2. The existing file APIs cannot reach the run directory: it is outside every allowed
   root, so `filesystem.list` answers `WORKSPACE_OUTSIDE_ALLOWED_ROOT`.
3. `git status --porcelain` in the user's workspace stays empty for the whole run —
   which proves **the platform did not touch it**, not that the agent could not.

**The remainder is deployment posture, and it is reported rather than promised.**
`dedicated` (`len(allowed_roots) == 0`) is the one condition the platform can check, and
the Agents page says in words what a mixed-use node means: *an agent running here can
read those directories.*

| Control | Where |
|---|---|
| The run root may not overlap an allowed root, **in either direction** | checked at startup; the daemon **refuses runner mode** and names the offending root |
| That refusal does not take the node's terminals away | interactive sessions are unaffected; the node reports `agent_runner: false` |
| Two quota layers plus a free-space floor | over the node total, the runner **stops polling** and says why rather than appearing offline |
| Directories are reclaimed, failures kept far longer | 3 days / 14 days; an unfinished directory is never reclaimed |
| The run credential file is deleted at the end of the run | not at the retention deadline |
| git argv is a closed table | `internal/gitfetch`; no element comes from a payload, a card field, or the agent |
| A credential cannot be expressed in a repository URL | stored as three columns; the wire pattern accepts only a literal `git@` on ssh, so a **password** is unrepresentable in all three languages |
| Missing credentials fail in seconds | `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=/bin/false`, ssh `BatchMode=yes` — **on the daemon's own calls only** |
| Cancellation leaves no residue | three phases against the whole process group; asserted by scanning `/proc` for surviving members |

**Residual, chosen:** **the agent may use the machine's existing git credentials for
anything git can do, including push.** This is deliberate (2026-08-10, second ruling),
not a gap. It follows D25 — constrain how output leaves, not what happens inside the
sandbox — and its convergence points are red line 5 (a branch nobody merges affects
nobody), the node's posture, and observability: every run reports `git remote -v` with
userinfo masked, and its unpushed commit count.

**Residual, accepted:** no mount namespace. It needs unprivileged user namespaces (a
node kernel setting), it would hide `~/.claude`, `~/.codex`, `~/.gitconfig` and `~/.ssh`
which the runtimes need, and "use it if present" is a half-guarantee reported as a whole
one. `codex exec -s workspace-write` gives a real landlock sandbox scoped to the run
directory on that one path — **which the runtime gives, not the platform**.

---

## Open items for the operator

1. **A runner node should be dedicated.** Whatever that machine can reach, an agent
   running on it can reach. The console shows ⚠ when it is not.
2. **`CLIORA_GIT_ALLOWED_HOSTS` is empty by default**, and an empty list allows nothing.
   That is the right default for a deployment that has not decided yet.
3. **Token spend is measured, not capped** (M-AR-10). This is the phase's one knowingly
   unmitigated risk, and it is in the release note rather than only in a measurement
   list: `claude --max-budget-usd` exists and codex has no equivalent, and wiring half
   of it would suggest a protection that only one path has.
