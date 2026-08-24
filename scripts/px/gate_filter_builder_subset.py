#!/usr/bin/env python
"""`GATE-PX-BUILDER-SUBSET` — the filter builder cannot construct a filter the server refuses.

The builder is TypeScript and the allowlist is Python, so nothing in either language can
notice them drifting. The failure that produces is specific and bad: a dropdown that
returns **400 from a control the person was invited to use**. Not a crash, not a blank
screen — a validation error about a field name they never typed.

So this reads `frontend/src/modules/work/filterBuilder.ts` and checks every `(field, op,
value)` triple it can produce against `services/work/filters.FIELDS`:

1. every field the builder offers is a field the compiler accepts;
2. every operator it offers for that field is in that field's `ops`;
3. every value it offers is in that field's closed value set — or, for `is_blocked`, is
   one of the two booleans.

**Parsed, not imported.** There is no JS runtime in this gate's environment, and shelling
out to one would make a static check depend on `node_modules`. The file is written to be
readable: a `BUILDER_FIELDS` array of object literals with `field`, `ops` and `options`
keys, and the parser below refuses anything it cannot read rather than passing it — an
unparseable builder is not a passing builder.

Run: uv run --project backend python scripts/px/gate_filter_builder_subset.py
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.services.work.filters import FIELDS  # noqa: E402

BUILDER = REPO / "frontend/src/modules/work/filterBuilder.ts"

#: The two aliases the builder uses for operator tuples, resolved before parsing. Kept as
#: a table rather than followed generically: a gate that evaluated arbitrary constant
#: expressions would be an interpreter, and an interpreter is a thing that can be wrong.
OP_ALIASES = {
    "EQUALITY": ("eq", "neq"),
    "ALL_OPS": ("eq", "neq", "in", "not_in"),
}

#: `is_blocked` is the one field whose on-screen values are not its stored values: the
#: `<select>` carries the strings `"true"`/`"false"` and `coerce()` turns them into
#: booleans on the way out. So its values are checked against the *boolean* field kind
#: rather than against a frozenset there is none of.
BOOLEAN_VALUES = {"true", "false"}


def _strip_comments(source: str) -> str:
    """Line and block comments out, offsets not preserved.

    Offsets do not matter here — nothing reports a line number from the stripped text —
    but string contents do, and a `//` inside a quoted label would be eaten by a naive
    strip. The builder's labels are Chinese and none contains `//` or `/*`; the assertion
    below (`no comment markers survive`) is what keeps that true rather than assumed.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


def _extract_array(source: str, name: str) -> str:
    """The bracketed body of `export const <name>: … = [ … ];`, by bracket depth."""
    match = re.search(rf"export const {name}[^=]*=\s*\[", source)
    if match is None:
        raise SystemExit(
            f"GATE-PX-BUILDER-SUBSET: FAIL — {name} not found in {BUILDER}"
        )
    start = match.end() - 1
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "[":
            depth += 1
        elif source[index] == "]":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index]
    raise SystemExit(f"GATE-PX-BUILDER-SUBSET: FAIL — {name} is not bracket-balanced")


def _parse_fields(body: str) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """One tuple per builder field. Raises rather than skipping anything unreadable."""
    out: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    # Each entry is `{ field: "x", label: "…", ops: …, options: [ … ] }`. Split on the
    # `field:` key rather than on braces, because `options` contains braces of its own.
    chunks = re.split(r"\bfield:\s*", body)[1:]
    for chunk in chunks:
        name_match = re.match(r'"([^"]+)"', chunk)
        if name_match is None:
            raise SystemExit("GATE-PX-BUILDER-SUBSET: FAIL — a field entry has no name")
        name = name_match.group(1)
        ops_match = re.search(r"ops:\s*([A-Z_]+|\[[^\]]*\])", chunk)
        if ops_match is None:
            raise SystemExit(f"GATE-PX-BUILDER-SUBSET: FAIL — {name} declares no ops")
        raw_ops = ops_match.group(1)
        if raw_ops in OP_ALIASES:
            ops = OP_ALIASES[raw_ops]
        elif raw_ops.startswith("["):
            ops = tuple(re.findall(r'"([a-z_]+)"', raw_ops))
        else:
            raise SystemExit(
                f"GATE-PX-BUILDER-SUBSET: FAIL — {name} uses an ops alias this gate "
                f"cannot resolve: {raw_ops}. Add it to OP_ALIASES."
            )
        options_match = re.search(r"options:\s*\[(.*?)\]", chunk, flags=re.DOTALL)
        if options_match is None:
            raise SystemExit(
                f"GATE-PX-BUILDER-SUBSET: FAIL — {name} declares no options"
            )
        values = tuple(re.findall(r'value:\s*"([^"]*)"', options_match.group(1)))
        if not values:
            raise SystemExit(f"GATE-PX-BUILDER-SUBSET: FAIL — {name} offers no values")
        out.append((name, ops, values))
    if not out:
        raise SystemExit(
            "GATE-PX-BUILDER-SUBSET: FAIL — BUILDER_FIELDS parsed as empty"
        )
    return out


def main() -> int:
    source = _strip_comments(BUILDER.read_text(encoding="utf-8"))
    assert "//" not in source.replace("https://", ""), (
        "a comment marker survived the strip; the parser below would read it as code"
    )
    problems: list[str] = []
    for name, ops, values in _parse_fields(_extract_array(source, "BUILDER_FIELDS")):
        spec = FIELDS.get(name)
        if spec is None:
            problems.append(
                f"`{name}` is offered by the builder and is not a filter field"
            )
            continue
        for op in ops:
            if op not in spec.ops:
                problems.append(
                    f"`{name}` is offered with `{op}`, which the compiler refuses "
                    f"(it accepts {sorted(spec.ops)})"
                )
        allowed = spec.values if spec.values is not None else None
        for value in values:
            if allowed is not None:
                if value not in allowed:
                    problems.append(
                        f"`{name} = {value}` is offered and is not in the server's value set"
                    )
            elif spec.kind == "bool":
                if value not in BOOLEAN_VALUES:
                    problems.append(
                        f"`{name} = {value}` is offered and is not a boolean"
                    )
            else:
                problems.append(
                    f"`{name}` has open values (kind={spec.kind}) and must not be in the "
                    f"builder — it needs a picker, not a dropdown"
                )
        print(f"        checked {name} ({len(ops)} ops, {len(values)} values)")

    if problems:
        for problem in problems:
            print(f"  FAIL  {problem}")
        print("GATE-PX-BUILDER-SUBSET: FAIL")
        return 1
    print("GATE-PX-BUILDER-SUBSET: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
