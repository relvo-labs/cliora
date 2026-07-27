"""Session lifecycle churn: the per-node cap, and no leaks after it (P4-11).

Two properties, both about what happens at and after the limit:

* `sessions_per_node_max` is **enforced**, and the refusal is the named
  `SESSION_LIMIT_REACHED` rather than a generic 500 — the cap is a product rule the
  operator has to be able to recognise, not an incidental failure;
* repeated create/terminate cycles leave nothing behind: the node's session count
  returns to its floor, Central's RSS does not ratchet up per cycle, and the fake
  daemon's own bookkeeping agrees with Central's about how many sessions exist.

The daemon-side agreement check is the interesting one. Central's row count and the
daemon's live set are maintained independently, so a divergence after churn is exactly
the shape of a leak — a session Central thinks is running that the node has forgotten,
or the reverse.

    cd backend && uv run python ../scripts/p4/load/session_churn.py \
        --base-url http://127.0.0.1:8000 --admin-password ... --cycles 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Central,
    CentralError,
    RssSampler,
    Scenario,
    bring_up_fleet,
    print_scenario,
    tear_down_fleet,
    write_report,
)


def _error_code(error: CentralError) -> str:
    if '"code"' not in error.body:
        return ""
    return error.body.split('"code":"', 1)[-1].split('"', 1)[0]


async def run(args: argparse.Namespace) -> Scenario:
    scenario = Scenario(name="session-churn")
    central = Central(args.base_url)
    central.login(args.admin_user, args.admin_password)

    rss = RssSampler(args.central_pid)
    if not rss.available:
        scenario.notes.append(
            "Central RSS not sampled: pass --central-pid on the same host to include "
            "the leak evidence."
        )

    daemons = await bring_up_fleet(
        central,
        nodes=args.nodes,
        roots=[args.workspace_root],
        heartbeat_interval=args.heartbeat_interval,
    )
    rss.start()
    created_total = 0
    refused_codes: dict[str, int] = {}
    terminate_failures: dict[str, int] = {}
    cycle_counts: list[int] = []

    try:
        await asyncio.sleep(args.heartbeat_interval + 1)

        for cycle in range(args.cycles):
            live: list[str] = []
            # Push past the cap on purpose: the extra attempts are the point.
            for index in range(args.cap + args.overshoot):
                for daemon in daemons:
                    try:
                        created = await asyncio.to_thread(
                            central.create_session,
                            daemon.node_id,
                            name=f"churn-{cycle}-{index}",
                            workspace=args.workspace_root,
                        )
                        live.append(created["id"])
                        created_total += 1
                    except CentralError as error:
                        code = _error_code(error) or f"http-{error.status}"
                        refused_codes[code] = refused_codes.get(code, 0) + 1

            cycle_counts.append(len(live))

            # The daemon's own view, before teardown.
            daemon_live = sum(len(d.sessions) for d in daemons)
            scenario.measurements.setdefault("per_cycle", []).append(
                {
                    "cycle": cycle,
                    "central_created": len(live),
                    "daemon_live_sessions": daemon_live,
                }
            )

            for session_id in live:
                try:
                    await asyncio.to_thread(central.terminate_session, session_id)
                except CentralError as error:
                    # Recorded, never suppressed. Silently swallowing a failed
                    # terminate is how the leak checks came to report a leak that was
                    # the harness failing to tear down.
                    code = _error_code(error) or f"http-{error.status}"
                    terminate_failures[code] = terminate_failures.get(code, 0) + 1
            # Give the stop round trips a moment to land on the fake daemons.
            await asyncio.sleep(0.5)

        residual_daemon = sum(len(d.sessions) for d in daemons)
        running = _running_per_node(central, [d.node_id for d in daemons])

        await rss.stop()
        scenario.measurements.update(
            {
                "nodes": args.nodes,
                "cycles": args.cycles,
                "cap": args.cap,
                "overshoot_attempts_per_cycle": args.overshoot * args.nodes,
                "sessions_created_total": created_total,
                "refusal_codes": refused_codes,
                "terminate_failures": terminate_failures,
                "sessions_per_cycle": cycle_counts,
                "daemon_sessions_after_teardown": residual_daemon,
                "central_running_after_teardown": running,
                "central_rss": rss.summary(),
            }
        )

        expected_per_cycle = args.cap * args.nodes
        scenario.check(
            "cap_enforced",
            f"ADR 0013: at most sessions_per_node_max ({args.cap}) sessions per node",
            passed=all(count <= expected_per_cycle for count in cycle_counts),
            observed=cycle_counts,
            limit=expected_per_cycle,
        )
        expected_refusals = args.overshoot * args.nodes * args.cycles
        scenario.check(
            "cap_refusal_is_named",
            "the cap refusal is SESSION_LIMIT_REACHED, not a generic failure",
            passed=refused_codes.get("SESSION_LIMIT_REACHED", 0) >= expected_refusals,
            observed=refused_codes,
            limit=f"SESSION_LIMIT_REACHED >= {expected_refusals}",
            detail="An operator has to be able to tell 'you hit the limit' from "
            "'something broke'; only the named code does that.",
        )
        scenario.check(
            "teardown_succeeds",
            "harness integrity: every created session is actually terminated",
            passed=not terminate_failures,
            observed=terminate_failures or "none",
            limit="no failures",
            detail="A failed teardown makes the leak checks below meaningless, so it "
            "is reported as its own failure rather than folded into them.",
        )
        scenario.check(
            "no_session_leak_on_the_node",
            "no leak: the daemon holds no sessions after every cycle is torn down",
            passed=residual_daemon == 0,
            observed=residual_daemon,
            limit=0,
        )
        scenario.check(
            "no_session_leak_in_central",
            "no leak: Central reports no running sessions after teardown",
            passed=running == 0,
            observed=running,
            limit=0,
            detail="Counted independently of the daemon's set, so a divergence here "
            "is the leak rather than a shared bookkeeping error.",
        )

        if rss.samples:
            summary = rss.summary()
            growth = summary["second_half_mean_mib"] - summary["first_half_mean_mib"]
            scenario.check(
                "central_rss_does_not_ratchet",
                "no leak: RSS does not climb with each create/terminate cycle",
                passed=growth <= args.rss_growth_budget_mib,
                observed=round(growth, 1),
                limit=args.rss_growth_budget_mib,
                detail=f"peak {summary['peak_mib']} MiB over {args.cycles} cycles",
            )
    finally:
        await tear_down_fleet(daemons)
        await rss.stop()
    return scenario


def _running_per_node(central: Central, node_ids: list[str]) -> int:
    """How many sessions Central still considers running on the fleet."""
    _, body = central.timed("GET", "/api/sessions")
    wanted = set(node_ids)
    return sum(
        1
        for s in body
        if s["node_id"] in wanted and s["status"] in ("running", "starting")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--nodes", type=int, default=3)
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--cap", type=int, default=10)
    parser.add_argument("--overshoot", type=int, default=2)
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--workspace-root", default="/tmp/cliora-load")
    parser.add_argument("--central-pid", type=int, default=None)
    parser.add_argument("--rss-growth-budget-mib", type=float, default=48.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    scenario = asyncio.run(run(args))
    print_scenario(scenario)
    if args.out:
        write_report(args.out, scenario.to_json())
    return 1 if scenario.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
