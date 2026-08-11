# ADR 0031 — The isolated run directory, and how a run gets its code (fetch half)

- Status: **proposed** — written form of the two rulings of 2026-08-10
  (`plan/18/README.md` §裁決紀錄); acceptance is a human action and is **gate
  four**: `AR-03` (schema) and `AR-07b` (the daemon's directory work) both wait on
  it, because it decides where the run root lives, what a quota means, and who
  reclaims the space (`plan/18/00-…md` §4).

  > **This version covers only the *fetch* half of git.** The send-back half —
  > push, the `cliora/<card_ref>-<run_seq>` branch namespace, the five hard
  > constraints — and platform-managed credentials **amend this same document in
  > V2.3**. A document that will be amended has to say so in its first version;
  > otherwise the next author has to guess whether to edit this or start a new
  > one, and both answers produce a file that lies.
- Date: 2026-08-11
- Amends: nothing yet. It **narrows ADR 0028's projection rule** in one place: the
  platform's `.cliora/{context,process}` write path is a *daemon-local file write*
  when the destination is a run directory, not a `VerbProject` round trip, because
  the destination is the daemon's own directory rather than the user's workspace.
- Related: ADR 0014 (path containment — §3.6 uses the same `filepath.Rel`
  reasoning as `authorize_workspace`, deliberately **without** sharing the
  implementation), ADR 0023 (a node is a disposable isolated VM, and "report the
  machine's actual posture, never the posture you wish for" is where `dedicated`
  comes from), ADR 0024 (who cleans this up — this is the third of three answers
  in this phase), ADR 0027 (`.cliora/` is the only thing ever projected into a
  workspace; here it is projected into a directory the platform owns instead),
  ADR 0029 (the run lifecycle), ADR 0030 (what leaves the directory and what
  outlives it)
- Requirements: `FR-AGENT-011`, `FR-AGENT-012`, `FR-AGENT-013`
- Contract: **v1.11.0** — no message of its own. `spec.source` on `run.offer`, and
  `commit_sha` / the git summary fields on `run.progress` / `run.complete`.
- Ships in: **`agentd` 0.9.0** only, plus one line in the systemd unit
  (`StateDirectory=agentd`). No Central behaviour depends on where the directory
  is; Central does not even learn its path.
- Plan: `plan/18/04b-run-directory-and-git.md`

## Context

The 2026-08-10 ruling replaced this phase's largest known gap. The original design
ran an unattended agent **in the user's bound workspace** — next to their
uncommitted work — and the ruling said: the agent pulls the project itself, like a
GitLab runner, into a hidden directory, and workspace bindings from now on serve
interactive sessions only.

That moves two pieces of V2.3 forward (the isolated directory, and the fetch half
of git) and one piece of V2.2 back (project↔agent binding). It also creates the
first place in this system where **the platform triggers a git operation**, and the
first directory the platform both owns and fills with a third party's code.

A second ruling the same day narrowed the design again, in the opposite direction:
**do not block the agent from pushing, and do not require read-only credentials.**
§5 records what that means and what replaced the blocking.

## Decision

### 1. Two trees on one node, and nothing joins them

```text
/var/lib/agentd/                     ← the agent's ground. StateDirectory, 0700, service user
└── .cliora/
    ├── mirrors/<repo_hash>/         ← one bare mirror per repo, shared by every run
    └── runs/<run_id>/
        ├── repo/                    ← git worktree; the child process's cwd
        ├── .cliora/context|process/ ← the context pack and the run token (0600)
        ├── artifacts/               ← what the run produces
        └── .git-config              ← user.name = cliora-run

/home/<user>/projects/<repo>/        ← the interactive session's ground; an allowed root
└── .cliora/{context,uploads,.gitignore}
```

A run lives only in the first tree. `run.offer`'s `spec` **has no `workspace`
field**: the daemon chooses the directory and Central never learns its path.

### 2. Six rules for the run directory

1. **It is outside every allowed root, in both directions.** Neither the run root
   inside an allowed root, nor an allowed root inside the run root.
2. **A fresh directory per run.** Never reused, never shared; `run_id` is the name.
3. **Two quota layers plus a free-space floor** (§4).
4. **The repository cache is separate from the run** — `mirrors/` is shared, `runs/`
   is not.
5. **The daemon reclaims it**, on a retention period that depends on the outcome
   (§4).
6. **`artifacts/` is an enumeration, not a file browser.** The daemon lists what
   the run put there; no API browses it.

Rule 1 is enforced at startup, not documented (§3.6). Rules 3 and 5 are what make
the directory safe to fill with a process that runs for an hour.

### 3. Why `StateDirectory`, and the one line in the unit

The current unit has `RuntimeDirectory=agentd` → `/run/agentd`, which is **tmpfs**
(`daemon/internal/install/systemd.go:39`). A failed run's directory has to survive
14 days, and tmpfs does not survive one reboot. So the unit gains exactly one line:

```ini
StateDirectory=agentd          # → /var/lib/agentd, created 0700 as the service user
```

systemd's own directive rather than `mkdir` + `chown`: doing it by hand adds a
root/non-root branch to `install/`, and that single line is the only change this
phase makes to that package.

`runner.work_dir` defaults to `<StateDirectory>/.cliora/runs`. The `.cliora`
segment is kept because the ruling asked for a hidden directory by that name, and
because it inherits an accidental but real benefit: image drop already writes a
`.cliora/.gitignore` containing `*` (`upload.go:38`), so if an operator points
`work_dir` somewhere that happens to be inside a repository, git already ignores
it. That is a softened worst case, **not** something the design relies on.

`repo/` and `.cliora/` are **siblings**: the context pack is not inside the clone,
so it cannot appear in `git status`, cannot be committed by accident, and needs no
gitignore to protect it. The `cliora` CLI finds it without a code change, because
`FindContext` (`cli.go:71`) already searches upward from the cwd — and because the
run directory holds exactly one context pack, the "several packs, name one with
`--session`" branch becomes unreachable.

### 4. Quotas and reclamation

| Layer | Setting | On exceeding |
|---|---|---|
| One run directory | `runner.run_quota_bytes` | run `failed` with `RUN_DISK_QUOTA`, stated in the log |
| All runs on the node | `runner.total_quota_bytes` | **stop polling**, report the reason on heartbeat |
| Free-space floor | `runner.min_free_bytes`, default 512 MB | same |

The floor reuses `DefaultFileUploadMinFreeBytes` (`config.go:226`) deliberately:
the agent's clones and the user's uploads compete for one disk, and two different
floors would let one starve the other.

**Stop polling rather than report offline.** "Out of disk" and "machine is gone"
are different facts and a person reacts differently to each.

| Outcome | Retained | Reclaimed by |
|---|---|---|
| success | 3 days | the daemon's cleanup loop |
| failed / lost / cancelled | 14 days | the same |
| a mirror, unused | 30 days | the same |

The loop follows `projectionRetentionLoop` (`connection.go:627`) line for line:
owned by `Run`, cancelled with the connection, `defer <-done` proving the goroutine
exited. **The run token file is deleted the moment the run ends**, not at the
retention deadline — a credential's lifetime is the run, not the directory.

This is ADR 0024 §W2's third answer in this phase; the other two are in ADR 0030.

### 5. git: the executable, a closed argv table, and ambient credentials

**`git` the executable, not a Go library.** `daemon/go.mod` gains no dependency.
Three reasons: bare mirror plus `git worktree` is precisely where go-git is
weakest; a second implementation means the daemon's view of the repository can
differ from the agent's, and the agent in the sandbox uses real `git`; and
whether `git` exists is answered by the same probe shape as `RunCapable`
(`git --version`), reporting `runtimes: []` and a `doctor` line when it does not.
**`git` is a new node prerequisite for runner mode**, and it belongs in the runbook.

**argv is a closed table**, the same discipline as `runArgs`: `clone --mirror`,
`remote update --prune`, `worktree add --detach`, `status --porcelain`,
`remote -v`, `log --branches --not --remotes`, `diff`. No argv element comes from a
request payload, a card's free-text field, or the agent's output. The `--`
separator on `clone` is required, because a URL beginning with `-` is otherwise a
flag. The URL is validated separately: scheme `https` or `ssh`, host in
`runner.git.allowed_hosts`, and **no userinfo** — that last one is the machine form
of "never put a token in a remote URL", which would otherwise surface in `git
remote -v`, the reflog and error messages. The URL is stored as three columns
(scheme / host / path) so userinfo is not representable at all.

SEC-002's test still passes here for a reason worth stating: **the repository URL
is platform configuration, not a caller-supplied string** — the same class of
source as `runtime.binary` in `config.yaml`. It reaches the platform through
`POST /api/projects/{id}/repositories`, which requires `project.manage` and
validates the format strictly.

**Fetch, and only fetch:**

```text
source: none                     → no repo/ is created. The agent has no code, deliberately
source: repo | existing_branch   → mirror update-or-clone → worktree add --detach → record
                                   commit_sha → record the baseline git status --porcelain
```

`--detach` because this phase creates no branches: "which commit is this run on"
then has exactly one answer.

#### The five consequences of using the machine's existing credentials

Platform-managed secrets are V2.3. This phase clones with whatever git
authentication the machine already has — ssh-agent, a credential helper, or a
public repository. **The platform manages, injects and records no credential.**

**One — the platform adds no secret surface.** V2.3's scope is unchanged.

**Two — a private repository is reachable only where the machine already reaches
it, and it must fail fast.** `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=/bin/false`, and
`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=…`, host
keys pinned in the manner of `tunnel.known_hosts_path` (a separate file — a
different host list — but the same posture of pinning rather than
`StrictHostKeyChecking=no`). **These three variables go into the daemon's own git
calls and not into the agent's environment**; their purpose is to keep the
daemon's clone from hanging on a prompt, not to constrain the agent. Without them
a missing credential hangs until the six-hour wall clock, and the user sees "it ran
for an hour and then failed" instead of a failure in seconds. **The idle timer
cannot save this case**: the clone happens before `run.accept`, so there is no
event stream yet to measure.

**Three — the agent may use the machine's credentials for anything git can do,
including push. This is deliberate.** It follows D25: do not constrain what the
agent may do inside the sandbox; constrain how its output leaves. Red line 5's
principle holds on this exit too — *a branch nobody merges affects nobody*. The
convergence points are that principle, the node's deployment posture (ADR 0023: a
runner node should be dedicated), and the observability in point four. **This is
not an apology for a gap**; the framing in which it was one was withdrawn by the
second ruling of 2026-08-10.

**Four — observability replaces blocking, as the primary mechanism.** At the end
of a run, two facts go into the run summary and `run.complete`: the output of `git
remote -v` (with any userinfo masked), and the line count of `git log --oneline
--branches --not --remotes` — how many commits are **not** pushed. The second is not
perfect detection, but it costs nothing, assumes nothing, and makes "did this run
touch a remote" a visible fact on the Run detail page rather than a guess.

**Five — the run's git identity is the machine's.** The platform makes no commit.
The run's `.git-config` sets `user.name = cliora-run` and `user.email =
cliora-run@<node>`: it does not impersonate a person and does not pretend to be
the platform, and `git log` shows which commits came from an unattended run. Bot
identity and commit trailers in full are V2.3.

#### The red line this changes the wording of

`research/02/00` §7 red line 4, clauses 1 and 2, said "the **Agent** may only push
to `cliora/…`, hard-coded in the daemon". After the second ruling that subject is
wrong. The approved wording (2026-08-11; changing a red line's wording is a
governance act and carries its own approval, recorded in `research/02/00` §7)
makes the subject **the platform's push path**, which does not exist until V2.3,
and states explicitly that the agent's own git operations inside the sandbox are
outside those two clauses. This ADR is the technical half of that change; the red
line is the governance half.

### 6. The platform cannot stop the run from reading an allowed root, and says so

An earlier version of this design claimed "the run process cannot read or write
any allowed root". **Nothing implements that**, so the claim is withdrawn rather
than restated:

| Fact | Where |
|---|---|
| The run's child process runs as the **same OS user** as agentd | there is only one; `systemd.go:51` |
| Allowed roots **must** be readable and writable by that user | otherwise interactive sessions cannot start |
| The unit deliberately does **not** hide the home directory | `systemd.go:33`: "PrivateHome is deliberately NOT set: it would hide the user's CLI config and workspaces that the runtimes need" |
| There is no chroot, mount namespace or seccomp | not introduced by this phase |

**Three smaller things the platform does guarantee, and they are true:**

1. No platform path writes into an allowed root. The run directory is created
   outside them, the context pack is written straight into it, and
   `daemon/internal/files/` has a zero diff.
2. The existing file APIs cannot reach the run directory — the reverse direction
   *is* real and testable (`filesystem.list` answers
   `WORKSPACE_OUTSIDE_ALLOWED_ROOT`).
3. `git status --porcelain` in the user's workspace stays empty for the whole run.
   That proves **the platform did not touch it**, not that the agent could not.

The remainder is carried by deployment posture, and posture needs a checkable
definition or it is just a sentence in a runbook. Exactly one of its five
conditions is machine-checkable, and it happens to be the strongest:
**`workspace.allowed_roots` is empty**, on which "the run cannot read an allowed
root" is vacuously true. So the daemon reports it:

```text
runner.register gains:  dedicated: bool   ← len(workspace.allowed_roots) == 0
Agents page shows:      ✔ dedicated runner (this node declares no allowed root)
                        ⚠ mixed use (this node also serves interactive sessions;
                          an agent can read those directories)
```

**A report, not an enforcement**, for three reasons: a mixed-use node is a
legitimate and common setup (one person, one dev VM, both uses, informed consent);
it follows ADR 0023 D3's rule of reporting the machine's actual posture rather
than the wished-for one, exactly as `sandbox_bypass` does; and it turns "dedicated"
from prose in a runbook into a cell in the console. A visible ⚠ gets asked about; a
runbook sentence does not. `agentd doctor` prints the same line, before enrollment.

**Mount namespaces are not introduced**, and the reason is not effort: they need
unprivileged user namespaces, which is a node-level kernel setting, and
"use it if present" is a half-guarantee; they would hide `~/.claude`, `~/.codex`,
`~/.gitconfig` and `~/.ssh`, which the runtimes need, so avoiding that means a
per-node mount list to maintain; and `codex exec -s workspace-write` already
provides a real sandbox (landlock) scoped to the run directory on that one path —
**which the runtime gives, not the platform**, so it is a side benefit rather than
a promise.

### 7. Changes are never silently discarded

If `delivery ∈ {none, artifact}` and `git status --porcelain` is non-empty when the
run ends, the daemon writes `git diff` to `artifacts/changes-<run_id>.patch`,
uploads it as an artifact, and records in the run summary: *this card declared no
delivery, but N files changed; the diff is attached.*

This honesty rule was scheduled for V2.4, when `delivery` gains behaviour. The
ruling made it necessary now: a run really does pull code and really does change
files, and the run directory expires. Without the artifact, that work disappears
after three days **and nobody knows it ever existed**.

The second ruling narrows where it applies without removing it: an agent that
pushed a branch has not lost its work, an agent that did not still will, and the
platform cannot tell the two apart. So the rule is unconditional, and the unpushed
commit count from §5 point four goes into the summary so a person can tell.

`git diff` covers tracked modifications only. Untracked files are **counted and
not packaged** — the `??` line count goes into the summary with "N further
untracked files were not attached", because one `node_modules/` would blow the
quota. Whether to keep them is a person's call.

## Consequences

- A new filesystem surface exists on every runner node, and disk is the resource it
  consumes. Quotas and the cleanup loop are the whole defence; **M11 and M12 are
  measured before `AR-07b` starts**, because a quota chosen without them is a
  guess, and the failure mode is a full disk that also stops interactive sessions.
- Mirrors mean the second run of a repository is much cheaper than the first, and
  it also means a cache with locking and corruption modes to own. **Whether the
  mirror layer is worth it at all is an open measurement (M11)**: if a shallow
  clone of a repository the size of Traqora is fast enough, the mirror is an
  unnecessary cache. This sentence is deliberately in the ADR, not only in the plan.
- An agent can read the interactive workspaces on a mixed-use node. This is
  reported, not prevented, and §6 is the whole of the platform's answer.
- An agent can push with the machine's credentials. This is chosen, reported at
  the end of each run, and bounded by the node's posture rather than by code.
- One more prerequisite for a runner node: `git` on `PATH`.

## Alternatives rejected

| Rejected | Why |
|---|---|
| A run directory inside an allowed root | The two authorization models would interconnect: the agent's intermediate files appear in the user's file browser, and the user's `filesystem.store` can write into the run directory |
| `RuntimeDirectory` (`/run/agentd`) | tmpfs — it does not survive a reboot, and a failed run's directory must last 14 days |
| A Go git library | mirror and worktree are its weakest area, and the agent uses real `git` anyway, so two implementations would see different states |
| A full clone every run, no mirror | **Not rejected — pending measurement.** If M11 says a shallow clone is fast enough at Traqora's size, the mirror is a cache nobody needed |
| A token inside the remote URL | It surfaces in `git remote -v`, the reflog and error messages. The URL is stored in three columns so userinfo cannot be represented |
| Removing `origin` after clone | Withdrawn by the second ruling of 2026-08-10: it breaks fetch and pull along with the push that is now permitted. Observability replaced it |
| Recommending read-only git credentials on runner nodes | Withdrawn by the same ruling. The runbook says instead: whatever this machine can reach, the agent can reach — so a runner node should be dedicated |
| Removing the agent's shell access to stop it pushing | That degrades autonomous execution back into an interactive session (D25). This phase constrains how output leaves, not what happens inside |
| A mount namespace or bubblewrap | Needs unprivileged user namespaces (a node kernel setting), hides the CLI config the runtimes need, and would be a half-guarantee reported as a whole one. Open an ADR if a platform-level enforcement is genuinely needed; its first question is how it relates to D25 |
| Testing "the run process cannot read an allowed root" | On an ordinary machine that read **succeeds**. It was an assertion written wrong, not a test that would catch a bug |
