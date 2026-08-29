#!/usr/bin/env python
"""`work-counts` under concurrency, over HTTP (`HD-09`, plan/27/07 §5).

    . scripts/hd/env.sh && hd_stack_env
    uv run --project backend python scripts/hd/measure-concurrency.py --base http://127.0.0.1:8111

**This is the one measurement in the phase that deliberately does not use the service
layer.** Everything else is weighed against a session because the query is what the card
count changes. Here the subject *is* the round trip: what is being measured is the
connection pool and the event loop contending, and a service-level call has neither.

| Scenario | Concurrency | Budget | Why that number |
|---|---:|---|---|
| `work-counts` | 10 | P95 < 200ms | D95's hard budget, re-weighed on 2000 cards |
| `work-counts` | 50 | P95 < 500ms | a fifty-person team each with a board tab open |
| `work-counts` | 100 | **recorded, no budget** | where it stops working, not how fast |

**The third row has no budget on purpose.** The only available response to exceeding a
guessed budget is to raise it, and that is bookkeeping rather than measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import httpx  # noqa: E402

SCENARIOS = [(10, 200.0), (50, 500.0), (100, None)]
ROUNDS = 5


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


async def one(client: httpx.AsyncClient, url: str, headers: dict) -> tuple[float, int | str]:
    """One request, and **a transport failure is a result rather than an exception.**

    The third scenario exists to find where this stops working, so the run must survive
    finding out. A `raise_for_status()` here would abort the measurement at exactly the
    concurrency the measurement is about, and leave the artifact empty.
    """
    began = time.perf_counter()
    try:
        reply = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return (time.perf_counter() - began) * 1000, type(exc).__name__
    return (time.perf_counter() - began) * 1000, reply.status_code


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8111")
    parser.add_argument("--project-slug", default="hd-large-20260828")
    parser.add_argument("--out", default="artifacts/hd/local/w6/concurrency-2000.json")
    args = parser.parse_args()

    password = os.environ.get("CLIORA_ADMIN_PASSWORD")
    if not password:
        print("set CLIORA_ADMIN_PASSWORD (scripts/hd/env.sh: hd_stack_env)", file=sys.stderr)
        return 2

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    async with httpx.AsyncClient(base_url=args.base, timeout=120.0, limits=limits) as client:
        login = await client.post(
            "/api/auth/login", json={"username": "e2e-admin", "password": password}
        )
        login.raise_for_status()
        headers = {"authorization": f"Bearer {login.json()['tokens']['access_token']}"}

        projects = await client.get("/api/projects", params={"limit": 100}, headers=headers)
        projects.raise_for_status()
        body = projects.json()
        # The route answers a bare list; `items` is the shape most other collection
        # routes use, so both are accepted rather than pinned to whichever one is
        # current on the day this ran.
        items = body if isinstance(body, list) else body.get("items", [])
        match = [item for item in items if item["slug"] == args.project_slug]
        if not match:
            print(f"no project {args.project_slug} on {args.base}", file=sys.stderr)
            return 2
        url = f"/api/projects/{match[0]['id']}/work-counts"

        # Warm: the first request pays for pool construction and JIT-ish import cost, and
        # attributing that to "concurrency 10" would make the first scenario the slowest
        # one no matter what the server does.
        await client.get(url, headers=headers)

        results = []
        for concurrency, budget in SCENARIOS:
            samples: list[float] = []
            ok_samples: list[float] = []
            codes: dict[str, int] = {}
            wall = time.perf_counter()
            for _ in range(ROUNDS):
                done = await asyncio.gather(
                    *(one(client, url, headers) for _ in range(concurrency))
                )
                for elapsed, code in done:
                    samples.append(elapsed)
                    if code == 200:
                        ok_samples.append(elapsed)
                    codes[str(code)] = codes.get(str(code), 0) + 1
            seconds = time.perf_counter() - wall
            # **P95 is over the successful requests.** A 503 that returns in 4ms would
            # otherwise improve the percentile, so a server that refuses everything
            # instantly would post the best number in the table.
            p95 = round(percentile(ok_samples, 0.95), 2) if ok_samples else float("nan")
            succeeded = len(ok_samples)
            if budget is None:
                verdict = "RECORDED"
            elif succeeded < len(samples):
                # Not "FAIL because it was slow" — a scenario that dropped requests has
                # not met a latency budget regardless of what the survivors did.
                verdict = "FAIL"
            else:
                verdict = "PASS" if p95 < budget else "FAIL"
            row = {
                "concurrency": concurrency,
                "requests": len(samples),
                "succeeded": succeeded,
                "status_codes": codes,
                "median_ms": round(statistics.median(ok_samples), 2) if ok_samples else None,
                "p95_ms": p95 if ok_samples else None,
                "max_ms": round(max(ok_samples), 2) if ok_samples else None,
                "throughput_rps": round(succeeded / seconds, 1),
                "budget_ms": budget,
                # A budget of `None` is not a pass. The row records a number and says so,
                # because "PASS" against no budget is a claim nobody made.
                "verdict": verdict,
            }
            results.append(row)
            print(
                f"concurrency {concurrency:>3}  {succeeded:>4}/{len(samples)} ok"
                f"  median {row['median_ms'] or float('nan'):>8.2f}ms"
                f"  p95 {p95:>9.2f}ms  max {row['max_ms'] or float('nan'):>9.2f}ms"
                f"  {row['throughput_rps']:>6.1f} rps  {row['verdict']}"
            )
            if set(codes) != {"200"}:
                print(f"  !! not all 200: {codes}")

    payload = {
        "commit": commit(),
        "base": args.base,
        "project_slug": args.project_slug,
        "rounds_per_scenario": ROUNDS,
        "transport": "HTTP — the pool and the loop contending is the subject",
        "scenarios": results,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 1 if any(row["verdict"] == "FAIL" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
