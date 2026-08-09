"""Deterministic PostgreSQL schema snapshot (plan/16 PJ-00 B2, exit condition 7).

`pg_dump --schema-only` is what plan/16/01-…md §2 asks for, but no PostgreSQL client
is installed on this machine and installing one needs root. This produces the same
*decision* — "did any existing table change, column by column" — by reflecting the
live schema through SQLAlchemy and printing it in a stable order.

It is arguably the better instrument for this particular gate: `pg_dump` output also
carries extension/owner/ACL noise that has to be filtered before a diff means
anything, while every line here is a fact the exit condition actually names.

    python scripts/pj/schema_snapshot.py > artifacts/pj/local/baseline/schema.txt
    python scripts/pj/schema_snapshot.py --diff artifacts/pj/local/baseline/schema.txt

Exit code 1 on a diff, so it can be a gate rather than a report.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import os
import sys
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_URL = "postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test"


def _render(inspector) -> list[str]:
    out: list[str] = []
    for table in sorted(inspector.get_table_names()):
        out.append(f"TABLE {table}")
        for column in sorted(inspector.get_columns(table), key=lambda c: c["name"]):
            # Deliberately including the server default: a changed default is exactly
            # the kind of silent alteration D12 forbids ("no existing column changes
            # type, nullability or default").
            default = column.get("default")
            out.append(
                f"  COLUMN {column['name']} "
                f"type={column['type']} "
                f"nullable={bool(column['nullable'])} "
                f"default={default!r}"
            )
        pk = inspector.get_pk_constraint(table)
        if pk.get("constrained_columns"):
            out.append(f"  PK ({', '.join(pk['constrained_columns'])})")
        for fk in sorted(
            inspector.get_foreign_keys(table),
            key=lambda f: (f.get("name") or "", tuple(f["constrained_columns"])),
        ):
            opts = fk.get("options") or {}
            out.append(
                f"  FK ({', '.join(fk['constrained_columns'])}) -> "
                f"{fk['referred_table']}({', '.join(fk['referred_columns'])}) "
                f"ondelete={opts.get('ondelete')}"
            )
        for uq in sorted(inspector.get_unique_constraints(table), key=lambda u: u["name"] or ""):
            out.append(f"  UNIQUE {uq['name']} ({', '.join(uq['column_names'])})")
        for ix in sorted(inspector.get_indexes(table), key=lambda i: i["name"] or ""):
            cols = ", ".join(c or "?" for c in ix["column_names"])
            unique = " UNIQUE" if ix.get("unique") else ""
            # Partial-index predicates live in dialect_options; they are load-bearing
            # here (one live shell per parent, one primary workspace per project).
            where = (ix.get("dialect_options") or {}).get("postgresql_where")
            where = f" WHERE {where}" if where else ""
            out.append(f"  INDEX{unique} {ix['name']} ({cols}){where}")
    return out


async def _snapshot(url: str) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            lines = await conn.run_sync(lambda sync_conn: _render(inspect(sync_conn)))
            revision = (await conn.execute(text("select version_num from alembic_version"))).scalar()
    finally:
        await engine.dispose()
    return [f"# alembic revision: {revision}", *lines]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("CLIORA_DATABASE_URL", DEFAULT_URL))
    parser.add_argument("--diff", type=Path, help="compare against a saved snapshot")
    args = parser.parse_args()

    lines = asyncio.run(_snapshot(args.url))

    if args.diff is None:
        print("\n".join(lines))
        return 0

    baseline = args.diff.read_text(encoding="utf-8").splitlines()
    # The revision line is expected to move; it is the one line that *should* differ.
    delta = [
        line
        for line in difflib.unified_diff(
            baseline, lines, fromfile=str(args.diff), tofile="live", lineterm=""
        )
    ]
    if not delta:
        print("schema unchanged")
        return 0
    print("\n".join(delta))
    added = sum(1 for line in delta if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in delta if line.startswith("-") and not line.startswith("---"))
    print(f"\n{added} added, {removed} removed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
