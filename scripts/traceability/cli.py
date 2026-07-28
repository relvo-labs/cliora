from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .bootstrap import bootstrap
from .evidence import snapshot, write_snapshot
from .model import (
    REPO_ROOT,
    TRACE_ROOT,
    JsonObject,
    load_json,
    load_trace_data,
    locator_path,
    sha256_path,
)
from .render import render
from .validate import coverage, validate_schemas, validate_selectors, validate_static


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _resolve_commit(value: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", value],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _print_findings(findings: Sequence[Any], output_format: str) -> None:
    if output_format == "json":
        _json({"findings": [finding.as_dict() for finding in findings]})
        return
    if not findings:
        print("traceability validation passed")
        return
    for finding in findings:
        object_label = f" [{finding.object_id}]" if finding.object_id else ""
        print(f"{finding.code}{object_label}: {finding.message}")


def command_validate(args: argparse.Namespace) -> int:
    if args.level == "schema":
        findings = validate_schemas()
    else:
        data = load_trace_data()
        findings = validate_static(data)
        if args.level == "selectors" and not findings:
            findings.extend(validate_selectors(data))
    _print_findings(findings, args.format)
    return 2 if findings else 0


def command_coverage(args: argparse.Namespace) -> int:
    result = coverage(load_trace_data(), args.scope)
    if args.format == "json":
        _json(result)
    else:
        summary = result["summary"]
        print(
            f"criteria={summary['total']} verifiable={summary['verifiable']} "
            f"covered-by-parent={summary['covered_by_parent']} "
            f"needs-rewrite={summary['needs_rewrite']} "
            f"blocking={summary['blocking']}"
        )
        gaps = [row for row in result["criteria"] if row["missing"]]
        shown = gaps if args.verbose else gaps[:20]
        for row in shown:
            print(f"{row['criterion_id']}: missing {', '.join(row['missing'])}")
        if len(shown) < len(gaps):
            print(
                f"... {len(gaps) - len(shown)} more gap(s); see docs/traceability/gaps.md"
            )
        for row in result["criteria"]:
            if row["status"] == "needs-rewrite":
                print(f"{row['criterion_id']}: needs rewrite before it can be verified")
    if args.baseline:
        return _baseline_verdict(result, Path(args.baseline))
    # `--strict` answers "may full release blocking be switched on", so an open
    # rewrite queue counts against it exactly like a missing link does.
    unresolved = result["summary"]["blocking"] + result["summary"]["needs_rewrite"]
    return 4 if args.strict and unresolved else 0


def _baseline_verdict(result: JsonObject, baseline_path: Path) -> int:
    """Changed-scope blocking: everything except a named, finite debt list fails.

    The list is checked in both directions. A gap that is not on it blocks, and an
    entry that is no longer a gap also blocks — otherwise the file quietly grows
    into the 308-item backlog it replaced.
    """
    baseline = load_json(baseline_path)
    allowed = {entry["criterion_id"] for entry in baseline["entries"]}
    open_now = {
        row["criterion_id"]
        for row in result["criteria"]
        if (
            row["missing"]
            and row["criticality"] == "must"
            and row["modifier"] != "waived-active"
        )
        or row["status"] == "needs-rewrite"
    }
    new_gaps = sorted(open_now - allowed)
    stale = sorted(allowed - open_now)
    for criterion_id in new_gaps:
        print(f"blocked: {criterion_id} is a new gap, not baseline debt")
    for criterion_id in stale:
        print(
            f"blocked: {criterion_id} is listed as baseline debt but is no longer a gap; "
            f"remove it from {baseline_path.name}"
        )
    if new_gaps or stale:
        return 4
    print(f"changed-scope clean; {len(allowed)} known baseline debt item(s) remain")
    return 0


def command_render(args: argparse.Namespace) -> int:
    drift = render(load_trace_data(), check=args.check)
    if drift:
        print("generated traceability documents are stale:")
        for path in drift:
            print(f"- {path}")
        return 5
    print(
        "generated traceability documents are current"
        if args.check
        else "rendered traceability documents"
    )
    return 0


def _changed_files(base: str, head: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--find-renames", f"{base}...{head}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line)


def command_impact(args: argparse.Namespace) -> int:
    data = load_trace_data()
    changed = _changed_files(args.base, args.head)
    impacted: dict[str, list[str]] = {}
    mapped_paths: set[str] = set()
    for link in data.links:
        path, _ = locator_path(link["target"]["kind"], link["target"]["locator"])
        if path is None:
            continue
        try:
            relative = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            continue
        mapped_paths.add(relative)
        for changed_path in changed:
            if changed_path == relative or changed_path.startswith(
                relative.rstrip("/") + "/"
            ):
                impacted.setdefault(link["from"], []).append(changed_path)
    for requirement in data.requirements:
        source_path = requirement["source"]["path"]
        if source_path in changed:
            for criterion in requirement["criteria"]:
                impacted.setdefault(criterion["id"], []).append(source_path)
    product_roots = (
        "backend/app/",
        "daemon/",
        "frontend/src/",
        "contracts/",
        "deploy/",
    )
    unknown = [
        path
        for path in changed
        if path.startswith(product_roots)
        and not any(
            path == mapped or path.startswith(mapped.rstrip("/") + "/")
            for mapped in mapped_paths
        )
    ]
    owners = sorted(
        {
            requirement["owner"]
            for requirement in data.requirements
            if any(criterion["id"] in impacted for criterion in requirement["criteria"])
        }
    )
    result = {
        "base": args.base,
        "head": args.head,
        "changed_files": changed,
        "impacted_criteria": {
            key: sorted(set(value)) for key, value in sorted(impacted.items())
        },
        "owners": owners,
        "unknown_product_impact": unknown,
    }
    if args.format == "json":
        _json(result)
    else:
        print(f"changed={len(changed)} impacted={len(impacted)} unknown={len(unknown)}")
        for criterion_id, paths in result["impacted_criteria"].items():
            print(f"- {criterion_id}: {', '.join(paths)}")
        for path in unknown:
            print(f"! unknown product impact: {path}")
    return 4 if unknown else 0


def command_snapshot(args: argparse.Namespace) -> int:
    commit = _resolve_commit(args.commit)
    value = snapshot(load_trace_data(), Path(args.results).resolve(), commit=commit)
    if args.out:
        write_snapshot(value, Path(args.out).resolve())
    if args.format == "json" or not args.out:
        _json(value)
    else:
        print(
            f"snapshot verdict={value['verdict']} verified={value['summary']['verified']} "
            f"blocking={value['summary']['blocking']}"
        )
    return 4 if value["verdict"] != "accepted" else 0


def command_explain(args: argparse.Namespace) -> int:
    data = load_trace_data()
    requirement_index = data.requirement_index()
    criterion_index = data.criterion_index()
    if args.id in requirement_index:
        requirements = [requirement_index[args.id]]
    elif args.id in criterion_index:
        requirements = [criterion_index[args.id][0]]
    else:
        print(f"unknown requirement or criterion: {args.id}", file=sys.stderr)
        return 2
    by_source = data.links_by_source()
    for requirement in requirements:
        print(f"{requirement['id']} — {requirement['title']} ({requirement['owner']})")
        for criterion in requirement["criteria"]:
            if args.id != requirement["id"] and criterion["id"] != args.id:
                continue
            kind = criterion.get("classification", "criterion")
            print(
                f"  {criterion['id']} [{criterion['verification_profile']}/{criterion['risk']}]"
                + ("" if kind == "criterion" else f" ({kind})")
            )
            # Otherwise an absorbed bullet reads as a criterion with no verification.
            if criterion.get("covered_by"):
                print(f"    covered_by: {criterion['covered_by']}")
            if "review" in criterion:
                review = criterion["review"]
                approved = "approved" if review.get("approved") else "unapproved"
                print(
                    f"    review ({approved}, {review['classified_by']}, "
                    f"{review['classified_at']}): {review['rationale']}"
                )
            for link in by_source.get(criterion["id"], []):
                target = link["target"]
                gate = f" via {link['gate_id']}" if link.get("gate_id") else ""
                print(f"    {link['type']}: {target['kind']}:{target['locator']}{gate}")
    return 0


def command_owners(args: argparse.Namespace) -> int:
    data = load_trace_data()
    requirement_id = args.id.split(".AC-", 1)[0]
    requirement = data.requirement_index().get(requirement_id)
    if not requirement:
        print(f"unknown requirement: {args.id}", file=sys.stderr)
        return 2
    owners = {requirement["owner"]}
    for link in data.links_by_source().get(args.id, []):
        owners.add(link["owner"])
    print("\n".join(sorted(owners)))
    return 0


def _environment_map(
    gate: JsonObject, declared: Sequence[str], profile: str
) -> JsonObject:
    """Account for every declared matrix leg.

    Legs default to `skipped`, never to `executed`: a runner that says nothing
    about WebKit did not run WebKit, and the snapshot has to be able to tell.
    """
    reported = {"profile": profile}
    for leg in gate.get("environment", []):
        reported[leg] = "executed" if leg in declared else "skipped"
    return reported


def _parse_environment(values: Sequence[str] | None) -> list[str]:
    return list(values or [])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sanitize_evidence_text(value: str) -> str:
    value = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", value)
    value = re.sub(r"\benroll_[A-Za-z0-9._-]+", "enroll_[REDACTED]", value)
    value = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "[REDACTED_JWT]",
        value,
    )
    value = re.sub(r"/(?:home|Users)/[^/\s]+/", "/[PRIVATE_HOME]/", value)
    return value[:4000]


def command_manual_template(args: argparse.Namespace) -> int:
    commit = _resolve_commit(args.commit)
    value = {
        "schema_version": 1,
        "procedure_id": args.procedure,
        "procedure_version": 1,
        "commit": commit,
        "actor": "",
        "reviewer": "",
        "executed_at": _utc_now(),
        "environment": {},
        "steps": [],
        "artifacts": [],
        "result": "pending",
        "deviations": [],
    }
    output = Path(args.out)
    output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output)
    return 0


def command_run_gate(args: argparse.Namespace) -> int:
    data = load_trace_data()
    gate = data.gate_index().get(args.gate_id)
    if gate is None:
        print(f"unknown gate: {args.gate_id}", file=sys.stderr)
        return 2
    commit = _resolve_commit(args.commit)
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    started_wall = _utc_now()
    started_mono = time.monotonic()
    if args.skip_reason:
        # A prerequisite this runner does not have. Recorded as its own status so
        # a snapshot can tell "not run here" from "ran and passed".
        status = "skipped"
        exit_code: int | None = None
    else:
        try:
            completed = subprocess.run(
                gate["command"],
                cwd=REPO_ROOT / gate["working_directory"],
                timeout=gate["timeout_seconds"],
                check=False,
            )
            status = "passed" if completed.returncode == 0 else "failed"
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            status = "failed"
            exit_code = None
    finished_wall = _utc_now()
    selectors = sorted(
        {
            link["target"]["locator"]
            for link in data.links
            if link.get("gate_id") == gate["id"]
            and link["type"]
            in {"verified_by", "measured_by", "validated_by", "guards_scope"}
        }
    )
    result = {
        "schema_version": 1,
        "run_id": args.run_id,
        "commit": commit,
        "tree_state": "dirty" if dirty else "clean",
        "generated_at": finished_wall,
        "gate_definition_sha256": sha256_path(TRACE_ROOT / "gates.json"),
        "runner": {
            "provider": os.environ.get("CI_PROVIDER", "local"),
            "os": platform.system().lower(),
            "arch": platform.machine().lower(),
            "profile": args.profile,
        },
        "gates": [
            {
                "id": gate["id"],
                "started_at": started_wall,
                "finished_at": finished_wall,
                "duration_ms": round((time.monotonic() - started_mono) * 1000),
                "status": status,
                "command": gate["command"],
                "exit_code": exit_code,
                "selectors": selectors,
                "environment": _environment_map(
                    gate, _parse_environment(args.environment), args.profile
                ),
                "artifacts": [],
                **(
                    {"skip_reason": _sanitize_evidence_text(args.skip_reason)}
                    if status == "skipped"
                    else {}
                ),
            }
        ],
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if status in {"passed", "skipped"} else 4


def command_emit_evidence(args: argparse.Namespace) -> int:
    data = load_trace_data()
    gate = data.gate_index().get(args.gate_id)
    if gate is None:
        print(f"unknown gate: {args.gate_id}", file=sys.stderr)
        return 2
    commands_path = Path(args.commands)
    skips_path = Path(args.skips) if args.skips else None
    command_text = commands_path.read_text(encoding="utf-8")
    exit_codes = [int(value) for value in re.findall(r"exit=([0-9]+)", command_text)]
    skip_text = (
        skips_path.read_text(encoding="utf-8").strip()
        if skips_path is not None and skips_path.exists()
        else ""
    )
    if any(code != 0 for code in exit_codes):
        status = "failed"
        exit_code: int | None = 1
    elif skip_text:
        status = "skipped"
        exit_code = None
    else:
        status = "passed"
        exit_code = 0
    commit = _resolve_commit(args.commit)
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    now = _utc_now()
    selectors = sorted(
        {
            link["target"]["locator"]
            for link in data.links
            if link.get("gate_id") == gate["id"]
            and link["type"]
            in {"verified_by", "measured_by", "validated_by", "guards_scope"}
        }
    )
    result: JsonObject = {
        "schema_version": 1,
        "run_id": args.run_id,
        "commit": commit,
        "tree_state": "dirty" if dirty else "clean",
        "generated_at": now,
        "gate_definition_sha256": sha256_path(TRACE_ROOT / "gates.json"),
        "runner": {
            "provider": os.environ.get("CI_PROVIDER", "local"),
            "os": platform.system().lower(),
            "arch": platform.machine().lower(),
            "profile": args.profile,
        },
        "gates": [
            {
                "id": gate["id"],
                "started_at": now,
                "finished_at": now,
                "duration_ms": 0,
                "status": status,
                "command": gate["command"],
                "exit_code": exit_code,
                "selectors": selectors,
                "environment": _environment_map(
                    gate, _parse_environment(args.environment), args.profile
                ),
                "artifacts": [],
                **(
                    {"skip_reason": _sanitize_evidence_text(skip_text)}
                    if status == "skipped"
                    else {}
                ),
            }
        ],
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 4 if status == "failed" else 0


def command_merge(args: argparse.Namespace) -> int:
    """Combine per-gate shards into the one result file a snapshot reads.

    Shards that disagree about the commit, the tree state, the gate definition or
    the runner profile are refused rather than merged: a release verdict assembled
    from two different revisions is worse than no verdict.
    """
    shards = [load_json(Path(path)) for path in args.results]
    if not shards:
        print("no shards given", file=sys.stderr)
        return 2
    head, *rest = shards
    for field in ("commit", "tree_state", "gate_definition_sha256"):
        mismatched = {shard[field] for shard in shards}
        if len(mismatched) > 1:
            print(
                f"refusing to merge: shards disagree on {field}: {sorted(mismatched)}",
                file=sys.stderr,
            )
            return 4
    profiles = {shard["runner"]["profile"] for shard in shards}
    if len(profiles) > 1:
        print(
            f"refusing to merge: shards ran under different profiles: {sorted(profiles)}",
            file=sys.stderr,
        )
        return 4
    gates: list[JsonObject] = []
    seen: set[str] = set()
    for shard in shards:
        for gate in shard["gates"]:
            if gate["id"] in seen:
                print(
                    f"refusing to merge: {gate['id']} appears in more than one shard",
                    file=sys.stderr,
                )
                return 4
            seen.add(gate["id"])
            gates.append(gate)
    merged = {
        **head,
        "run_id": args.run_id or head["run_id"],
        "generated_at": _utc_now(),
        "gates": sorted(gates, key=lambda item: item["id"]),
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"merged {len(shards)} shard(s), {len(gates)} gate result(s) -> {output}")
    return 0


def command_bootstrap(args: argparse.Namespace) -> int:
    if not args.force:
        print(
            "bootstrap rewrites canonical anchors and baseline registries; rerun with --force",
            file=sys.stderr,
        )
        return 2
    _json(bootstrap())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trace", description="Cliora requirement traceability"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument(
        "--level", choices=["schema", "static", "selectors"], default="static"
    )
    validate_parser.add_argument("--format", choices=["human", "json"], default="human")
    validate_parser.set_defaults(func=command_validate)

    coverage_parser = subparsers.add_parser("coverage")
    coverage_parser.add_argument("--scope", choices=["all", "mvp"], default="all")
    coverage_parser.add_argument("--format", choices=["human", "json"], default="human")
    coverage_parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on blocking gaps; omit during report-only baseline rollout",
    )
    coverage_parser.add_argument(
        "--baseline",
        help="changed-scope blocking: fail on any gap outside this debt list, and on "
        "any entry in it that is no longer a gap",
    )
    coverage_parser.add_argument("--verbose", action="store_true")
    coverage_parser.set_defaults(func=command_coverage)

    render_parser = subparsers.add_parser("render")
    render_mode = render_parser.add_mutually_exclusive_group(required=True)
    render_mode.add_argument("--check", action="store_true")
    render_mode.add_argument("--write", action="store_true")
    render_parser.set_defaults(func=command_render)

    impact_parser = subparsers.add_parser("impact")
    impact_parser.add_argument("--base", required=True)
    impact_parser.add_argument("--head", required=True)
    impact_parser.add_argument("--format", choices=["human", "json"], default="human")
    impact_parser.set_defaults(func=command_impact)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--results", required=True)
    snapshot_parser.add_argument("--commit", default="HEAD")
    snapshot_parser.add_argument("--out")
    snapshot_parser.add_argument("--format", choices=["human", "json"], default="human")
    snapshot_parser.set_defaults(func=command_snapshot)

    explain_parser = subparsers.add_parser("explain")
    explain_parser.add_argument("id")
    explain_parser.set_defaults(func=command_explain)

    owners_parser = subparsers.add_parser("owners")
    owners_parser.add_argument("id")
    owners_parser.set_defaults(func=command_owners)

    manual_parser = subparsers.add_parser("manual-template")
    manual_parser.add_argument("--procedure", required=True)
    manual_parser.add_argument("--commit", default="HEAD")
    manual_parser.add_argument("--out", default="manual-result.json")
    manual_parser.set_defaults(func=command_manual_template)

    run_parser = subparsers.add_parser("run-gate")
    run_parser.add_argument("gate_id")
    run_parser.add_argument("--commit", default="HEAD")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--profile", default="local")
    run_parser.add_argument(
        "--skip-reason",
        help="record the gate as skipped with this prerequisite instead of running it",
    )
    run_parser.add_argument(
        "--environment",
        action="append",
        help="name a declared environment leg this run actually executed; "
        "unnamed legs are recorded as skipped",
    )
    run_parser.add_argument("--out", required=True)
    run_parser.set_defaults(func=command_run_gate)

    emit_parser = subparsers.add_parser("emit-evidence")
    emit_parser.add_argument("--gate-id", required=True)
    emit_parser.add_argument("--commands", required=True)
    emit_parser.add_argument("--skips")
    emit_parser.add_argument("--commit", default="HEAD")
    emit_parser.add_argument("--run-id", required=True)
    emit_parser.add_argument("--profile", default="local")
    emit_parser.add_argument(
        "--environment",
        action="append",
        help="name a declared environment leg this run actually executed; "
        "unnamed legs are recorded as skipped",
    )
    emit_parser.add_argument("--out", required=True)
    emit_parser.set_defaults(func=command_emit_evidence)

    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("results", nargs="+")
    merge_parser.add_argument("--run-id")
    merge_parser.add_argument("--out", required=True)
    merge_parser.set_defaults(func=command_merge)

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--force", action="store_true")
    bootstrap_parser.set_defaults(func=command_bootstrap)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
