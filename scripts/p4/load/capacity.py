"""P4-11 orchestrator: run every capacity scenario and emit `capacity.json`.

One command, one verdict. It starts a Central of its own against a throwaway database
(so a load run can never pollute a shared one), runs the three scenarios in sequence,
and writes the artifact the exit gate reads — including **per-NFR pass/fail**, not just
numbers. Exits non-zero if any check failed, which is what lets this sit in CI as a gate
rather than as a report someone has to remember to read.

Scenarios run sequentially rather than concurrently on purpose: each one's memory and
latency claims are about *its* load, and overlapping them would make every number
un-attributable.

    # small, for every PR
    scripts/p4/load/capacity.py --profile smoke

    # full NFR-003 scale, for merge and RC
    scripts/p4/load/capacity.py --profile full
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_nodes  # noqa: E402
import session_churn  # noqa: E402
import terminal_clients  # noqa: E402
from _common import Scenario, print_scenario, write_report  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

# Two profiles. `smoke` is small enough to run on every PR so the harness cannot rot
# unnoticed; `full` is the NFR-003 target. Same code path, same assertions — only the
# magnitudes differ, so a smoke pass is real (if partial) evidence.
PROFILES: dict[str, dict[str, Any]] = {
    "smoke": {
        "nodes": 5,
        "clients": 10,
        "sessions": 4,
        "slow_clients": 1,
        "flood_clients": 1,
        "duration": 8.0,
        "churn_nodes": 2,
        "churn_cycles": 2,
        "pending_probe": 160,
    },
    "full": {
        "nodes": 100,
        "clients": 500,
        "sessions": 50,
        "slow_clients": 5,
        "flood_clients": 5,
        "duration": 30.0,
        "churn_nodes": 3,
        "churn_cycles": 5,
        "pending_probe": 160,
    },
}


class Stack:
    """A throwaway Central: own database, own port, own admin.

    Deliberately not reusing an existing deployment or a shared test database. A load
    run creates hundreds of nodes and sessions and deliberately floods and stalls
    connections; pointing that at a database other tests use is how a load run becomes
    a mysterious failure in an unrelated suite.
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.port = args.port
        self.database = f"cliora_load_{uuid.uuid4().hex[:8]}"
        self.password = "LoadHarness-" + uuid.uuid4().hex[:12]
        self.process: subprocess.Popen[bytes] | None = None
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.db_url = ""
        self._created_db = False

    # --- database ---

    def _psql(self, database: str, *sql: str) -> None:
        command = [
            "docker",
            "exec",
            self.args.pg_container,
            "psql",
            "-U",
            self.args.pg_user,
            "-d",
            database,
        ]
        for statement in sql:
            command += ["-c", statement]
        subprocess.run(command, check=True, capture_output=True)

    def create_database(self) -> None:
        self._psql(
            "postgres", f'CREATE DATABASE "{self.database}" OWNER {self.args.pg_user}'
        )
        self._created_db = True
        self.db_url = (
            f"postgresql+asyncpg://{self.args.pg_user}:{self.args.pg_password}"
            f"@127.0.0.1:{self.args.pg_port}/{self.database}"
        )
        env = {**os.environ, "CLIORA_DATABASE_URL": self.db_url}
        subprocess.run(
            ["uv", "run", "--project", ".", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "uv",
                "run",
                "--project",
                ".",
                "python",
                "-m",
                "app.bootstrap",
                "create-admin",
                "--username",
                "loadadmin",
                "--password",
                self.password,
            ],
            cwd=ROOT / "backend",
            env=env,
            check=True,
            capture_output=True,
        )

    def drop_database(self) -> None:
        if not self._created_db:
            return
        # check=False: teardown must not mask the run's own verdict. A leftover
        # database is reported by name in the artifact rather than raising here.
        subprocess.run(
            [
                "docker",
                "exec",
                self.args.pg_container,
                "psql",
                "-U",
                self.args.pg_user,
                "-d",
                "postgres",
                "-c",
                f'DROP DATABASE IF EXISTS "{self.database}"',
            ],
            capture_output=True,
            check=False,
        )

    # --- process ---

    def start(self) -> None:
        env = {
            **os.environ,
            "CLIORA_DATABASE_URL": self.db_url,
            # A load run must not be shaped by a stray .env: the bounds under test are
            # the defaults the product ships with.
            "CLIORA_ENVIRONMENT": "test",
        }
        self.process = subprocess.Popen(
            [
                "uv",
                "run",
                "--project",
                ".",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT / "backend",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"{self.base_url}/readyz", timeout=2
                ) as response:
                    if json.loads(response.read())["status"] == "ready":
                        return
            except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
                time.sleep(0.5)
        raise RuntimeError("Central did not become ready")

    @property
    def pid(self) -> int | None:
        """The uvicorn worker's pid, for RSS sampling.

        `uv run` may exec through a wrapper, so the direct child is not necessarily the
        server. The deepest descendant that is a python process is.
        """
        if self.process is None:
            return None
        pid = self.process.pid
        for _ in range(4):
            children = self._children(pid)
            python_children = [c for c in children if self._is_python(c)]
            if not python_children:
                break
            pid = python_children[0]
        return pid

    @staticmethod
    def _children(pid: int) -> list[int]:
        path = Path(f"/proc/{pid}/task/{pid}/children")
        if not path.exists():
            return []
        try:
            return [int(p) for p in path.read_text().split()]
        except (OSError, ValueError):
            return []

    @staticmethod
    def _is_python(pid: int) -> bool:
        try:
            return b"python" in Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return False

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()


def _namespace(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


async def _guarded(name: str, budget: float, coro: Any) -> Scenario:
    """Run one scenario under a wall-clock budget.

    A hung scenario used to hang the whole harness, producing no artifact at all — the
    worst possible outcome for something meant to gate CI, because "still running" is
    indistinguishable from "passing" to anything watching. A timeout is now a recorded
    FAIL with the budget it blew, and the remaining scenarios still run.
    """
    try:
        return await asyncio.wait_for(coro, timeout=budget)
    except TimeoutError:
        scenario = Scenario(name=name)
        scenario.check(
            "scenario_completes",
            "harness integrity: the scenario finishes inside its wall-clock budget",
            passed=False,
            observed=f"> {budget:.0f}s",
            limit=f"{budget:.0f}s",
            detail="Timed out. Treat as a failure of the run, not of the harness, "
            "until the cause is identified: a stall here usually means something in "
            "Central stopped answering.",
        )
        return scenario


async def _run_all(
    stack: Stack, args: argparse.Namespace, profile: dict[str, Any]
) -> list[Scenario]:
    common = {
        "base_url": stack.base_url,
        "admin_user": "loadadmin",
        "admin_password": stack.password,
        "central_pid": stack.pid,
        "workspace_root": args.workspace_root,
        "heartbeat_interval": args.heartbeat_interval,
        "out": None,
    }
    scenarios: list[Scenario] = []

    # Budgets are generous multiples of the expected duration: they exist to convert a
    # hang into a report, not to police performance (the checks inside do that).
    scenarios.append(
        await _guarded(
            "fleet-scale",
            args.scenario_budget_seconds,
            fake_nodes.run(
                _namespace(
                    **common,
                    nodes=profile["nodes"],
                    pending_probe=profile["pending_probe"],
                    pending_max=args.pending_max,
                    rss_growth_budget_mib=args.rss_growth_budget_mib,
                )
            ),
        )
    )
    # A pause between scenarios so the previous run's sockets are fully released and
    # the next scenario's memory baseline is its own.
    await asyncio.sleep(3)

    scenarios.append(
        await _guarded(
            "terminal-relay",
            args.scenario_budget_seconds,
            terminal_clients.run(
                _namespace(
                    **common,
                    clients=profile["clients"],
                    sessions=profile["sessions"],
                    sessions_per_node=10,
                    slow_clients=profile["slow_clients"],
                    flood_clients=profile["flood_clients"],
                    duration=profile["duration"],
                    slow_extra=5.0,
                    slow_drain_seconds=args.slow_drain_seconds,
                    slow_rcvbuf=args.slow_rcvbuf,
                    input_size=64,
                    in_flight=1,
                    output_rate_bytes=args.output_rate_bytes,
                    output_chunk=4096,
                    connect_pace=args.connect_pace,
                    queue_max_bytes=args.queue_max_bytes,
                    queue_slack=1.5,
                    rss_growth_budget_mib=args.rss_growth_budget_mib + 32,
                )
            ),
        )
    )
    await asyncio.sleep(3)

    scenarios.append(
        await _guarded(
            "session-churn",
            args.scenario_budget_seconds,
            session_churn.run(
                _namespace(
                    **common,
                    nodes=profile["churn_nodes"],
                    cycles=profile["churn_cycles"],
                    cap=args.sessions_per_node_max,
                    overshoot=2,
                    rss_growth_budget_mib=args.rss_growth_budget_mib,
                )
            ),
        )
    )
    return scenarios


def _environment(stack: Stack) -> dict[str, Any]:
    """Recorded with the results, because a capacity number without the machine it was
    measured on is not comparable to the next run's."""
    return {
        "host": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "total_ram_mib": _total_ram_mib(),
        "central_base_url": stack.base_url,
        "database": stack.database,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _total_ram_mib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--pg-container", default="cliora-pg")
    parser.add_argument("--pg-user", default="cliora")
    parser.add_argument("--pg-password", default="cliora")
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--workspace-root", default="/tmp/cliora-load")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--pending-max", type=int, default=128)
    parser.add_argument("--sessions-per-node-max", type=int, default=10)
    parser.add_argument("--queue-max-bytes", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--output-rate-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--connect-pace", type=float, default=0.004)
    parser.add_argument("--rss-growth-budget-mib", type=float, default=64.0)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "artifacts/p4/local/capacity.json"
    )
    parser.add_argument("--slow-rcvbuf", type=int, default=4096)
    parser.add_argument("--slow-drain-seconds", type=float, default=20.0)
    parser.add_argument("--scenario-budget-seconds", type=float, default=420.0)
    parser.add_argument("--keep-database", action="store_true")
    args = parser.parse_args()

    if shutil.which("docker") is None:
        print(
            "docker is required to create the throwaway load database", file=sys.stderr
        )
        return 2

    profile = PROFILES[args.profile]
    stack = Stack(args)
    scenarios: list[Scenario] = []
    startup_error = ""
    try:
        stack.create_database()
        stack.start()
        scenarios = asyncio.run(_run_all(stack, args, profile))
    except Exception as error:  # noqa: BLE001 - recorded, not swallowed
        startup_error = f"{type(error).__name__}: {error}"
    finally:
        stack.stop()
        if not args.keep_database:
            stack.drop_database()

    report = {
        "profile": args.profile,
        "profile_settings": profile,
        "environment": _environment(stack),
        "bounds_under_test": {
            "pending_requests_max": args.pending_max,
            "sessions_per_node_max": args.sessions_per_node_max,
            "terminal_queue_max_bytes": args.queue_max_bytes,
            "note": "These must match the Central under test; the harness asserts "
            "against them and cannot read them over HTTP.",
        },
        "scenarios": [s.to_json() for s in scenarios],
        "startup_error": startup_error,
    }
    failed = [c for s in scenarios for c in s.failed]
    report["verdict"] = {
        "status": "pass" if not failed and not startup_error else "FAIL",
        "checks_total": sum(len(s.checks) for s in scenarios),
        "checks_failed": len(failed),
        "failed": [c.name for c in failed],
    }
    write_report(args.out, report)

    for scenario in scenarios:
        print_scenario(scenario)
    print(f"\ncapacity report: {args.out}")
    if startup_error:
        print(f"FAILED before measuring: {startup_error}", file=sys.stderr)
        return 1
    print(
        f"verdict: {report['verdict']['status']} "
        f"({report['verdict']['checks_failed']}/{report['verdict']['checks_total']} failed)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
