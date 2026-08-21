#!/usr/bin/env python
"""The three closeout gates for `v2.0.0-alpha.2` (`plan/24/08` §1).

    uv run --project backend python scripts/cv/gate_closeout.py [--baseline <commit>]

* `GATE-CE-NO-PRODUCT-DRIFT` — `backend/app/` and `frontend/src/` are unchanged against
  the closeout baseline **except** for the paths named in the waiver file. D68's whole
  point is that a red journey has exactly one possible cause; an unrecorded product edit
  puts a second one back.
* `GATE-CE-JOURNEY-COVERAGE` — all seven journeys ran, and **none of them was skipped**.
  This is the phase's most likely false green: every browser journey is behind an env
  var, `test.skip()` makes a skipped suite exit 0, and four of the seven are separate
  scripts that simply might not have been invoked.
* `GATE-CE-EVIDENCE-FRESH` — every evidence file was produced at the current commit. A
  number measured two commits ago, quoted as if it were this release's, is the failure
  `plan/23/10` §5 paid for once already.

Each prints what it honoured or found, because a gate whose output is only PASS/FAIL
teaches nothing the second time it fails.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WAIVERS = REPO / "scripts/cv/product-drift-waivers.txt"
EVIDENCE = REPO / "artifacts/cv/local"
JOURNEYS = EVIDENCE / "journeys"

#: The frozen trees. Not `backend/tests/` or `frontend/tests/`: a closeout phase's whole
#: output is tests and evidence, so freezing them would freeze the work itself.
FROZEN = ("backend/app", "frontend/src")

#: The seven journeys, and which artefact proves each one ran. The browser three land in
#: one playwright report; the four scripts each write their own file.
SCRIPT_JOURNEYS = ("j5-chaos", "j6-comments", "j8-concurrent", "j9-decision")
BROWSER_JOURNEYS = ("J1a", "J3", "J7")
PLAYWRIGHT_REPORT = REPO / "artifacts/cv/local/playwright.json"

failures: list[str] = []


def head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def waived() -> dict[str, str]:
    """`path → "ticket reason"`, from the file both this gate and the touch list read."""
    entries: dict[str, str] = {}
    if not WAIVERS.exists():
        return entries
    for line in WAIVERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) >= 2:
            entries[parts[0]] = " ".join(parts[1:])
    return entries


def changed_files(baseline: str) -> list[str]:
    diff = subprocess.run(
        ["git", "diff", "--name-only", baseline, "--", *FROZEN],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.split()
    # `git diff` cannot see a file that has never been added, and a new module in a
    # frozen tree is exactly the change this gate exists to catch (the lesson
    # `GATE-CV-TOUCH-LIST` learned in plan/23/10 §9.1).
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *FROZEN],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = [line[3:].strip() for line in status if line[:2].strip() == "??"]
    return sorted(set(diff) | set(untracked))


def check_no_product_drift(baseline: str) -> None:
    allowed = waived()
    offenders: list[str] = []
    for path in changed_files(baseline):
        if path in allowed:
            print(f"        waived: {path} ({allowed[path]})")
        else:
            offenders.append(path)
    if offenders:
        failures.append(
            "GATE-CE-NO-PRODUCT-DRIFT: product code changed with no waiver:\n  "
            + "\n  ".join(offenders)
            + f"\n  (add a line to {WAIVERS.relative_to(REPO)} naming the ticket and why,"
            " and record it in plan/24/10 §2)"
        )


def check_journey_coverage(commit: str) -> None:
    missing: list[str] = []
    for name in SCRIPT_JOURNEYS:
        path = JOURNEYS / f"{name}.json"
        if not path.exists():
            missing.append(f"{name}: no evidence file — the journey was never run")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("verdict") != "PASS":
            missing.append(f"{name}: verdict {payload.get('verdict')}")
        elif payload.get("commit") != commit:
            missing.append(
                f"{name}: measured at {str(payload.get('commit'))[:7]}, not HEAD"
            )
        else:
            checks = payload.get("checks", [])
            print(f"        {name}: {len(checks)} checks, all passed")

    if not PLAYWRIGHT_REPORT.exists():
        missing.append(
            "the browser journeys left no report — run the suite with "
            "`--reporter=json` into artifacts/cv/local/playwright.json"
        )
    else:
        report = json.loads(PLAYWRIGHT_REPORT.read_text(encoding="utf-8"))
        seen: dict[str, str] = {}
        for suite in report.get("suites", []):
            for spec in _specs(suite):
                for test in spec.get("tests", []):
                    for name in BROWSER_JOURNEYS:
                        if spec.get("title", "").startswith(f"{name}:"):
                            seen[name] = test.get("status", "unknown")
        for name in BROWSER_JOURNEYS:
            status = seen.get(name)
            if status is None:
                missing.append(f"{name}: not in the report — the spec never ran")
            elif status == "skipped":
                # The false green this gate exists for: playwright exits 0 for a suite
                # that skipped everything, so "the tests pass" and "the tests ran" are
                # different sentences.
                missing.append(f"{name}: **skipped** (E2E_CONVERSATION unset?)")
            elif status != "expected":
                missing.append(f"{name}: {status}")
            else:
                print(f"        {name}: ran and passed in the browser")
    if missing:
        failures.append("GATE-CE-JOURNEY-COVERAGE:\n  " + "\n  ".join(missing))


def _specs(suite: dict) -> list[dict]:
    specs = list(suite.get("specs", []))
    for nested in suite.get("suites", []):
        specs.extend(_specs(nested))
    return specs


def check_evidence_fresh(commit: str) -> None:
    stale: list[str] = []
    for path in sorted(EVIDENCE.rglob("*.json")):
        if path.name == "playwright.json":
            continue  # playwright's own schema, checked above by status instead
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            stale.append(f"{path.relative_to(REPO)}: unreadable ({error})")
            continue
        if not isinstance(payload, dict) or "commit" not in payload:
            # Not a claim about this release; measurement files carry a commit on purpose.
            continue
        if payload["commit"] != commit:
            stale.append(
                f"{path.relative_to(REPO)}: measured at {str(payload['commit'])[:7]}"
            )
    if stale:
        failures.append(
            "GATE-CE-EVIDENCE-FRESH: evidence from another commit:\n  "
            + "\n  ".join(stale)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    # The closeout baseline: the commit the phase started from, `ac3dfef` unless the
    # caller knows better. Passed rather than read from a file so a rebase cannot make
    # this gate quietly compare against the wrong thing.
    parser.add_argument("--baseline", default="ac3dfef")
    args = parser.parse_args()

    commit = head()
    print(f"V2-C1 closeout gates (baseline: {args.baseline}, HEAD: {commit[:7]})")
    check_no_product_drift(args.baseline)
    check_journey_coverage(commit)
    check_evidence_fresh(commit)

    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(
        "closeout invariants: OK (no undeclared product drift, seven journeys, fresh evidence)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
