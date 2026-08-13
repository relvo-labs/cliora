# Release note — project secrets, tag dispatch, and branch delivery (V2.3)

Requires `agentd` **0.10.0** on a node, contract **v1.12.0**, and migrations through
`0034`. Everything here is behind `CLIORA_AGENT_RUNS_ENABLED`; with both flags off the
system behaves exactly as it did before.

## What is new

**Project secrets.** A project can hold values the platform hands to a runner on demand
— envelope-encrypted, never readable back, revocable, and audited by name at every
delivery. A card declares which ones it needs from a project-level allowlist, and only
those are delivered.

**Tag dispatch.** A card can declare tags and a runner reports its own; a card reaches a
runner when its tags are a subset of the runner's. Two node-side declarations go with
it: `run_untagged: false` reserves a machine for tagged work, and
`accept_secrets: false` keeps it away from cards that declare secrets. When nothing can
claim a card, the console says **which tags are missing** rather than "waiting for an
available agent".

**`delivery: branch`.** The platform pushes the run's work to
`cliora/<card>-<attempt>`, under five constraints compiled into the daemon.

## ⚠️ Two behaviour changes

**1. The platform now pushes to your remotes, and on the default configuration it uses
the node's own git credentials.**

Until this release the platform never wrote to a remote. It does now, for cards with
`delivery: branch`. The five constraints hold regardless of which credential is used —
they constrain *what* is pushed: only a `cliora/…` branch, never a base or target
branch, never a force push or a deletion or a tag, and only to a host on the allowlist.

But **"revocable" does not apply to the default path**: the credential belongs to the
machine, and Cliora can neither manage nor revoke it. If that matters for your
deployment, the answer is either a dedicated runner node or turning on the platform's
own credential management (below).

**2. Registering a repository now requires `secret.manage` instead of `project.manage`.**

Both are Admin-only, so no role loses an ability — but automation holding only
`project.manage` will start seeing 403. The reason for the move is that a repository row
stopped being "where the code is" and became "which credential fetches it".

## Off by default: platform-managed git credentials

`CLIORA_GIT_SECRET_DELIVERY_ENABLED` (default `false`). At this stage git authentication
is configured on the node by its owner and the platform does not manage it. With the
flag off:

- Secrets of kind `git_pat` and `git_ssh_key` **cannot be created** — the API refuses
  and names the variable. A credential the platform stores and never delivers is a
  setting that looks finished and is not.
- A repository's authentication may only be "use this machine's existing git
  credentials". The console shows the other two options **disabled with the reason**
  rather than hiding them.

Turning it on adds a third behaviour change: with a platform credential in play, the run
is isolated from the machine's own git configuration, so **the agent can no longer fetch
or push using either the platform's credential or the machine's** during a run. That is
the point — the platform's credential is revocable only if it is the platform's — but it
is a real change to what an agent can do inside the sandbox, and it does not happen
unless you enable this.

## Operating a deployment with secrets

```bash
CLIORA_SECRET_MASTER_KEY="$(openssl rand -base64 32)"
```

Required as soon as `CLIORA_AGENT_RUNS_ENABLED` is true; Central refuses to start
without a usable one and names which of the four ways it is unusable. With the runner
layer off it is not needed at all, so an existing deployment that does not use V2 is
unaffected by this release.

**Three things the software cannot check for you:**

| | Why |
|---|---|
| Keep the key **separately from the database backup** | The backup cannot restore a secret without it. Losing the key loses every secret irrecoverably — they can only be recreated, which means reissuing every token at its provider |
| Record which `key_version` a backup matches | Rotation moves the version; a restore under the wrong one fails with a message that names the version, but only if the key still exists |
| Use a **different** key from `CLIORA_SECRET_ENCRYPTION_KEY` | The two rotate for different reasons — a tunnel provider change for one, personnel movement for the other. Sharing makes each rotation hostage to the other |

**Rotating the master key**: put the old value in `CLIORA_SECRET_MASTER_KEY_V<n>`, the
new one in `CLIORA_SECRET_MASTER_KEY`, and raise
`CLIORA_SECRET_MASTER_KEY_VERSION`. Existing rows keep opening under their own version;
rewrapping re-encrypts the per-row data key and never rewrites a ciphertext.

**Deleting a secret stops the platform delivering it. It does not revoke it anywhere
else** — Cliora does not know what that token is called at GitHub. The console says so
at the point of deletion.

## Known trade-offs

**The authorization boundary is enrollment, permanently.** Any enrolled machine whose
tags match can claim any project's card and receive the secrets that card declares.
There is no per-project authorization and there will not be one: the design trades that
for operational simplicity, and the trade is written down in ADR 0032 §0 rather than
hidden. What bounds the radius is four things — a card gets only what it declares from
the project's allowlist, a node may refuse secrets entirely, every delivery is audited
and revocable, and the enrollment screen states the consequence where the token is
issued.

**A tag is not authorization.** It is a value the runner reports about itself, so a
compromised or misconfigured runner changes what it is offered by reporting one more.
Tags decide *which machine*, never *which machine may hold a secret*. They are read-only
in the console for that reason — changing them means editing that node's config.

**Redaction of secrets in logs is best effort.** Values are matched literally, so an
encoded one can get through. The real protections are that secrets are revocable and
logs expire.

**Token spend is still measured, not capped.** Unchanged from V2.2, and for the same
reason: `claude --max-budget-usd` exists and codex has no equivalent, and wiring up half
of it would suggest a protection that only covers one runtime.

## Upgrading

1. Migrate to `0034`.
2. Set `CLIORA_SECRET_MASTER_KEY` if the runner layer is on.
3. Roll `agentd` **0.10.0** to runner nodes. A node that has not been upgraded keeps
   working: it sends neither `run_untagged` nor `accept_secrets`, both are read as
   `true`, and it behaves exactly as it did — the compatibility rule is a property of
   the payload, not of a version number.
4. Add `tags:` to a node's `runner:` block to make it eligible for tagged cards. **A
   node with no tags claims only cards that declare none**, so nothing changes until you
   do. `agentd doctor` prints the three declarations.
