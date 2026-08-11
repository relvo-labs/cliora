"""The frontend route table, as a three-column text snapshot (plan/18 AR-00).

Criterion 14 asserts a **negative** proposition — "no path inside the application
origin renders an artifact" — and a negative proposition can only be proved against
an enumeration. `openapi.json` enumerates the server half; this enumerates the
browser half. Together they are the two machine assertions that stand in for a claim
no test can make directly (`plan/18/00-…md` D14).

Static extraction rather than importing the module: `router/index.ts` reaches for
`vue-router`, Pinia and every view component, so importing it needs the whole Vite
graph, and a snapshot instrument that can only run inside the app's build is one
more thing that can break for reasons unrelated to what it measures. Every `path`,
`name` and `component` in that file is a literal, so reading them is honest.

The guard against a silent miss is a count: every `path:` in the file must end up in
exactly one record. A refactor into a shape this cannot read fails loudly instead of
quietly emitting a shorter list — which, for a negative proposition, is the one
failure mode that matters.

    python scripts/ar/frontend_routes.py > artifacts/ar/local/baseline/frontend-routes.txt
    python scripts/ar/frontend_routes.py --diff artifacts/ar/local/baseline/frontend-routes.txt

Exit code 1 on a diff, so it can be a gate rather than a report.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "frontend/src/router/index.ts"

# One record per `{ … }` that carries a `path:`. Non-greedy up to the first `}` that
# starts a line at the object's own indentation, or — for the one-liners — the first
# `}` on the same line.
_RECORD = re.compile(r"\{[^{}]*\bpath:[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
_PATH = re.compile(r"\bpath:\s*\"([^\"]*)\"")
_NAME = re.compile(r"\bname:\s*\"([^\"]*)\"")
_COMPONENT = re.compile(r"\bcomponent:\s*\(\)\s*=>\s*import\(\s*\"([^\"]*)\"\s*\)")
_REDIRECT = re.compile(r"\bredirect:\s*\{\s*name:\s*\"([^\"]*)\"")


def _dev_only_span(text: str) -> tuple[int, int]:
    """Character range of the `if (import.meta.env.DEV) { … }` block, if present.

    A route that only exists in a dev build is not part of the application origin an
    operator deploys, and criterion 14 is about the deployed origin. Marking it is
    more useful than omitting it: an omitted route looks like the extractor missed
    something, and this list exists to prove nothing was missed.
    """
    marker = "if (import.meta.env.DEV) {"
    start = text.find(marker)
    if start < 0:
        return (-1, -1)
    depth = 0
    for index in range(start + len(marker) - 1, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return (start, index)
    return (start, len(text))


def _records(text: str) -> list[tuple[str, str, str]]:
    dev_start, dev_end = _dev_only_span(text)
    out: list[tuple[str, str, str]] = []
    for match in _RECORD.finditer(text):
        block = match.group(0)
        path = _PATH.search(block)
        if path is None:  # pragma: no cover - _RECORD requires a `path:`
            continue
        redirect = _REDIRECT.search(block)
        # `redirect: { name: … }` names the *destination*, not this route. Searching
        # the whole block for `name:` would report every redirect as a named route.
        outer = re.sub(r"\bredirect:\s*\{[^{}]*\}", "", block)
        name = _NAME.search(outer)
        component = _COMPONENT.search(block)
        if component is not None:
            target = component.group(1)
        elif redirect is not None:
            # A redirect renders nothing of its own. Recorded as such rather than
            # omitted: criterion 14 cares about which paths can render, and "this one
            # cannot" is part of that answer.
            target = f"(redirect → {redirect.group(1)})"
        else:
            target = "(none)"
        if dev_start <= match.start() < dev_end:
            target += "  [dev-only build]"
        out.append((path.group(1), name.group(1) if name else "(unnamed)", target))
    return out


def _render(records: list[tuple[str, str, str]]) -> str:
    return "".join(
        f"{path}\t{name}\t{component}\n" for path, name, component in sorted(records)
    )


def _snapshot() -> str:
    text = SOURCE.read_text()
    records = _records(text)
    declared = len(re.findall(r"\bpath:\s*\"", text))
    if len(records) != declared:
        raise SystemExit(
            f"{SOURCE.relative_to(REPO)}: parsed {len(records)} route records but the file "
            f"declares {declared} `path:` keys. The route table changed shape; this "
            f"extractor has to be taught the new shape before its output means anything."
        )
    return _render(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", type=Path, help="compare against a captured baseline")
    args = parser.parse_args()

    live = _snapshot()
    if args.diff is None:
        sys.stdout.write(live)
        return 0

    baseline = args.diff.read_text()
    if baseline == live:
        print(f"frontend routes unchanged: {len(live.splitlines())} routes")
        return 0
    sys.stdout.writelines(
        difflib.unified_diff(
            baseline.splitlines(keepends=True),
            live.splitlines(keepends=True),
            fromfile=str(args.diff),
            tofile="live",
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
