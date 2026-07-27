from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .model import TRACE_ROOT, JsonObject, TraceData, load_json, sha256_path
from .validate import coverage


#: How a result may account for one declared environment leg. `profile` is the
#: free-form runner label and is not a leg.
LEG_STATES = {"executed", "skipped", "not-applicable"}
RESERVED_ENVIRONMENT_KEYS = {"profile"}


def _environment_errors(definition: JsonObject, gate: JsonObject) -> list[str]:
    """A gate that declares a matrix has to say what happened to each leg.

    Without this a browser job that only ran Chromium produces a result that is
    indistinguishable from one that ran all three, and every WebKit criterion
    linked to it reads as verified.
    """
    declared = set(definition.get("environment", []))
    reported = gate.get("environment", {})
    errors: list[str] = []
    for name in sorted(declared - set(reported)):
        errors.append(f"{gate['id']} does not report environment leg {name}")
    for name, state in sorted(reported.items()):
        if name in RESERVED_ENVIRONMENT_KEYS:
            continue
        if name not in declared:
            errors.append(
                f"{gate['id']} reports environment {name}, which traceability/gates.json "
                f"does not declare for it"
            )
        elif state not in LEG_STATES:
            errors.append(
                f"{gate['id']} environment {name}={state!r} is not one of "
                f"{sorted(LEG_STATES)}"
            )
    return errors


def unexecuted_legs(definition: JsonObject, gate: JsonObject) -> list[str]:
    declared = set(definition.get("environment", []))
    reported = gate.get("environment", {})
    return sorted(
        name for name in declared if reported.get(name, "skipped") != "executed"
    )


def validate_gate_results(path: Path, *, commit: str) -> list[str]:
    result = load_json(path)
    schema = load_json(TRACE_ROOT / "schema" / "gate-results.schema.json")
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(result)
    ]
    if errors:
        return sorted(errors)
    if result["commit"] != commit:
        errors.append(f"stale commit: results={result['commit']} requested={commit}")
    if result["tree_state"] != "clean":
        errors.append("release evidence requires a clean tree")
    gates_hash = sha256_path(TRACE_ROOT / "gates.json")
    if result["gate_definition_sha256"] != gates_hash:
        errors.append("gate definition hash does not match traceability/gates.json")
    gate_definitions = {item["id"]: item for item in load_trace_gate_list()}
    known = set(gate_definitions)
    seen: set[str] = set()
    for gate in result["gates"]:
        if gate["id"] not in known:
            errors.append(f"unknown gate result {gate['id']}")
        else:
            errors.extend(_environment_errors(gate_definitions[gate["id"]], gate))
        if gate["id"] in seen:
            errors.append(f"duplicate gate result {gate['id']}")
        seen.add(gate["id"])
        for artifact in gate["artifacts"]:
            raw_artifact = Path(artifact["path"])
            if raw_artifact.is_absolute():
                errors.append(f"artifact path must be relative {artifact['path']}")
                continue
            artifact_path = (path.parent / raw_artifact).resolve()
            try:
                artifact_path.relative_to(path.parent.resolve())
            except ValueError:
                errors.append(f"artifact path escapes evidence root {artifact['path']}")
                continue
            if not artifact_path.is_file():
                errors.append(f"missing artifact {artifact['path']}")
                continue
            if artifact_path.stat().st_size != artifact["size"]:
                errors.append(f"artifact size mismatch {artifact['path']}")
            if sha256_path(artifact_path) != artifact["sha256"]:
                errors.append(f"artifact digest mismatch {artifact['path']}")
        if gate["status"] == "skipped" and not gate.get("skip_reason"):
            errors.append(f"skipped gate {gate['id']} needs skip_reason")
    return errors


def load_trace_gate_list() -> list[JsonObject]:
    return load_json(TRACE_ROOT / "gates.json")["gates"]


def snapshot(data: TraceData, results_path: Path, *, commit: str) -> JsonObject:
    errors = validate_gate_results(results_path, commit=commit)
    static = coverage(data)
    result = load_json(results_path)
    gate_results = {item["id"]: item for item in result.get("gates", [])}
    gate_definitions = data.gate_index()
    links_by_source = data.links_by_source()
    criteria_rows: list[JsonObject] = []
    for row in static["criteria"]:
        criterion_id = row["criterion_id"]
        evidence_links = [
            link
            for link in links_by_source.get(criterion_id, [])
            if link.get("gate_id")
            and link["type"]
            in {"verified_by", "measured_by", "validated_by", "guards_scope"}
            and link["role"] == "primary"
        ]
        required_gate_ids = sorted({link["gate_id"] for link in evidence_links})
        missing_results = [
            gate_id for gate_id in required_gate_ids if gate_id not in gate_results
        ]
        failed = [
            gate_id
            for gate_id in required_gate_ids
            if gate_id in gate_results and gate_results[gate_id]["status"] != "passed"
        ]
        unresolved_selectors = sorted(
            f"{link['gate_id']}:{link['target']['locator']}"
            for link in evidence_links
            if link["gate_id"] in gate_results
            and gate_results[link["gate_id"]]["status"] == "passed"
            and link["target"]["locator"]
            not in gate_results[link["gate_id"]]["selectors"]
        )
        # A passing gate whose matrix only half ran proves only the legs that ran.
        incomplete_environments = sorted(
            f"{gate_id}:{leg}"
            for gate_id in required_gate_ids
            if gate_id in gate_results
            and gate_results[gate_id]["status"] == "passed"
            and gate_id in gate_definitions
            for leg in unexecuted_legs(gate_definitions[gate_id], gate_results[gate_id])
        )
        if row["status"] in {"covered-by-parent", "needs-rewrite"}:
            verdict = row["status"]
        elif row["missing"]:
            verdict = "blocked-static"
        elif missing_results:
            verdict = "no-current-evidence"
        elif failed:
            statuses = {gate_results[gate_id]["status"] for gate_id in failed}
            verdict = "skipped" if statuses == {"skipped"} else "failed"
        elif unresolved_selectors:
            verdict = "selector-unproven"
        elif incomplete_environments:
            verdict = "environment-incomplete"
        elif required_gate_ids:
            verdict = "verified"
        else:
            verdict = "verifiable"
        criteria_rows.append(
            {
                **row,
                "required_gates": required_gate_ids,
                "missing_results": missing_results,
                "non_passing_gates": failed,
                "unproven_selectors": unresolved_selectors,
                "incomplete_environments": incomplete_environments,
                "verdict": verdict,
            }
        )
    blocking = [
        row
        for row in criteria_rows
        if row["criticality"] == "must"
        and row["verdict"] not in {"verified", "covered-by-parent"}
    ]
    return {
        "schema_version": 1,
        "commit": commit,
        "run_id": result.get("run_id"),
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "validity_errors": errors,
        "criteria": criteria_rows,
        "summary": {
            "total": len(criteria_rows),
            "verified": sum(row["verdict"] == "verified" for row in criteria_rows),
            "blocking": len(blocking) + len(errors),
        },
        "verdict": "accepted" if not blocking and not errors else "blocked",
    }


def write_snapshot(value: JsonObject, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
