# Runbook — task context in a session

Covers the second path by which the platform writes to a node (ADR 0028, `plan/17`),
and the credential that travels with it. The first path is image drop
(`image-drop.md`); the two are **disjoint by construction** — neither can write where
the other may.

## What it does

When a session is created inside a project, Central makes a **second** round trip — after
the session is already running — and the daemon writes:

```text
<workspace>/.cliora/context/<session id>.md      the task context pack, ≤ 4 KB
<workspace>/.cliora/context/<session id>.token   the session credential
<workspace>/.cliora/process/<version>/process.md the lanes, readiness items and gates
```

All at mode `0600`, none ever overwriting anything. `.cliora/.gitignore` (`*`) is
written when absent, so nothing here shows up in the user's `git status`.

The agent reads them through `cliora`, which is the same binary as `agentd`.

## The first three things to check

**"The session has no context."** Expected, and not an error, in three cases:

| Cause | How to tell | Fix |
|---|---|---|
| The node runs agentd < 0.8.0 | `nodes.context_projection = false`; the console says which version is needed | Update the node the usual way (`update-failure.md` if it goes wrong) |
| The session belongs to no project | `terminal_sessions.project_id IS NULL` | Nothing to fix — an ad-hoc session has no card |
| `CLIORA_PROJECTS_ENABLED=false` | No project routes exist at all | Nothing to fix |

**A failed projection never fails a session.** If the round trip timed out or the node
refused, the session is running normally and the timeline carries a
`session.started` row whose payload names `context_projection`. The console offers a
retry. Investigate with:

```sql
SELECT payload FROM activity_events
WHERE session_id = '<id>' AND kind = 'session.started';
```

**"The agent says it cannot record anything."** Almost always the credential rather than
the projection. It is revoked the moment the session ends, and expires after
`CLIORA_SESSION_TOKEN_TTL_H` (default 24) regardless:

```sql
SELECT issued_at, expires_at, revoked_at, last_used_at
FROM session_tokens WHERE session_id = '<id>';
```

A revoked or expired credential answers 401, and `cliora` says so in one sentence. What
it must **not** do is stop the agent working — `cliora context show` reads a local file
and never dials, so the agent still knows what it is doing when Central is down.

## What you cannot do from here

- **You cannot read a credential.** Only its HMAC is stored, by construction. If one is
  suspected of leaking, revoke it — ending the session does that — and the projection
  files become inert strings.
- **You cannot make the platform write anywhere else.** The wire schema admits only
  `.cliora/{context,process,reference}/`; a path outside them is unrepresentable rather
  than refused, and the daemon re-checks anyway.

## Retention

The daemon prunes `context/`, `process/` and `reference/` after 30 days. It **does not
touch** `.cliora/uploads/` (image drop's area, with its own retention) or
`.cliora/.gitignore` (which the user may own). Expiry is not breakage: the session keeps
working, and only `cliora context show` notices.

Revoked credential rows are kept 90 days, because the audit trail names a token id and
that name has to stay resolvable.

## Related

`image-drop.md` (the other write path), `file-upload.md`,
`docs/security-review-v21.md` (what a leaked credential can and cannot do),
ADR 0024/0026/0028.
