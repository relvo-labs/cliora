#!/usr/bin/env python
"""`GATE-PX-JOURNEY-COVERAGE` — the six journeys ran, on this code, and said yes.

`plan/26/10` §3 calls this **the phase's most likely false green**, and quotes `plan/24`
for the shape of it: six journeys all skip, the suite reports success, and the release
ships having demonstrated nothing. That is not a hypothetical here — `evidence.sh`
printed three `SKIP` lines for weeks, and the reason attached to them was false.

So this checks three things, and the third is the one a `SKIP` count cannot:

1. **every journey left evidence** — `j{1,4,15}.json` from the daemon runs,
   `j{2,10,16}-*.png` from the browser ones. A missing file is a failure that names the
   command that produces it, never a silent omission;
2. **every assertion inside a verdict passed.** Not the top-level `verdict` field: a
   journey that finished with 8 of 12 writes `verdict: "FAIL"` *and* a JSON somebody can
   still read as "it ran". The check is per-assertion;
3. **the evidence is about this code.** Two checks, because one commit stamp cannot carry
   the whole claim.

On (3), the commit half: a journey stamps the commit it ran at, and normal work — writing
this gate, editing a plan — moves `HEAD` afterwards. Requiring equality would mean
re-running three daemon journeys after every documentation commit, and a gate that is
expensive to satisfy honestly is a gate people satisfy dishonestly. So a stamp is accepted
when it is an **ancestor of HEAD** *and* nothing the journey exercises has changed since:
`backend/app`, `frontend/src`, `daemon/` and `scripts/px/journeys/`. Docs and plans may
move; code may not.

And the half a commit stamp **cannot** carry: while a phase is in progress everything is
uncommitted, so the stamp equals `HEAD` no matter how much the working tree has moved
since the journey ran. A gate that stopped there would report green for a journey run
before the code it is supposed to cover was written — which is this gate's own failure
mode, one step in. So the timestamps are compared too: **no file under `CODE_PATHS` may be
newer than the journey that claims to cover it.** That works on an uncommitted tree, which
is exactly where the commit check goes blind.

Run: uv run --project backend python scripts/px/gate_journey_coverage.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "artifacts/px/local/journeys"

#: The three that need a daemon. Each writes one JSON with a per-assertion list.
DAEMON_JOURNEYS = {
    "j1": "the main journey — 模糊需求 → Done, no terminal (**non-degradable**)",
    "j4": "My Work → answer and continue → the turn reads it",
    "j15": "no eligible runner → the missing tag is named → fixed → claimed",
}

#: The three that are browser-level. Each leaves screenshots.
BROWSER_JOURNEYS = {
    "j2": "Backlog → Ready, warnings and all",
    "j10": "filter and scroll survive the Drawer; back unwinds in order",
    "j16": "the flag matrix, both halves",
}

#: What each kind of journey actually exercises. **Split by kind, not one list**: J1, J4
#: and J15 drive HTTP and a real daemon and never open a browser, so a change under
#: `frontend/src` cannot invalidate them — and a gate that said it did would demand three
#: daemon re-runs for a CSS edit. Being over-strict is not the safe direction: it is how a
#: gate becomes something people disable.
#: Shared by all three daemon journeys. `px_harness.py` is here because every one of them
#: imports it; the individual `j*_*.py` files are **not**, and that is the point — editing
#: J4's script must not invalidate J1's verdict. Each journey's own file is added per
#: journey below.
DAEMON_CODE_PATHS = (
    "backend/app",
    "daemon",
    "scripts/px/journeys/px_harness.py",
    "scripts/cv/journeys/harness.py",
)
#: The browser journeys live in **one** spec file, so that file plus the app is what they
#: depend on. `frontend/tests/px` as a whole would mean editing `wave5.spec.ts` invalidates
#: J16's screenshots — the same over-strictness the daemon list above avoids, and the gate
#: reported exactly that the first time this list was too coarse.
BROWSER_CODE_PATHS = (
    "frontend/src",
    "backend/app",
    "frontend/tests/px/journeys.spec.ts",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


#: Directories inside `CODE_PATHS` whose contents are build output rather than source.
#: `node_modules` alone makes the newest-file scan meaningless — an `npm install` would
#: invalidate every journey.
_IGNORED_DIRS = {"node_modules", "__pycache__", ".venv", "dist", "bin"}


def _newest_code_change(roots: tuple[str, ...]) -> tuple[float, pathlib.Path] | None:
    """The most recently modified source file, and when.

    Modification time rather than git status, because during a phase everything is
    uncommitted and `git status` says only *that* a file changed, never *when* relative to
    a journey run.
    """
    newest: tuple[float, pathlib.Path] | None = None
    for root in roots:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix in {".pyc", ".log"}:
                continue
            if _IGNORED_DIRS & set(path.parts):
                continue
            stamp = path.stat().st_mtime
            if newest is None or stamp > newest[0]:
                newest = (stamp, path)
    return newest


def main() -> int:
    problems: list[str] = []
    head = _git("rev-parse", "HEAD")
    if not head:
        print("GATE-PX-JOURNEY-COVERAGE: FAIL — not a git checkout")
        return 1
    shared_newest = _newest_code_change(DAEMON_CODE_PATHS)
    if shared_newest is not None:
        print(
            f"        newest shared change: "
            f"{datetime.fromtimestamp(shared_newest[0], tz=timezone.utc).isoformat(timespec='seconds')}"
            f"  {shared_newest[1].relative_to(REPO)}"
        )

    for name, title in DAEMON_JOURNEYS.items():
        path = EVIDENCE / f"{name}.json"
        if not path.exists():
            problems.append(
                f"{name} has no verdict — run: E2E_RUNNER=1 CLIORA_DATABASE_URL=… "
                f"scripts/e2e/run-stack.sh uv run --project backend python "
                f"scripts/px/journeys/{name}_*.py  ({title})"
            )
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as bad:
            problems.append(f"{name}.json is not readable JSON: {bad}")
            continue

        checks = data.get("checks")
        if not isinstance(checks, list) or not checks:
            problems.append(f"{name}.json carries no assertions, so it proves nothing")
            continue
        failed = [
            str(check.get("claim", "?")) for check in checks if not check.get("ok")
        ]
        if failed:
            problems.append(
                f"{name}: {len(failed)}/{len(checks)} assertions failed — first: {failed[0]}"
            )
            continue

        # The shared code, plus **this** journey's own script and nothing else's.
        own = sorted((REPO / "scripts/px/journeys").glob(f"{name}_*.py"))
        newest = shared_newest
        for script in own:
            stamp_time = script.stat().st_mtime
            if newest is None or stamp_time > newest[0]:
                newest = (stamp_time, script)

        stamp = str(data.get("commit") or "")
        if not stamp:
            problems.append(f"{name}.json does not stamp the commit it ran against")
        elif stamp != head:
            # An ancestor is fine; a divergent or unknown commit is not.
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", stamp, head],
                cwd=REPO,
                capture_output=True,
                check=False,
            )
            if ancestor.returncode != 0:
                problems.append(
                    f"{name} ran at {stamp[:12]}, which is not an ancestor of HEAD — "
                    f"the evidence is about code this checkout does not contain"
                )
            else:
                changed = _git(
                    "diff", "--name-only", stamp, "HEAD", "--", *DAEMON_CODE_PATHS
                )
                if changed:
                    first = changed.splitlines()[0]
                    problems.append(
                        f"{name} ran at {stamp[:12]} and code has changed since "
                        f"({len(changed.splitlines())} file(s), e.g. {first}) — re-run it"
                    )
        # The half the commit stamp cannot carry: was the code edited *after* this ran?
        recorded = str(data.get("recorded_at") or "")
        if not recorded:
            problems.append(f"{name}.json does not record when it ran")
        elif newest is not None:
            try:
                ran_at = datetime.fromisoformat(recorded).timestamp()
            except ValueError:
                problems.append(
                    f"{name}.json has an unreadable `recorded_at`: {recorded}"
                )
            else:
                if newest[0] > ran_at:
                    problems.append(
                        f"{name} ran at {recorded[:19]} and "
                        f"{newest[1].relative_to(REPO)} changed after it — the verdict is "
                        f"about code this checkout no longer has. Re-run it."
                    )
        print(f"        {name}: {len(checks)}/{len(checks)} at {stamp[:12] or '?'}")

    browser_newest = _newest_code_change(BROWSER_CODE_PATHS)
    for name, title in BROWSER_JOURNEYS.items():
        shots = sorted(EVIDENCE.glob(f"{name}-*.png"))
        if not shots:
            problems.append(
                f"{name} left no screenshots — run: E2E_PX_PROJECT=… npx playwright test "
                f"-c tests/px/playwright.config.ts tests/px/journeys.spec.ts  ({title})"
            )
            continue
        # A screenshot has no verdict inside it, so its mtime is the whole claim: it was
        # taken after the code it shows. Nothing else about a stale PNG looks stale.
        taken = max(shot.stat().st_mtime for shot in shots)
        if browser_newest is not None and browser_newest[0] > taken:
            problems.append(
                f"{name}'s screenshots predate "
                f"{browser_newest[1].relative_to(REPO)} — re-run the browser suite"
            )
        print(f"        {name}: {len(shots)} screenshot(s)")

    if problems:
        for problem in problems:
            print(f"  FAIL  {problem}")
        print("GATE-PX-JOURNEY-COVERAGE: FAIL")
        return 1
    print("GATE-PX-JOURNEY-COVERAGE: OK (6 journeys, every assertion, on this code)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
