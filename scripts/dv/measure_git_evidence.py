"""M6 — how long the evidence collection's three git commands take (plan/21/10-…md §1.1).

The number this produces decides one thing: **the timeout the daemon puts on
`Runner.Inspect`**. Both ways of getting it wrong are new failure modes rather than a
badly tuned parameter, which is why `research/02/10` §5 marks M6 as answerable *before*
V2.4 starts:

* too short — the evidence block is empty on every large repository, and that reads as
  "the feature does not work" rather than "the timeout is low";
* too long (or absent) — a hung `git status` stops the run's last step forever **while
  the lease keeps renewing**, so Central sees a run wedged in `finishing`.

Three commands, because all three run in the same step and `git diff` on a dirty large
repository is far slower than `status`:

    git status --porcelain      git diff --stat       git diff

**Measured on a throwaway clone, never on the repository itself.** The dirty half has
to modify tracked files, and doing that to a working tree somebody is using is not a
measurement, it is an accident. `git clone --local` is cheap and gives an index whose
stat cache is warm in the same way a run directory's is right after checkout.

    python scripts/dv/measure_git_evidence.py REPO [REPO...] --out artifacts/dv/local/m6.json

Every duration is wall clock in milliseconds, from Python, around a `subprocess.run` —
that includes process spawn, which is right: the daemon pays it too.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The three commands, with the exact argv the daemon uses (`gitfetch` composes them
# from a closed table; `diff --stat` is the one V2.4 adds). Keeping them identical here
# matters more than it looks: `git status` without `--porcelain` does extra formatting
# work, so measuring the friendly form would overstate the cost.
COMMANDS: dict[str, list[str]] = {
    "status": ["status", "--porcelain"],
    "diff_stat": ["diff", "--stat"],
    "diff": ["diff"],
}

RUNS = 10
# How much of the tree the dirty half touches. 5% is chosen to be *plausible* rather
# than worst case: a run that rewrote every file would be a different measurement, and
# the interesting question here is what a normal agent leaves behind.
DIRTY_FRACTION = 0.05
DIRTY_CAP = 500


def _time_once(repo: Path, args: list[str]) -> float:
    start = time.perf_counter()
    subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return (time.perf_counter() - start) * 1000.0


def _measure(repo: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for name, args in COMMANDS.items():
        # One warm-up that is deliberately **not** recorded. The first invocation pays
        # for the page cache on `.git/index`, and the daemon's own first call in a run
        # has already been preceded by a clone — so including it would measure a state
        # no real run is ever in.
        _time_once(repo, args)
        samples = sorted(_time_once(repo, args) for _ in range(RUNS))
        out[name] = {
            "p50": round(statistics.median(samples), 1),
            # With 10 samples the 95th percentile is the largest one. Named p95 for
            # continuity with the other baselines, and `max` is printed beside it so
            # nobody reads more resolution into it than it has.
            "p95": round(samples[-1], 1),
            "max": round(samples[-1], 1),
            "mean": round(statistics.fmean(samples), 1),
            "samples": RUNS,
        }
    return out


def _dirty(repo: Path) -> int:
    """Modify a slice of the tracked files, in place, and report how many."""
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    target = min(DIRTY_CAP, max(1, int(len(tracked) * DIRTY_FRACTION)))
    touched = 0
    for name in tracked:
        if touched >= target:
            break
        path = repo / name
        try:
            if not path.is_file() or path.is_symlink():
                continue
            with path.open("ab") as handle:
                handle.write(b"\n# m6\n")
        except OSError:
            continue
        touched += 1
    return touched


def _snapshot(source: Path, workdir: Path) -> Path:
    clone = workdir / source.name
    subprocess.run(
        ["git", "clone", "--quiet", "--local", "--no-hardlinks", str(source), str(clone)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return clone


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repos", nargs="+")
    parser.add_argument("--out")
    args = parser.parse_args()

    results = []
    for raw in args.repos:
        source = Path(raw).resolve()
        if not (source / ".git").exists():
            print(f"!! {source} is not a git repository", file=sys.stderr)
            continue
        with tempfile.TemporaryDirectory(prefix="m6-") as tmp:
            clone = _snapshot(source, Path(tmp))
            files = len(
                subprocess.run(
                    ["git", "-C", str(clone), "ls-files"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.splitlines()
            )
            clean = _measure(clone)
            touched = _dirty(clone)
            dirty = _measure(clone)
            # The clone dies with the temp directory; nothing is restored because
            # nothing shared was modified.
            results.append(
                {
                    "repo": str(source),
                    "tracked_files": files,
                    "dirty_files": touched,
                    "clean": clean,
                    "dirty": dirty,
                }
            )
            print(
                f"{source.name:<24} {files:>6} files  "
                f"status p95 {clean['status']['p95']:>7.1f} / {dirty['status']['p95']:>7.1f} ms  "
                f"diff p95 {clean['diff']['p95']:>7.1f} / {dirty['diff']['p95']:>7.1f} ms  "
                "(clean / dirty)",
                file=sys.stderr,
            )

    worst = max(
        (
            entry[state][name]["p95"]
            for entry in results
            for state in ("clean", "dirty")
            for name in COMMANDS
        ),
        default=0.0,
    )
    # The rule from plan/21/10-…md §1.1: four times the worst p95, rounded up to five
    # seconds, floor ten. Four rather than two because a run ends on a machine that is
    # usually still running other runs, and they share one disk — the measurement is
    # taken idle and the value is used when it is not.
    suggested = max(10, -(-int(worst * 4 / 1000) // 5) * 5)
    payload = {
        "runs_per_command": RUNS,
        "commands": {name: ["git", *argv] for name, argv in COMMANDS.items()},
        "results": results,
        "worst_p95_ms": round(worst, 1),
        "suggested_timeout_seconds": suggested,
        # The threshold that would change the design rather than the number: above it,
        # collection has to become "may fail" instead of "must complete".
        "design_change_threshold_ms": 5000,
        "design_change_required": worst > 5000,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(f"\nwrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    print(
        f"\nworst p95 {worst:.1f} ms → timeout {suggested}s"
        + ("  ** exceeds 5 s: collection must become failable **" if worst > 5000 else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
