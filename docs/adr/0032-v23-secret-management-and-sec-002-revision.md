# ADR 0032 — Project secrets: envelope encryption, delivery at the claim, and the one sentence of SEC-002 that is withdrawn

- Status: **proposed** (2026-08-13) — waiting on gate two, which is a person's
  approval. Until it is accepted, `SC-03` onward may not touch `backend/`,
  `frontend/`, `daemon/` or `contracts/` (`plan/20/00-…md` §4). A document that
  marks itself accepted would make that gate meaningless.
- Date: 2026-08-13
- Amends: **SEC-002**, in exactly one clause (§1). Everything else in SEC-002 is
  reproduced here unchanged, because a revision that only lists what it removes
  makes the reader reconstruct what survived.
- Related: ADR 0022 (the tunnel provider credential — the pattern this copies and
  the module it deliberately does **not** share), ADR 0023 (report the machine's
  posture, never set it — where `accept_secrets` comes from), ADR 0027 (feature
  flag is not a permission), ADR 0029 (the runner model; §0 here is the
  authorization boundary that ADR's tag amendment refuses to re-argue), ADR 0031
  (the run directory and git; the send-back half is amended there, not here)
- Requirements: `FR-RUNENV-001`, `-002`, `-003`, `-004`, `-009`, `-010`, `-011`
- Contract: **v1.12.0** — `run.offer`'s `spec.secrets`, and two booleans on
  `runner.register`.
- Ships in: Central (minor), `agentd` **0.10.0**, frontend (minor).

## Context

V2.2 gave the platform the ability to start a process on a node with nobody at a
terminal. That process could do useful work only with whatever the machine already
had: its ambient git credentials, its ambient environment. The platform managed
nothing, so it could revoke nothing and audit nothing.

This phase gives the platform one thing it did not have — **a value it holds on a
user's behalf, hands to a machine on demand, and can take back**. That is a new
storage surface, a new credential flow, and the first time a request from a node
results in plaintext leaving Central's database.

Four decisions were already made before this document:

- **2026-08-08** — the master key lives in an environment variable; both
  fine-grained PAT and SSH key are supported.
- **2026-08-11** — `runner.git.isolate_ambient_credentials`, default "replace".
- **2026-08-12** — **`project_agents` is not built.** Pairing is tags plus an
  optional named runner, and **the authorization boundary is permanently
  enrollment**.
- **2026-08-13** — **delivering git credentials is off by default.** The mechanism
  is built, gated by an environment variable; at this stage git authentication is
  the node owner's manual configuration and the platform does not manage it.

The third and fourth of those decide the shape of this document, so they come
first.

## Decision

### §0 — The authorization boundary is enrollment

> **Issuing an enrollment token authorises that machine to draw the secrets
> declared by any card it can claim.**

This section is first because it decides the threat model every later section is
written against.

**`project_agents` is not built.** Not deferred — not built. The full argument and
the rejected alternatives are reproduced in §Alternatives; the one that matters
here is why a tag cannot stand in for it:

> **A tag is a string the runner reports about itself in `runner.register`.** A
> compromised or misconfigured runner changes what it is offered by reporting one
> more tag. Either authorization is a row somebody *else* wrote, or the boundary is
> enrollment. Treating a self-reported value as authorization buys the feeling of
> security and not the thing.

**Tags decide which machine the work goes to. They do not decide which machine may
hold a secret.** That sentence appears three times in this repository — here, in
ADR 0029's tag amendment, and in the `runner.register` schema — because the three
audiences read exactly one of the three.

**The blast radius, stated plainly:** any enrolled node's runner whose tags match
can claim any project's card and receive the secrets that card declares. Nothing
narrows *which machines*; four things narrow *how much*:

| Compensating control | Where it lands | What it bounds |
|---|---|---|
| A card gets only the secrets it declares, and only from the project's allowlist | `tasks.required_secrets` ⊆ `projects.allowed_secret_names`, checked at card edit **and** at dispatch | The maximum a single card can disclose is its own list, not the project's |
| A node may refuse | `accept_secrets: false` in the node's config; its runner is only ever offered cards with no `required_secrets` | The operator of the machine, who knows what else runs there, gets a veto |
| Revocable, and every delivery is audited | Soft delete takes effect on the next claim; one `audit_logs` row per delivery, carrying **names and never values** | The window between "this leaked" and "this is useless" is one run |
| The enrollment screen says this out loud | The sentence at the top of this section, on the page that issues the token | The person creating the boundary is told what it is |

**These four are not an equivalent substitute for an authorization table.** They
shrink a radius that remains large. Each is verified by its own exit condition
(`plan/20/07-…md` §5, conditions 3h, 3, 10/10b, 3g) — the security review checks
that the four exist, because the checkpoint it used to check (a binding table) no
longer does.

**One consequence that is easy to miss, so it is written here rather than left in
`01` D17b:** `run.dispatch` is a Developer action, and naming a runner on a card
causes that machine to receive the card's secrets. **No Admin approval sits between
those two facts.** What contains it is that enrollment itself is an Admin action.

### §1 — SEC-002, revised in one clause

| SEC-002 | Disposition |
|---|---|
| A caller may not name a command, a binary or a shell string | **Unchanged.** argv is still composed by the daemon from closed tables |
| A caller may not specify environment variables | **Revised**: a request payload may not carry the **value** of a secret. Values come only from the platform's secret store; names come only from the project's allowlist |
| Interactive sessions | **Unchanged**, not one byte |

The invariant after the revision, in one sentence:

> **No request payload can name a command, or carry the value of a secret.**

This is more precise than the wording it replaces, which bound "no environment
variables" together with "no arbitrary execution" as though they were one rule.
They are two, and only the first is being narrowed.

**The revision is verifiable against the code, not only against this document.**
The path a value takes is `RunService.poll()` → `SecretService.materialise()` →
`RunOffer.spec()`. Not one step on it accepts caller input: `poll` is answering a
node's own poll frame, `materialise` takes a project id and a list of names read
from the card, and the card's names were checked against the project allowlist when
they were written. The wire form is checked too — a fixture asserts that `secrets`
appearing on any message other than `run.offer` is rejected.

### §2 — The ten rules a secret follows

The first nine are the 2026-08-08 decision; the tenth is this phase's.

1. **Encrypted at rest**, envelope, per-row data key (§3).
2. **Never readable back.** No API returns a value. Asserted twice: a scan over
   every response schema in the OpenAPI document, and a sentinel value asserted
   absent from the raw bytes of five different endpoints' responses.
3. **Delivered on demand**, only the ones the card declares, only at the claim.
4. **Never written to a file.** One exception, and it is not one: see rule 10.
5. **Redacted on the node**, before the value can leave it.
6. **Names come from an allowlist** the project owns.
7. **A node may refuse** (`accept_secrets: false`).
8. **The audit carries names, never values** — and never a length or a
   fingerprint either. A length is a side channel: a 93-character value is almost
   certainly a fine-grained PAT. A fingerprint answers "is this the one I rotated
   last week", and `rotated_at` answers that without disclosing anything.
9. **Rotatable and revocable.** A run in flight is unaffected — the value is
   already in that machine's memory and the platform cannot recall it. The next
   claim does not get it.
10. 🆕 **`kind` decides where the value goes** (§4).

**Rule 4's one exception is a socket, and a socket is not a key.** The SSH path
runs an `ssh-agent` whose socket lives inside the run directory at 0700 and dies
with the run; the private key is fed to `ssh-add -` on **stdin** and never touches
a filesystem. This sentence is in the ADR because without it the natural
implementation is "write a 0600 file and delete it afterwards" — which violates
rule 4, and leaves the key on disk whenever the delete fails.

### §3 — Envelope encryption, and what the environment-variable master key costs

**A new module, `app/security/secret_envelope.py`. `secret_box.py` is not touched.**

Each row carries its own 32-byte data key. The value is encrypted under the DEK;
the DEK is encrypted under the master key; both ciphertexts and both nonces are
stored in the row, along with `key_version`. The AAD is
`cliora-project-secret-v1` — different from the tunnel credential's, so the two
kinds of ciphertext cannot be decrypted in each other's context.

Sharing `secret_box.py` was considered and rejected (§Alternatives). It has no
envelope and no `key_version`, its key is `CLIORA_SECRET_ENCRYPTION_KEY`, and the
two kinds of secret rotate on different occasions — a provider change for one,
personnel movement for the other. Sharing a key ties each rotation to the other.

**What the environment-variable master key costs. This section does not only list
the benefits:**

- **The key and the ciphertext share one trust boundary.** Whoever can read the
  environment can usually read the database. This is not fatal, but it means the
  protection against "the database backup leaked" rests on the attacker not having
  the environment, rather than on two independent defences.
- **There is no decryption audit.** Nobody knows who decrypted what, and when.
- **Losing the key loses every secret**, irrecoverably. They can only be recreated,
  which means reissuing every token at every provider.

Four things keep this from being a dead end:

1. **The envelope is real**, so rotating the master key rewraps DEKs rather than
   rewriting every ciphertext.
2. **`key_version` exists from the first row**, not "added later".
3. **Startup validation** — but **conditional**, tied to
   `CLIORA_AGENT_RUNS_ENABLED`. An unconditional check would stop every existing
   deployment that does not use V2 from booting, and those deployments hold zero
   secrets. The shape is copied from the `metrics_scrape_token` validator, which
   made the same call for the same reason.
4. **The KMS path stays open.** With an envelope and a `key_version`, moving to a
   KMS replaces one function — the one that unwraps a DEK. This sentence is here so
   that in six months nobody concludes the original choice was a mistake to be
   redone wholesale.

**An operational fact with no software answer:** a database backup cannot restore a
secret, because the key is not in it. The backup runbook gains a clause (keep the
key separately, and record the `key_version` it matches), and the secrets settings
page says the same thing on screen — a runbook is not where somebody looks before
typing a value in.

### §4 — `kind` decides where the value goes, and git credentials are off by default

| `kind` | Where the value goes | Default |
|---|---|---|
| `env` | The CLI child process's environment | **On** |
| `git_pat`, `git_ssh_key` | **The daemon's own git environment only. Never the child's.** | **Off** — `CLIORA_GIT_SECRET_DELIVERY_ENABLED`, default `false` |
| `provider_token` | Nowhere. Not delivered in this phase | — |

**Why git credentials do not go to the child.** What this phase buys is a
*revocable* credential. Putting it in the agent's environment hands the agent the
same credential — and the agent can push it anywhere, where **none of the five hard
constraints reach it**, because those are compiled into the daemon's push path. The
guarantee would then cover only the platform's own behaviour, which is not what
"revocable" is usually taken to mean.

**Why the whole git path is off by default (2026-08-13).** The ruling:

> Delivering git credentials from the platform is a wide-reaching change. It may be
> implemented, but it must be controlled by an environment variable and off by
> default; at this stage git authentication is node-side manual configuration,
> which the system does not manage — it is the node owner's to handle.

With the flag off: secrets of the two git kinds **cannot be created** (the API
refuses and names the variable), `project_repositories.auth_kind` may only be
`ambient`, `spec.secrets` never carries a git kind, and the ambient-credential
isolation of ADR 0031 does not apply. Refusing creation rather than storing an
unusable credential is the same judgement this repository already made when it
declined to pre-create a `project_agents` table that authorised nothing: a stored
credential that is never used is a configuration that looks finished and is not.

**The cost of the default, stated plainly:** the platform now pushes on a card's
behalf, and on the default path it pushes with a credential it did not issue and
cannot revoke. The five hard constraints still hold in full — they constrain *what
is pushed*, not *which credential pushes it* — but "revocable" does not apply to
that path. What contains it is the node's deployment posture and red line 5.

## Consequences

- **A secret is decrypted inside the node WebSocket receive loop**, at the claim.
  It is CPU-bound work with no `await` on a node round trip, which is the property
  that makes it safe there (`services/runs.py` documents why nothing in that module
  may call `registry.request()`). The audit row and `last_used_at` are written in
  the **same flush** as the claim: separating them creates a window in which a
  machine holds a secret with no record that it does.
- **A runner that declines after being offered has already received the secrets.**
  The audit says they were delivered, and it is not retracted. This is the honest
  record, and it is a cost of claiming at poll rather than at accept.
- **`run.offer` can now be too large to send.** It is a 64 KiB control frame and is
  deliberately not in the large-frame set — that socket also carries interactive
  terminal bytes. Central therefore measures the assembled frame before sending and
  **releases the claim** if it does not fit, leaving a message on the card. Without
  that, the failure is the worst kind: the frame is dropped silently on the node,
  the lease expires, the card is retried three times and blocked, and nothing
  anywhere reports an error.
- **Redaction is best effort and this document says so.** Values are matched
  literally. A base64- or URL-encoded value gets through. The second line of defence
  is not a better matcher, it is that secrets are revocable and logs expire.
- **Redaction covers every outbound frame, not only log chunks.** `run.failed`
  carries git's stderr and `run.complete` carries free text; the credential-shaped
  path is the error message, not the log.
- **Repository management moves from `project.manage` to `secret.manage`.** Both
  are Admin-only, so no role loses an ability — but it is a tightening, and an
  unannounced tightening surfaces as a 403 in somebody's automation.
- **Values above 8 KiB are refused.** An RSA-4096 private key measures 3 369 bytes
  and an ed25519 key 399; the ceiling has 2.4× headroom over the largest legitimate
  input.

## Alternatives rejected

| Option | Why not |
|---|---|
| **`project_agents(project_id, runner_id, enabled)` as the secrets authorization boundary** | Rejected 2026-08-12. A card can already name a runner and tags already express routing, so a binding table is a **third** set of data somebody has to maintain. An N×M authorization matrix, in a deployment with a handful of runners, buys less security than it costs in maintenance and failure modes — the commonest of which is "the new project was never bound, and its cards quietly go unclaimed", which is precisely the silent-wait state the console spends effort avoiding. **This is deliberately trading security posture for operational simplicity, not an oversight** — which is why the cost is written in §0 rather than hidden. **This row may not be dropped**: without it, a later reader of this ADR concludes nobody considered an authorization table |
| **Letting tags double as authorization** (no matching tag, no secret) | A tag is the runner's own claim about its capabilities. Either authorization is a row somebody else wrote, or the boundary is enrollment |
| **A runner-level `secrets_enabled` switch** (an Admin tick-box per machine) | Rejected 2026-08-12: it makes "which machines can receive secrets" a question with two places to look. And it points the wrong way — `accept_secrets: false` already exists, is declared by the node, and is closer to the truth |
| **Cards carrying env values directly** | The secret lands in a plaintext database column and in the UI |
| **The runner reading a local `.env` on the node** | The platform can neither audit nor revoke it |
| **Sharing `tunnel_integration`'s table or `secret_box.py`** | Different risk class, different rotation triggers. Sharing makes each rotation hostage to the other, and turns a module that passed a security review for one purpose into one serving two |
| **The master key in a KMS** | Rejected here **because it adds a cloud dependency that a self-hosted deployment cannot satisfy — not because it is worse.** This sentence matters: with the envelope and `key_version` in place the upgrade is one function, and without this line the choice reads as though a KMS was never considered |
| **Putting git credentials in the child's environment too** | §4. Buys the agent its git freedom, spends the meaning of "revocable", and the five hard constraints cannot reach it |
| **Storing git-kind secrets while delivery is disabled** | A credential that is stored and never used is a setting that looks complete and is not — the same judgement that declined to pre-create an authorization table that authorised nothing |
| **Promoting `run.offer` to the large-frame set** | That socket carries interactive terminal bytes. The reasoning is identical to V2.2's refusal to enlarge `run.log_chunk`, and the answer is the same: bound the payload, do not widen the pipe |
| **Delivering secrets in a second message after the offer** | One more message type, and a new ordering question ("what if the run starts before the secrets arrive") for a frame that is already a one-shot statement of fact |
| **An unconditional startup check for the master key** | Would stop every existing deployment that does not use V2 from booting, to protect zero rows. All three precedents in this repository for a required secret are conditional |

---

# Amendment (V2.4, 2026-08-14) — the first code path that uses `provider_token`, and a second store that names commands

## A1 — `provider_token` is used on Central and is still never delivered

V2.3 defined the kind, stored it, and had no code path that sent one. V2.4 is the
first user, and the place it is used is **Central's memory** — never a node.

`UNDELIVERABLE_KINDS` therefore stays as it is, and this amendment records that it
is permanent rather than pending: the five hard push constraints bind the daemon's
git path, and nothing in them reaches an HTTPS request to a provider's API. A
credential that can write to a repository without going through git is a credential
none of them can contain.

## A2 — It is decrypted outside the receive loop, and that is a different rule from §Consequences

The base document says a project secret is decrypted **inside** the node WebSocket
receive loop, at the claim, and explains why that is safe: AES-GCM is CPU-bound and
awaits nothing.

The provider token is decrypted in the **background worker** that opens pull
requests, because what follows it is a network call to somebody else's server. The
same loop that carries interactive terminal bytes cannot wait on that.

Both are true; they are different paths. This is written down because "secrets are
decrypted at the claim" reads like a description of the whole system, and after this
phase it describes one of two paths.

## A3 — Delivery auditing is unchanged; PR creation gets its own record

`materialise` still audits names and never values. Opening a pull request writes a
separate audit row — repository, PR number, head, base — and **no token, no
fragment of one, and no length**.

## A4 — A second platform-side store may name a command (SEC-002 is not amended again)

The revised invariant from §1 stands **word for word**:

> No request payload may name a command, or carry a secret's value.

V2.4 adds `tasks.verification_commands` beside `projects.verification_commands`.
Both are columns in Central's database, written by an authorised request and read
back by Central when it assembles an offer — structurally identical to the argument
this ADR made for `spec.secrets`, and for the same reason it does not touch the
invariant.

What keeps the card-level store from re-opening what §1 closed is **which action
writes it**: `task.approve`, which `RUN_TOKEN_SCOPES` deliberately excludes (this
module records that it is the half a run credential can never hold). A person may
declare a check on a card; the agent being verified may not. The full argument is
ADR 0033 §3b.

## Alternatives rejected (amendment)

| Rejected | Why |
|---|---|
| Delivering `provider_token` so the node opens the PR | The agent's sandbox would reach a credential that can write to any repository the token allows, and no push constraint applies to an HTTPS call |
| Decrypting the provider token at the claim, with the other secrets | It is followed by a network call. The receive loop also carries terminal bytes |
| Authorising card-level verification commands with `task.update` | The verified party would choose its own verification. Every exit code would remain real and every one would be worthless |
| Amending SEC-002 a second time to permit "commands from a card" | Nothing needs permitting. A column is not a request payload, and saying otherwise would weaken the invariant to describe a case it already covers |
