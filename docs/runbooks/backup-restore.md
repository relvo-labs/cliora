# Runbook — backup, restore and retention pruning

Covers the PostgreSQL backup/restore drill and the retention command that depends
on it. Owner: platform operator. Related: ADR 0016 (retention),
`scripts/p4/backup-restore-drill.sh` (the automated drill), `docs/deployment.md`
(deployment, upgrade and rollback).

## What is in the database — and what is deliberately not

| Present | Absent by design |
|---|---|
| users, roles and their permission sets | terminal input/output bytes (ADR 0004) |
| nodes, runtimes, workspace roots, credentials (public keys / hashes only) | file contents, directory listings, search keywords |
| terminal **session metadata** (status, timings, exit code) | plaintext enrollment tokens or passwords (hashed only) |
| audit trail (minimized, redacted metadata) | Ed25519 private keys (they never leave the node) |
| node metric samples (from P4-06) | |

A restored database therefore reproduces the control plane and the audit trail,
never the content of anyone's terminal or files. **Verifying that is part of the
drill**, not an assumption: the drill scans the dump itself for ANSI-escape-dense
runs, JWT shapes, bearer tokens, connection strings with credentials, private-key
headers and the seeded plaintext password.

It also scans in the *other* direction — asserting the dump does contain this
deployment's data — because otherwise every clean result above would be equally
satisfied by an empty file.

## Automated drill

```bash
scripts/p4/backup-restore-drill.sh [output-dir]     # default artifacts/p4/local
```

Runs the whole cycle against **two throwaway databases** and never touches a shared
one. Writes `backup-restore.md` with the exact commands, versions, timings, row
counts and scan results, and exits non-zero if any check failed. Beyond the leakage
scan it verifies:

* row counts and content for every table that matters — *and* that the source
  actually had rows in each, since the counts are captured after seeding and a
  half-failed seed would otherwise make every comparison pass against zero;
* all three roles with their full action lists (a count cannot catch a restore that
  brought back the rows but flattened `permissions`);
* `alembic current` on the restored database equals head;
* Central starts against the restored database, reports ready, **and** the restored
  admin credential still authenticates.

Run it after any schema change and after any change to the backup procedure.

## Backup

```bash
pg_dump --format=custom --no-owner --file=cliora-$(date -u +%Y%m%dT%H%M%SZ).dump "$CLIORA_DATABASE_URL_LIBPQ"
```

Record the `pg_dump` version alongside the file: a dump is only restorable by an
equal or newer server. Store it where the platform host cannot delete it.

## Restore

1. Create an **empty** target database — never restore over a live one.
2. `pg_restore --no-owner --dbname=<target> <dump>`
3. Confirm the schema is at the expected revision:
   `alembic current` must equal `alembic heads`.
4. Point a Central instance at the restored database and check `/readyz` reports
   `{"status":"ready","database":true,"migration":true}`. A `degraded` answer with
   `migration:false` means the dump predates the code — migrate forward before
   serving traffic.
5. Spot-check the three roles still hold their documented actions
   (`docs/permission-matrix.md`) and that the audit trail's newest row is as
   recent as expected.

## Retention pruning

Expiry is **an operator command, never a scheduled job** (ADR 0016). A mis-set
schedule silently destroys the record of what happened, which is worse than an
oversized table.

```bash
# 1. Take a backup first. This is a precondition, not advice.
# 2. See what would go (default; deletes nothing):
uv run --project backend python -m app.retention prune
# 3. Apply:
uv run --project backend python -m app.retention prune --yes
```

Windows come from settings, so they are reviewable and overridable per
deployment:

| Setting | Default | Table |
|---|---:|---|
| `CLIORA_AUDIT_RETENTION_DAYS` | 365 | `audit_logs` |
| `CLIORA_NODE_METRIC_RETENTION_DAYS` | 30 | `node_metric_samples` |

Cutoffs are computed from an aware UTC instant against timezone-aware columns, so
the same rows are selected regardless of the server's local timezone. A table that
does not exist yet at the current migration level is reported and skipped rather
than failing the run.

## Symptoms → action

| Symptom | Action |
|---|---|
| `/readyz` shows `migration:false` after a restore | Run `alembic upgrade head` against the restored database before serving traffic |
| Audit table growing faster than expected | Check `authz.denied` and `user.login_failed` volume first — a spike is a security signal, not a capacity problem. Investigate before pruning |
| `audit_error_total > 0` | The audit chain is failing: accountability is broken while it lasts. Treat as critical (ADR 0018), check database connectivity and disk, and do **not** prune until it is resolved |
| Prune reports far more rows than expected | Stop. Confirm the retention setting and that the backup exists before passing `--yes` |
| Nodes stay offline after a restore | `CLIORA_TOKEN_PEPPER` differs from the value the credentials were created under. The credentials cannot be recovered — every node must re-enroll. Store the pepper alongside the dumps: it is the one value that makes them useful |
| Roles show fewer actions than expected | The restore was partial, or the seed migration ran against an already-populated database. Restore again into a fresh, empty database; do not repair `roles.permissions` by hand |
| A dump will not restore at all | `pg_dump` was newer than the target server. Restore into a server at or above the dump's version — which is why the `pg_dump` version is recorded next to the file |

## After any restore or prune

Record in the incident/maintenance log: what was restored or pruned, the dump
used, row counts before and after, and who authorised it. A retention run that
nobody can account for is indistinguishable from tampering.
