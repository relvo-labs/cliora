"""M11 and M12: what fetching a repository costs, in seconds and in bytes.

Both measurements block `AR-07b` (`plan/18/10-…md` §1.2, §1.3), and they block it
for the same reason: **a quota chosen without them is a guess, and the failure mode
of a wrong guess is a full disk that also stops interactive sessions.**

M11 asks whether the bare-mirror strategy earns its keep. `research/02/01` D19 rule
4 simply says "use a mirror", but that is a conclusion that assumes a large
repository — and a cache layer nobody needed is still something to reclaim, lock
and repair. So each repository is measured **both ways**:

    mirror:  git clone --mirror   →  git worktree add --detach   (×N)
    shallow: git clone --depth 1                                 (×N)

M12 asks how big a run directory gets. The honest answer has two halves: the
checkout itself (small, measured here) and whatever the agent builds inside it
(large, and the reason the quota's *order of magnitude* is the question). The
second half is reported as a separate number, because a `node_modules/` is the
difference between a megabyte quota and a gigabyte one.

Local sources are read over `file://` on purpose: a local-path clone hardlinks its
objects, which makes both the timing and the size meaningless for this question.

    python scripts/ar/measure_clone.py --repo cliora=/home/ubuntu/workspace/cliora \
        --out artifacts/ar/local/measurements/m11-m12.json

Every source is cloned into a scratch directory that is removed afterwards; nothing
is written next to the source repository.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# The same three environment variables the daemon puts on its own git calls
# (ADR 0031 §5, consequence two): a measurement that can hang on a password prompt
# measures the prompt.
GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/false",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _run(args: list[str], cwd: Path | None = None) -> float:
    started = time.perf_counter()
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed ({result.returncode}):\n{result.stderr.strip()}"
        )
    return elapsed


def _size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for name in files:
            entry = Path(root) / name
            try:
                # `lstat`, not `stat`: a symlink's target is counted where it lives.
                total += entry.lstat().st_size
            except OSError:
                pass
    return total


def _url(source: str) -> str:
    # file:// rather than a bare path: a local-path clone hardlinks objects, and both
    # numbers this script produces would then be answers to a different question.
    if "://" in source or source.startswith("git@"):
        return source
    return f"file://{Path(source).resolve()}"


def _measure_repo(
    name: str, source: str, worktrees: int, scratch: Path
) -> dict[str, Any]:
    url = _url(source)
    base = scratch / name
    base.mkdir(parents=True)
    mirror = base / "mirror.git"

    report: dict[str, Any] = {"name": name, "source": url}

    report["mirror_clone_seconds"] = round(
        _run(["clone", "--mirror", "--", url, str(mirror)]), 3
    )
    report["mirror_bytes"] = _size(mirror)
    # A no-op update: the interesting number is the fixed cost paid before every run,
    # not the cost of fetching commits that happen to exist today.
    report["mirror_update_noop_seconds"] = round(
        _run(["--git-dir", str(mirror), "remote", "update", "--prune"]), 3
    )

    head = subprocess.run(
        ["git", "--git-dir", str(mirror), "rev-parse", "HEAD"],
        env=GIT_ENV,
        capture_output=True,
        text=True,
    ).stdout.strip()
    report["head"] = head

    times: list[float] = []
    for index in range(worktrees):
        dest = base / f"worktree-{index}"
        times.append(
            _run(
                [
                    "--git-dir",
                    str(mirror),
                    "worktree",
                    "add",
                    "--detach",
                    str(dest),
                    head,
                ]
            )
        )
        if index == 0:
            report["worktree_bytes"] = _size(dest)
    report["worktree_add_seconds"] = [round(value, 3) for value in times]
    report["worktree_add_seconds_median"] = round(statistics.median(times), 3)

    shallow_times: list[float] = []
    for index in range(worktrees):
        dest = base / f"shallow-{index}"
        shallow_times.append(_run(["clone", "--depth", "1", "--", url, str(dest)]))
        if index == 0:
            report["shallow_bytes"] = _size(dest)
    report["shallow_clone_seconds"] = [round(value, 3) for value in shallow_times]
    report["shallow_clone_seconds_median"] = round(statistics.median(shallow_times), 3)

    # The decision M11 exists to make, stated as a number rather than left to the
    # reader: how many runs it takes for the mirror to pay for its own first clone.
    per_run_mirror = (
        report["mirror_update_noop_seconds"] + report["worktree_add_seconds_median"]
    )
    per_run_shallow = report["shallow_clone_seconds_median"]
    saving = per_run_shallow - per_run_mirror
    report["per_run_mirror_seconds"] = round(per_run_mirror, 3)
    report["per_run_shallow_seconds"] = round(per_run_shallow, 3)
    report["mirror_breakeven_runs"] = (
        round(report["mirror_clone_seconds"] / saving, 1) if saving > 0 else None
    )
    # Disk, three runs in parallel, which is what `runner.total_quota_bytes` is set
    # from. The mirror is shared; the worktrees are not.
    report["three_concurrent_runs_bytes_mirror"] = (
        report["mirror_bytes"] + 3 * report["worktree_bytes"]
    )
    report["three_concurrent_runs_bytes_shallow"] = 3 * report["shallow_bytes"]

    shutil.rmtree(base, ignore_errors=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="NAME=SOURCE",
        help="a repository to measure; SOURCE may be a local path or a URL",
    )
    parser.add_argument("--worktrees", type=int, default=3)
    parser.add_argument(
        "--build-artifact",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="an existing build output directory to size, for M12's order-of-magnitude half",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if not args.repo:
        raise SystemExit("pass at least one --repo NAME=SOURCE")

    scratch = Path(tempfile.mkdtemp(prefix="ar-m11-"))
    try:
        repos = []
        for item in args.repo:
            name, _, source = item.partition("=")
            print(f"→ {name}", file=sys.stderr)
            repos.append(_measure_repo(name, source, args.worktrees, scratch))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    builds = []
    for item in args.build_artifact:
        label, _, path = item.partition("=")
        target = Path(path)
        if target.exists():
            builds.append({"label": label, "path": str(target), "bytes": _size(target)})

    report = {
        "measurement": "M11 (clone/worktree cost) and M12 (run directory size), plan/18 AR-00",
        "worktrees_per_repo": args.worktrees,
        "repos": repos,
        "build_outputs": builds,
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    sys.stdout.write(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
