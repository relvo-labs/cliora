#!/usr/bin/env python3
"""No response schema anywhere in the document can carry a secret's value.

`GATE-SC-NO-SECRET-IN-RESPONSE`, the static half of exit condition 1. The other half is
a sentinel value asserted absent from five real responses (`test_project_secrets.py`),
and the two catch different mistakes: this one catches a **future** endpoint that hands
back a whole row, that one catches a present endpoint whose schema is right and whose
implementation serialises a model directly.

**Responses only, and that distinction is the design.** A first version walked every
schema in the document and failed on `CreateProjectSecretRequest`, which of course
carries a value — it is the request that stores one. A guard that cannot tell a request
from a response would most cheaply be "fixed" by renaming the field somebody has to
type, which is worse than having no guard at all.

The scan resolves `$ref` transitively, so a response that merely nests a schema carrying
a value is caught too.
"""

from __future__ import annotations

import os
import sys

FORBIDDEN = {"value", "value_encrypted", "dek_wrapped", "plaintext", "secret_value"}


def refs(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for child in node.values():
            found |= refs(child)
    elif isinstance(node, list):
        for child in node:
            found |= refs(child)
    return found


def main() -> int:
    # Both flags on, because a route mounted behind a disabled flag is still in the
    # document — and a guard that only looked at one deployment's document would be
    # answering a narrower question than it appears to.
    os.environ.setdefault("CLIORA_PROJECTS_ENABLED", "true")
    os.environ.setdefault("CLIORA_AGENT_RUNS_ENABLED", "true")
    os.environ.setdefault(
        "CLIORA_SECRET_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    )
    sys.path.insert(0, "backend")
    from app.main import app

    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})

    reachable: set[str] = set()
    for operations in spec.get("paths", {}).values():
        for operation in operations.values():
            if isinstance(operation, dict):
                reachable |= refs(operation.get("responses", {}))
    frontier = set(reachable)
    while frontier:
        nxt: set[str] = set()
        for name in frontier:
            for candidate in refs(schemas.get(name, {})) - reachable:
                reachable.add(candidate)
                nxt.add(candidate)
        frontier = nxt

    leaked = sorted(
        f"{name}.{field}"
        for name in reachable
        for field in FORBIDDEN & set(schemas.get(name, {}).get("properties") or {})
    )
    if leaked:
        print(f"a response schema exposes {leaked}", file=sys.stderr)
        return 1
    # Not vacuous: the guard has to have actually reached the DTO it is guarding.
    if "ProjectSecretDTO" not in reachable:
        print(
            "the scan never reached ProjectSecretDTO; it is checking nothing",
            file=sys.stderr,
        )
        return 1
    print(f"no secret in any response ({len(reachable)} response schemas scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
