"""M-AR-9: how long a working agent goes quiet between events.

`runner.idle_timeout_seconds` is the one constant in D21 that can only be guessed
without a measurement, and guessing it wrong in the small direction kills an agent
that is working — which re-queues the card, so **one wrong kill is usually three**.

What matters here is **the tail, not the median**. A median inter-event gap of two
seconds tells you nothing about the run that spends nine minutes inside a test
suite; the idle timeout has to clear the longest *legitimate* silence, and every
number below the tail is decoration.

The instrument runs the CLI exactly as `plan/18/04-…md` §5 says the daemon will —
non-interactive, prompt on stdin, event stream on stdout — and timestamps each
JSONL line **as it arrives**, not by any clock inside the event:

    claude -p --output-format stream-json --verbose   < prompt
    codex exec --json                                  < prompt

    python scripts/ar/measure_event_intervals.py --runtime claude \
        --prompt-file prompt.txt --out artifacts/ar/local/measurements/m-ar-9-claude.json

Reading is line-buffered and unbuffered on the child's side where possible: a gap
that is really an artefact of a 4 KiB stdio buffer would be indistinguishable from
a gap in the agent's work, and this measurement exists to tell those apart.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

# Exactly the tables from M-AR-1 (`plan/18/10-…md` §1.1), so the gaps measured here
# are the gaps the daemon will see. Changing these makes the number answer a
# different question.
RUN_ARGS = {
    "claude": ["-p", "--output-format", "stream-json", "--verbose"],
    "codex": ["exec", "--json"],
}


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return ordered[rank - 1]


def _event_label(line: str) -> str:
    """A coarse name for what the event was, so the longest gaps can be attributed.

    "the tail is 9 minutes" is a number; "the tail is 9 minutes and it is always a
    Bash tool call" is a decision about whether tool-call granularity is enough.
    """
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return "<unparsed>"
    if not isinstance(payload, dict):
        return "<non-object>"
    parts = [str(payload.get("type", "?"))]
    if subtype := payload.get("subtype"):
        parts.append(str(subtype))
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    parts.append(f"tool:{block.get('name')}")
                    break
    return "/".join(parts)


def _measure(
    runtime: str,
    binary: str,
    prompt: str,
    cwd: Path,
    timeout: float,
    extra: list[str],
) -> dict[str, Any]:
    args = [binary, *RUN_ARGS[runtime], *extra]
    started = time.perf_counter()
    process = subprocess.Popen(
        args,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(prompt)
    # Closed immediately after writing, as the daemon will: a CLI still holding an
    # open stdin can wait on it forever, and that wait would be measured as an
    # inter-event gap that has nothing to do with the agent's work.
    process.stdin.close()

    events: list[dict[str, Any]] = []
    previous = started
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        now = time.perf_counter()
        events.append(
            {
                "at_seconds": round(now - started, 3),
                "gap_seconds": round(now - previous, 3),
                "label": _event_label(line),
                "bytes": len(line),
            }
        )
        previous = now
    process.stdin = None
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
    stderr = (process.stderr.read() if process.stderr else "") or ""
    total = time.perf_counter() - started

    gaps = [event["gap_seconds"] for event in events]
    tail = sorted(events, key=lambda event: event["gap_seconds"], reverse=True)[:5]
    return {
        "runtime": runtime,
        "argv": args[1:],
        "exit_code": process.returncode,
        "wall_seconds": round(total, 3),
        "events": len(events),
        "gap_p50": round(_percentile(gaps, 0.50), 3) if gaps else None,
        "gap_p95": round(_percentile(gaps, 0.95), 3) if gaps else None,
        "gap_p99": round(_percentile(gaps, 0.99), 3) if gaps else None,
        "gap_max": round(max(gaps), 3) if gaps else None,
        "gap_mean": round(statistics.fmean(gaps), 3) if gaps else None,
        "longest_gaps": tail,
        "stderr_tail": stderr[-2000:],
        "timeline": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=sorted(RUN_ARGS), required=True)
    parser.add_argument("--binary", default="")
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=3600.0)
    # The second residual of M-AR-1: which `--permission-mode` an unattended run
    # needs (`plan/18/04-…md` §5.4). Kept out of RUN_ARGS so that table keeps
    # mirroring the measured non-interactive flags exactly, and so the answer to
    # this question is visible in each report's `argv`.
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    binary = args.binary or args.runtime
    report = _measure(
        args.runtime,
        binary,
        args.prompt_file.read_text(),
        args.cwd,
        args.timeout,
        args.extra,
    )
    report["measurement"] = "M-AR-9 inter-event gap distribution (plan/18 AR-00)"
    report["prompt_file"] = str(args.prompt_file)
    report["cwd"] = str(args.cwd)

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    summary = {
        key: report[key]
        for key in (
            "runtime",
            "exit_code",
            "wall_seconds",
            "events",
            "gap_p50",
            "gap_p95",
            "gap_p99",
            "gap_max",
        )
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
