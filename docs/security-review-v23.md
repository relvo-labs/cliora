# Security review — V2.3: project secrets, tag dispatch and the platform's first remote write

- Date: 2026-08-13
- Scope: `plan/20`, ADR 0032, the ADR 0031 and ADR 0029 amendments.
- Triggers hit (`research/02/10` §6): **a secret flow**, **a new storage surface**, and
  **a git write**. Three of the four, so this review is mandatory and is written as
  three independent sections rather than one essay about "agent execution security".

**Read §2 first if you read only one.** §1 and §3 describe mechanisms; §2 describes a
boundary the platform has decided not to draw, and everything in the other two sections
is bounded by it.

---

## §1 — The storage and delivery of a secret

### What is stored

`project_secrets`, one row per secret, envelope-encrypted: the value under a per-row
data key, the data key under the master key, four ciphertext/nonce columns plus
`key_version`. AAD is `cliora-project-secret-v1`, distinct from the tunnel credential's,
so the two kinds cannot be decrypted in each other's context.

**Not stored**: any plaintext column, a fingerprint, or a length.
`GATE-SC-NO-PLAINTEXT-COLUMN` asserts the first. The other two are omissions with
reasons: a length is a side channel (a 93-character value is almost certainly a
fine-grained PAT), and a fingerprint answers "is this the one I rotated last week",
which `rotated_at` answers without disclosing anything.

### What can read it back

**Nothing.** Asserted twice, and the two catch different mistakes:

| Assertion | Catches |
|---|---|
| `GATE-SC-NO-SECRET-IN-RESPONSE` — every schema reachable from a **response** in the whole OpenAPI document | A *future* endpoint that hands back a whole row |
| `test_no_endpoint_returns_a_value` — a sentinel value asserted absent from the raw bytes of five real responses | A present endpoint whose schema is right and whose implementation serialises a model |

The scan is deliberately restricted to responses. Its first version walked every schema
and failed on `CreateProjectSecretRequest`, which of course carries a value — that is
the request that stores one. **A guard that cannot tell a request from a response would
most cheaply be "fixed" by renaming the field somebody has to type**, which is worse
than having no guard.

`GATE-SC-SINGLE-DECRYPT` asserts that exactly one module (`services/secrets.py`) can
turn a stored secret back into plaintext.

### The path a value takes

`RunService.poll()` → `SecretService.materialise()` → `RunOffer.spec()` → the
`run.offer` frame. Not one step accepts caller input: `poll` answers a node's own poll,
`materialise` takes a project id and names read from the card, and those names were
checked against the project's allowlist when they were written.

**Decryption happens at the claim**, inside the node WebSocket receive loop. It is
CPU-bound with no `await` on a node round trip, which is what makes it safe there.
The audit row and `last_used_at` are written **in the same flush** — separating them
would leave a window in which a machine holds a secret and nothing says so.

**A runner that declines afterwards has still received them**, and the audit says so
rather than being retracted. That is the honest record and an accepted cost of claiming
at poll rather than at accept.

### Where a value goes on the node

`kind` decides, and the split is the substance of this section:

| kind | destination | default |
|---|---|---|
| `env` | The CLI child's environment | on |
| `git_pat`, `git_ssh_key` | **The daemon's own git environment only** | **off** (§3b) |
| `provider_token` | Nowhere. Unrepresentable on the wire | — |

Putting a git credential in the child's environment would hand the agent the platform's
revocable credential, and it could push it anywhere — where **none of the five hard
constraints reach**, because those are compiled into the daemon's own push path.
`TestKindDecidesWhereAValueGoes` asserts the split; `GATE-SC-NO-SECRET-TO-DISK` asserts
no value reaches a file.

The one apparent exception on disk is `ssh-agent`'s socket, and **a socket is not a
key**: the key arrives on `ssh-add -`'s stdin and the socket dies with the run. The
`run.token` file is excluded from that gate **by name**, with its reason recorded: the
`cliora` CLI is a separate process and must read its credential from somewhere. A
project secret has no such need, so nothing else may take that route.

### Redaction, and what it does not do

The redactor wraps the outbound `send` closure, not the log sink — `run.failed` carries
git's stderr and `run.complete` carries free text, so **the credential-shaped path out
of a run is an error message, not a log line**. Values are sorted longest-first so a
secret that is a prefix of another is not cut into `***<tail>`; values shorter than
eight characters are skipped with a warning, because a secret whose value is `1` would
destroy the log and protect nothing.

> ⚠️ **It is best effort and the ADR says so.** Values are matched literally, so a
> base64- or URL-encoded one gets through. The second line of defence is not a cleverer
> matcher — it is that secrets are revocable and logs expire.

### The master key, and its three costs

Stated rather than implied (ADR 0032 §3):

1. **The key and the ciphertext share one trust boundary.** Whoever can read the
   environment can usually read the database. Protection against "the backup leaked"
   rests on the attacker not having the environment, not on two independent defences.
2. **There is no decryption audit.** Nobody knows who decrypted what, and when.
3. **Losing the key loses every secret**, irrecoverably.

Four things keep it from being a dead end: the envelope is real (rotation rewraps DEKs
and leaves ciphertexts byte-identical — asserted), `key_version` exists from the first
row, startup validation refuses to boot without a usable key **when the runner layer is
on**, and the KMS path is one function.

> **The startup check is conditional, and that is a decision.** Unconditional would stop
> every deployment that does not use V2 from booting, to protect zero rows. All three
> precedents in this codebase for a required secret are conditional.

### Refusals at creation

Reserved names (`PATH`, `HOME`, `LD_PRELOAD`, …) and reserved prefixes (`GIT_`, `SSH_`,
`CLIORA_`) are refused where the person is standing rather than skipped on the node.
`GIT_ASKPASS` is not a decorative entry on that list: a secret by that name would take
over the entire credential-helper mechanism §3b is built on. The daemon re-checks
anyway — it is the layer that hands the value to execve.

### Residual risks in this section

| Risk | Disposition |
|---|---|
| An encoded secret in a log | Accepted, documented; bounded by revocation and log expiry |
| A secret inside an uploaded artifact | Unchanged from ADR 0030: the platform does not inspect binary content and does not claim to |
| The master key in the same trust boundary as the data | Accepted (ADR 0032 §3); the KMS path is kept open rather than taken |

---

## §2 — The authorization boundary

**This section used to have a checkpoint to examine and no longer does.** The 2026-08-12
ruling cancelled `project_agents` rather than deferring it, so there is no binding table
to review. What is reviewed instead is whether the four compensating controls exist and
whether any interface implies a stronger boundary than the one there is.

> **Issuing an enrollment token authorises that machine to draw the secrets declared by
> any card it can claim.**

### The four controls, verified

| Control | Where | Verified by |
|---|---|---|
| A card gets only the secrets it declares, from the project's allowlist | Checked at card edit **and** at dispatch, with two distinct refusals | `test_a_card_declaring_a_secret_outside_the_allowlist_names_it`, `…an_allowed_but_uncreated_secret_says_so_differently` |
| A node may refuse | `accept_secrets: false`; its runner is never offered a card that declares any | `test_a_node_that_refuses_secrets_is_never_offered_a_card_with_any` |
| Revocable, and every delivery audited | Soft delete effective at the next claim; one `secret.deliver` row carrying **names only** | `test_delete_is_soft_and_the_name_becomes_free_again`, and the audit payload assertion |
| The enrollment screen says it out loud | Inside the form that issues the token | `EnrollmentView.test.ts` |

**These four are not an equivalent substitute for an authorization table.** They shrink
a radius that remains large.

### Tags are not authorization

A tag is a string the runner reports about itself in `runner.register`. A compromised or
misconfigured runner changes what it is offered by reporting one more. Two consequences
are enforced rather than stated:

- **Read-only through the API.** `labels`, `run_untagged` and `accept_secrets` left
  `EDITABLE_RUNNER_FIELDS` in this phase — while tags were decorative an edit was
  harmless vanity; now they decide dispatch, and an edit would be a second source of
  truth the node's next registration silently overwrites.
- **No interface draws one as a security control.** `AgentsView.test.ts` asserts the tag
  cell's rendered DOM contains no padlock and no word meaning "authorised". The
  assertion is scoped to that cell rather than the page **because the page must contain
  the word** — the boundary paragraph is the other half of the same requirement. A
  whole-page assertion would have forbidden the disclosure it exists to protect.

### Two costs, stated

- Any enrolled machine whose tags match can claim any project's card and receive the
  secrets it declares.
- **`run.dispatch` is a Developer action**, and naming a runner on a card causes that
  machine to receive the card's secrets. No Admin approval sits between those two facts.
  What contains it is that enrollment itself is an Admin action.

---

## §3 — The git write

**This section is two halves whose defaults are opposite**, and reading it as one is the
mistake it is arranged to prevent.

### §3a — Send-back (on by default)

The platform now pushes on a card's behalf. Five constraints bound it, compiled into
`gitfetch/push.go`:

1. Only a branch under `cliora/`.
2. Never the base or target branch — implied by 1, asserted separately.
3. Never a force push, a remote deletion or a tag. **Implemented as those strings not
   being in the table**, rather than as a check that they are absent: a check can be
   bypassed by a second call site. `GATE-SC-PUSH-ARGV` asserts the absence.
4. Only a host on the allowlist, through the same `CheckURL` the fetch half uses.
5. The commit identity is a bot and does not impersonate a person.

Every refusal happens **before `git` is executed**, and the test asserts that by running
against a directory that is not a repository at all — if the check were downstream, git
itself would fail rather than the rule.

The remote URL is passed explicitly rather than using `origin`: `.git/config` is inside
a directory the agent may write to, so constraint 4 must check the address the
*platform* knows.

**Constraint 5 has two tiers and they are not the same strength.** `user.name` /
`user.email` are set in the checkout's local config and the platform controls them —
*the platform never impersonates a human* is a guarantee. The `Cliora-Run-Id` trailer is
appended by a hook inside a directory the agent can write to, so *every commit is
traceable to a run* is best effort. Presenting these as one guarantee would hide which
half is soft.

> ⚠️ **The cost of the default, stated plainly.** On the default deployment the platform
> pushes with a credential it did not issue and cannot revoke — the node's own. The five
> constraints still hold; **"revocable" does not apply to that path.** What contains it
> is the node's deployment posture (`dedicated`) and red line 5: a branch nobody merges
> affects nobody.

### §3b — Platform-managed credentials (**off by default**)

`CLIORA_GIT_SECRET_DELIVERY_ENABLED`, default `false` (2026-08-13 ruling: at this stage
git authentication is the node owner's manual configuration, which the platform does not
manage). With it off:

- `kind: git_pat` / `git_ssh_key` **cannot be created** — refused with the variable
  named. Storing a credential that would never be delivered is a configuration that
  looks finished and is not.
- `auth_kind` may only be `ambient`.
- `spec.secrets` never carries a git kind.
- **The ambient-credential isolation does not engage.**

The last one is the correction this ruling forced. Isolation was specified as "replace,
by default" because a revocable credential loses meaning beside an unrevocable one — and
*that reasoning holds only when a platform credential exists*. Applying it
unconditionally would hide the machine's credentials and supply no replacement: every
private-repository clone would fail, and the symptom would look like a misconfigured
credential rather than a policy. The trigger is therefore "this run received a git
secret", asserted by `TestIsolationOnlyAppliesWhenAPlatformCredentialArrived`.

With the flag on:

- **PAT**: `GIT_ASKPASS` points at a helper containing no secret, reading an environment
  variable. Not in the remote URL (`git remote -v`, reflog, error messages), not via
  `-c http.extraHeader` (`ps`). `GIT_TERMINAL_PROMPT=0` is retained, so the
  "fails in seconds, not hours" property measured in V2.2 survives the change.
- **SSH**: `ssh-agent` per run, key on `ssh-add -`'s stdin, socket at 0700 inside the
  run directory, killed at the end. Writing a 0600 key file and deleting it afterwards
  is explicitly not acceptable: it is on disk in between, and a failed delete leaves it.
- **Isolation is not a sandbox.** It makes git blind to those credentials. The run's
  child shares an OS user with agentd and can read the home directory; what is bought is
  that the default path does not use them by accident.

### Residual risks in this section

| Risk | Disposition |
|---|---|
| The platform pushes with an unrevocable credential (default path) | **Accepted, by ruling.** Bounded by the five constraints and by node posture |
| An agent pushes with the machine's own credentials | Unchanged from V2.2 (2026-08-10 ②): deliberate, answered by observability |
| A commit trailer removed by the agent | Best effort by design; the identity half is hard |
| Shallow-clone push against a host that refuses it | **Unverified.** Needs a network remote — the open item in `plan/20/09-…md` §2.1 |

---

## Verification run for this review

```
scripts/sc/gates.sh                     10/10
backend/tests/db                        543 passed
daemon go test ./...                    17 packages
make check                              green
```

**Not covered by any of that, and named rather than implied**: the SSH path against a
real remote, a shallow-clone push, and the Traqora run (`plan/20/08-…md` §4). Those need
a machine with `ssh-agent` and network access to a real host.
