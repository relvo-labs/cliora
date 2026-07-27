"""Retention pruning for the audit trail and node metric samples (ADR 0016).

Deliberately an operator command, not a scheduled job. MVP ships no background
scheduler, and the audit trail is the one table where an unattended deletion is
worse than an oversized table: a mis-set schedule silently destroys the record of
what happened. So this runs when someone decides it should, after a backup, and
tells them exactly what it would remove before it removes anything.

    # what would be deleted (default; touches nothing)
    uv run --project backend python -m app.retention prune
    # actually delete
    uv run --project backend python -m app.retention prune --yes

See `docs/runbooks/backup-restore.md` — a current backup is a precondition.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text

from app.clock import now_utc
from app.db.engine import get_database
from app.settings import get_settings


@dataclass(frozen=True, slots=True)
class Target:
    table: str
    column: str
    days: int

    @property
    def label(self) -> str:
        return f"{self.table} older than {self.days} days"


def targets() -> list[Target]:
    settings = get_settings()
    return [
        Target("audit_logs", "created_at", settings.audit_retention_days),
        # Present from P4-06 onward; a missing table is reported, not fatal, so the
        # command works on a database that has not reached that migration.
        Target("node_metric_samples", "sampled_at", settings.node_metric_retention_days),
    ]


async def _table_exists(conn, table: str) -> bool:  # type: ignore[no-untyped-def]
    result = await conn.execute(
        text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{table}"}
    )
    return bool(result.scalar())


async def prune(*, apply: bool) -> int:
    """Report (and optionally delete) rows past their retention window.

    Returns the total number of rows matched. Cutoffs are computed from an aware
    UTC instant and compared against timezone-aware columns, so a server in any
    timezone prunes the same rows.
    """
    engine = get_database().engine
    now = now_utc()
    total = 0
    async with engine.begin() as conn:
        for target in targets():
            if not await _table_exists(conn, target.table):
                print(f"[skip] {target.table}: table not present at this migration level")
                continue
            cutoff = now - timedelta(days=target.days)
            counted = await conn.execute(
                text(f"SELECT count(*) FROM {target.table} WHERE {target.column} < :cutoff"),
                {"cutoff": cutoff},
            )
            rows = int(counted.scalar() or 0)
            total += rows
            verdict = "would delete" if not apply else "deleting"
            print(f"[{verdict}] {rows} row(s) — {target.label} (cutoff {cutoff.isoformat()})")
            if apply and rows:
                await conn.execute(
                    text(f"DELETE FROM {target.table} WHERE {target.column} < :cutoff"),
                    {"cutoff": cutoff},
                )
    if not apply:
        print("\nDry run: nothing was deleted. Re-run with --yes to apply.")
        print("Take a database backup first — see docs/runbooks/backup-restore.md.")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.retention")
    sub = parser.add_subparsers(dest="command", required=True)
    prune_cmd = sub.add_parser("prune", help="delete rows past their retention window")
    prune_cmd.add_argument(
        "--yes",
        action="store_true",
        help="actually delete (without this the command only reports)",
    )
    args = parser.parse_args(argv)
    if args.command == "prune":
        asyncio.run(prune(apply=args.yes))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
