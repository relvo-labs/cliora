"""Compare the live OpenAPI document against the pre-V2 baseline (plan/16 PJ-07).

"The API surface did not change" is the flag-off promise, and `openapi.json` is
several thousand lines — so it has to be a machine's job. What this enforces is
narrower than "no diff", because two kinds of addition are unavoidable and safe:

**Allowed**
  * a new path (which must answer 404 while the flag is off — asserted separately,
    by `test_every_project_route_is_404_while_the_flag_is_off`);
  * a new **optional** field on an existing request or response.

**Refused**
  * a removed or renamed field, a changed type, or a field that became required —
    each of these breaks a client that predates it;
  * a removed path.

The distinction matters because the OpenAPI document is static: `project_id` appears
on `CreateSessionRequest` whichever way the feature flag is set, since the schema is
built from the Pydantic model rather than from configuration. The runtime refusal is
what makes the flag real, and this check is what proves the refusal did not come at
the cost of the contract.

    python scripts/pj/openapi_diff.py --baseline artifacts/pj/local/baseline/openapi.json

Exit code 1 on a refused change, so it can be a gate rather than a report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]


def _live_schema() -> dict[str, Any]:
    sys.path.insert(0, str(REPO / "backend"))
    from app.main import app

    return app.openapi()


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    return document.get("components", {}).get("schemas", {})


def _properties(schema: dict[str, Any]) -> dict[str, Any]:
    return schema.get("properties", {})


def _type_of(prop: dict[str, Any]) -> str:
    """A comparable shape string.

    Deliberately coarse: what has to be caught is `str` becoming `int` or an object
    losing a member, not every way OpenAPI can spell a union. Over-precision here
    would produce diffs on formatting changes and train people to ignore the gate.
    """
    if "$ref" in prop:
        return f"ref:{prop['$ref']}"
    if "anyOf" in prop:
        return "anyOf:" + ",".join(sorted(_type_of(entry) for entry in prop["anyOf"]))
    if "allOf" in prop:
        return "allOf:" + ",".join(sorted(_type_of(entry) for entry in prop["allOf"]))
    kind = prop.get("type", "unknown")
    if kind == "array":
        return f"array<{_type_of(prop.get('items', {}))}>"
    return str(kind)


def compare(baseline: dict[str, Any], live: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Returns (refused, allowed)."""
    refused: list[str] = []
    allowed: list[str] = []

    base_paths, live_paths = set(baseline.get("paths", {})), set(live.get("paths", {}))
    for path in sorted(base_paths - live_paths):
        refused.append(f"path removed: {path}")
    for path in sorted(live_paths - base_paths):
        allowed.append(f"path added: {path}")

    for path in sorted(base_paths & live_paths):
        base_ops = set(baseline["paths"][path])
        live_ops = set(live["paths"][path])
        for method in sorted(base_ops - live_ops):
            refused.append(f"operation removed: {method.upper()} {path}")
        for method in sorted(live_ops - base_ops):
            allowed.append(f"operation added: {method.upper()} {path}")

    base_schemas, live_schemas = _schemas(baseline), _schemas(live)
    for name in sorted(set(base_schemas) - set(live_schemas)):
        refused.append(f"schema removed: {name}")
    for name in sorted(set(live_schemas) - set(base_schemas)):
        allowed.append(f"schema added: {name}")

    for name in sorted(set(base_schemas) & set(live_schemas)):
        base, live_schema = base_schemas[name], live_schemas[name]
        base_props, live_props = _properties(base), _properties(live_schema)

        for field in sorted(set(base_props) - set(live_props)):
            refused.append(f"field removed: {name}.{field}")

        base_required = set(base.get("required", []))
        live_required = set(live_schema.get("required", []))
        for field in sorted(live_required - base_required):
            # Newly required breaks every existing caller, whether the field is new
            # or not — so this is refused even for a field that was just added.
            refused.append(f"field became required: {name}.{field}")

        for field in sorted(set(live_props) - set(base_props)):
            if field in live_required:
                continue  # already reported above
            allowed.append(f"optional field added: {name}.{field}")

        for field in sorted(set(base_props) & set(live_props)):
            before, after = _type_of(base_props[field]), _type_of(live_props[field])
            if before != after:
                refused.append(f"type changed: {name}.{field}: {before} -> {after}")

    return refused, allowed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, default=REPO / "artifacts/pj/local/baseline/openapi.json"
    )
    parser.add_argument("--quiet", action="store_true", help="print refused changes only")
    args = parser.parse_args()

    if not args.baseline.exists():
        print(f"no baseline at {args.baseline} — capture one before changing the API", file=sys.stderr)
        return 2

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    refused, allowed = compare(baseline, _live_schema())

    if allowed and not args.quiet:
        print(f"allowed ({len(allowed)}):")
        for line in allowed:
            print(f"  + {line}")
    if refused:
        print(f"\nREFUSED ({len(refused)}):")
        for line in refused:
            print(f"  ! {line}")
        return 1
    print(f"\nno refused changes ({len(allowed)} additive)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
