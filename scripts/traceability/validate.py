from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .model import (
    OWNER_KEYS,
    REPO_ROOT,
    TRACE_ROOT,
    TraceData,
    JsonObject,
    load_json,
    locator_path,
    markdown_anchors,
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    object_id: str = ""
    blocking: bool = True

    def as_dict(self) -> JsonObject:
        return {
            "code": self.code,
            "message": self.message,
            "object_id": self.object_id,
            "blocking": self.blocking,
        }


SCHEMA_FILES = {
    "requirements.json": "requirements.schema.json",
    "links.json": "links.schema.json",
    "gates.json": "gates.schema.json",
    "waivers.json": "waivers.schema.json",
}


def validate_schemas() -> list[Finding]:
    findings: list[Finding] = []
    checker = FormatChecker()
    for document_name, schema_name in SCHEMA_FILES.items():
        document = load_json(TRACE_ROOT / document_name)
        schema = load_json(TRACE_ROOT / "schema" / schema_name)
        validator = Draft202012Validator(schema, format_checker=checker)
        for error in sorted(
            validator.iter_errors(document), key=lambda item: list(item.path)
        ):
            pointer = "/" + "/".join(str(part) for part in error.absolute_path)
            findings.append(
                Finding(
                    "schema.invalid",
                    f"{document_name}{pointer}: {error.message}",
                    document_name,
                )
            )
    return findings


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


#: Classifications from `plan/06/02` §3 Pass B. Only `criterion` carries its own
#: verification claim; `constraint`/`data_shape`/`example` are parts of another
#: criterion and must name it, and `needs_rewrite` is an open review item that can
#: never be silently counted as covered.
ABSORBED_CLASSIFICATIONS = {"constraint", "data_shape", "example"}


def classification(criterion: JsonObject) -> str:
    return criterion.get("classification", "criterion")


def _classification_findings(
    criterion: JsonObject, siblings: dict[str, JsonObject]
) -> list[Finding]:
    findings: list[Finding] = []
    kind = classification(criterion)
    parent_id = criterion.get("covered_by")
    if kind in ABSORBED_CLASSIFICATIONS:
        if not parent_id:
            findings.append(
                Finding(
                    "classification.uncovered",
                    f"{kind} criterion must name the criterion that absorbs it",
                    criterion["id"],
                )
            )
        elif parent_id == criterion["id"]:
            findings.append(
                Finding(
                    "classification.self_covered",
                    "covered_by may not point at itself",
                    criterion["id"],
                )
            )
        elif parent_id not in siblings:
            findings.append(
                Finding(
                    "classification.foreign_parent",
                    f"covered_by must stay inside the same requirement: {parent_id}",
                    criterion["id"],
                )
            )
        else:
            parent = siblings[parent_id]
            if classification(parent) != "criterion":
                findings.append(
                    Finding(
                        "classification.parent_not_verifiable",
                        f"{parent_id} is {classification(parent)}, so it carries no verification",
                        criterion["id"],
                    )
                )
            if parent.get("lifecycle", "active") != "active":
                findings.append(
                    Finding(
                        "classification.parent_inactive",
                        f"{parent_id} is not active",
                        criterion["id"],
                    )
                )
        if "review" not in criterion:
            findings.append(
                Finding(
                    "classification.unreviewed",
                    f"{kind} classification needs a recorded review",
                    criterion["id"],
                )
            )
    else:
        if parent_id:
            findings.append(
                Finding(
                    "classification.unexpected_parent",
                    f"{kind} criterion carries its own verification and may not be absorbed",
                    criterion["id"],
                )
            )
        if kind == "needs_rewrite" and "review" not in criterion:
            findings.append(
                Finding(
                    "classification.unreviewed",
                    "needs_rewrite must record who raised it and why",
                    criterion["id"],
                )
            )
    return findings


def validate_static(data: TraceData) -> list[Finding]:
    findings = validate_schemas()
    if findings:
        return findings

    requirement_ids = [item["id"] for item in data.requirements]
    criterion_ids = [
        criterion["id"]
        for requirement in data.requirements
        for criterion in requirement["criteria"]
    ]
    link_ids = [item["id"] for item in data.links]
    gate_ids = [item["id"] for item in data.gates]
    waiver_ids = [item["id"] for item in data.waivers]
    for kind, values in (
        ("requirement", requirement_ids),
        ("criterion", criterion_ids),
        ("link", link_ids),
        ("gate", gate_ids),
        ("waiver", waiver_ids),
    ):
        for duplicate in sorted(_duplicates(values)):
            findings.append(Finding("id.duplicate", f"duplicate {kind} ID", duplicate))

    source_cache: dict[Path, dict[str, str]] = {}
    for requirement in data.requirements:
        source_path = REPO_ROOT / requirement["source"]["path"]
        if not source_path.is_file():
            findings.append(
                Finding(
                    "source.missing",
                    f"missing source {requirement['source']['path']}",
                    requirement["id"],
                )
            )
            continue
        anchors = source_cache.setdefault(source_path, markdown_anchors(source_path))
        if requirement["source"]["anchor"] not in anchors:
            findings.append(
                Finding(
                    "anchor.missing",
                    f"{requirement['source']['path']}#{requirement['source']['anchor']} does not exist",
                    requirement["id"],
                )
            )
        own_criteria = {item["id"]: item for item in requirement["criteria"]}
        for criterion in requirement["criteria"]:
            if not criterion["id"].startswith(f"{requirement['id']}.AC-"):
                findings.append(
                    Finding(
                        "criterion.parent",
                        "criterion ID does not match its parent",
                        criterion["id"],
                    )
                )
            findings.extend(_classification_findings(criterion, own_criteria))
            if criterion["source_anchor"] not in anchors:
                findings.append(
                    Finding(
                        "anchor.missing",
                        f"{requirement['source']['path']}#{criterion['source_anchor']} does not exist",
                        criterion["id"],
                    )
                )
        if requirement["owner"] not in OWNER_KEYS:
            findings.append(
                Finding("owner.unknown", "unknown owner", requirement["id"])
            )

    criterion_index = data.criterion_index()
    requirement_index = data.requirement_index()
    gate_index = data.gate_index()
    for gate in data.gates:
        working_directory = (REPO_ROOT / gate["working_directory"]).resolve()
        try:
            working_directory.relative_to(REPO_ROOT.resolve())
        except ValueError:
            findings.append(
                Finding(
                    "gate.path_escape",
                    f"working directory escapes repository: {gate['working_directory']}",
                    gate["id"],
                )
            )
            continue
        if not working_directory.is_dir():
            findings.append(
                Finding(
                    "gate.directory_missing",
                    f"working directory does not exist: {gate['working_directory']}",
                    gate["id"],
                )
            )
    for link in data.links:
        if link["from"] not in criterion_index:
            findings.append(
                Finding("link.source_missing", "criterion does not exist", link["id"])
            )
        if link.get("gate_id") and link["gate_id"] not in gate_index:
            findings.append(
                Finding(
                    "link.gate_missing", f"unknown gate {link['gate_id']}", link["id"]
                )
            )
        target = link["target"]
        if target["kind"] == "requirement":
            target_id = target["locator"].split(".AC-", 1)[0]
            if target_id not in requirement_index:
                findings.append(
                    Finding(
                        "link.target_missing",
                        f"unknown requirement {target['locator']}",
                        link["id"],
                    )
                )
            continue
        if target["kind"] == "gate":
            if target["locator"] not in gate_index:
                findings.append(
                    Finding(
                        "link.target_missing",
                        f"unknown gate {target['locator']}",
                        link["id"],
                    )
                )
            continue
        path, _ = locator_path(target["kind"], target["locator"])
        if path is not None:
            try:
                resolved = path.resolve()
                resolved.relative_to(REPO_ROOT.resolve())
            except (OSError, ValueError):
                findings.append(
                    Finding(
                        "path.escape",
                        f"target escapes repository: {target['locator']}",
                        link["id"],
                    )
                )
                continue
            if not resolved.exists():
                findings.append(
                    Finding(
                        "link.target_missing",
                        f"target does not exist: {target['locator']}",
                        link["id"],
                    )
                )

    for waiver in data.waivers:
        created = datetime.fromisoformat(waiver["created_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(waiver["expires_at"].replace("Z", "+00:00"))
        if created.tzinfo is None or expires.tzinfo is None:
            findings.append(
                Finding(
                    "waiver.naive_time",
                    "waiver timestamps require offsets",
                    waiver["id"],
                )
            )
        if expires <= created:
            findings.append(
                Finding(
                    "waiver.invalid_window", "expiry must follow creation", waiver["id"]
                )
            )
        if expires - created > timedelta(days=90):
            findings.append(
                Finding(
                    "waiver.too_long", "waiver may not exceed 90 days", waiver["id"]
                )
            )
        for criterion_id in waiver["criteria"]:
            pair = criterion_index.get(criterion_id)
            if pair is None:
                findings.append(
                    Finding(
                        "waiver.criterion_missing",
                        f"unknown criterion {criterion_id}",
                        waiver["id"],
                    )
                )
            elif pair[1]["risk"] == "critical":
                findings.append(
                    Finding(
                        "waiver.non_waivable",
                        f"critical criterion {criterion_id}",
                        waiver["id"],
                    )
                )
    return findings


def validate_selectors(data: TraceData) -> list[Finding]:
    findings: list[Finding] = []
    for link in data.links:
        target = link["target"]
        if target["kind"] not in {
            "pytest",
            "gotest",
            "vitest",
            "playwright",
            "scenario",
            "fixture",
        }:
            continue
        path, token = locator_path(target["kind"], target["locator"])
        if path is None or not path.exists():
            findings.append(
                Finding(
                    "selector.path_missing",
                    f"selector path missing: {target['locator']}",
                    link["id"],
                )
            )
            continue
        if token:
            if path.is_dir():
                contents = "\n".join(
                    child.read_text(encoding="utf-8", errors="replace")
                    for child in path.rglob("*")
                    if child.is_file() and child.suffix in {".py", ".go", ".ts"}
                )
            else:
                contents = path.read_text(encoding="utf-8", errors="replace")
            candidates = [token, token.split(" > ")[-1]]
            if not any(candidate and candidate in contents for candidate in candidates):
                findings.append(
                    Finding(
                        "selector.unresolved",
                        f"selector token not found: {target['locator']}",
                        link["id"],
                    )
                )
    return findings


def required_link_types(requirement: JsonObject, criterion: JsonObject) -> set[str]:
    kind = requirement["kind"]
    profile = criterion["verification_profile"]
    if kind == "functional":
        return {"planned_by", "specified_by", "implemented_by", "verified_by"}
    if kind in {"security", "tech_security"}:
        return {"specified_by", "implemented_by", "verified_by"}
    if kind == "non_functional" or profile == "measurement":
        return {"specified_by", "measured_by"}
    if kind == "mvp":
        return {"refined_by", "validated_by"}
    if kind == "scope":
        return {"guards_scope"}
    return {"specified_by"}


def coverage(data: TraceData, scope: str = "all") -> JsonObject:
    links_by_source = data.links_by_source()
    active_waivers = {
        criterion_id: waiver
        for waiver in data.waivers
        if waiver["status"] == "active"
        and datetime.fromisoformat(waiver["expires_at"].replace("Z", "+00:00"))
        > datetime.now(UTC)
        for criterion_id in waiver["criteria"]
    }
    rows: list[JsonObject] = []
    for requirement in data.requirements:
        if requirement["lifecycle"] != "active":
            continue
        if scope == "mvp" and not (
            "mvp" in requirement["applicability"]
            or requirement["kind"] in {"mvp", "security", "tech_security"}
        ):
            continue
        for criterion in requirement["criteria"]:
            if criterion.get("lifecycle", "active") != "active":
                continue
            kind = classification(criterion)
            links = links_by_source.get(criterion["id"], [])
            actual = {link["type"] for link in links if link["role"] == "primary"}
            required = required_link_types(requirement, criterion)
            modifier = "waived-active" if criterion["id"] in active_waivers else None
            if kind in ABSORBED_CLASSIFICATIONS:
                # Not a claim of its own: it is a field, bound or example inside
                # `covered_by`, and that criterion carries the verification.
                missing: list[str] = []
                status = "covered-by-parent"
            elif kind == "needs_rewrite":
                missing = []
                status = "needs-rewrite"
            else:
                missing = sorted(required - actual)
                status = "verifiable" if not missing else "specified"
            rows.append(
                {
                    "requirement_id": requirement["id"],
                    "criterion_id": criterion["id"],
                    "kind": requirement["kind"],
                    "classification": kind,
                    "covered_by": criterion.get("covered_by"),
                    "criticality": requirement["criticality"],
                    "status": status,
                    "missing": missing,
                    "modifier": modifier,
                }
            )
    blocking = [
        row
        for row in rows
        if row["missing"]
        and row["criticality"] == "must"
        and row["modifier"] != "waived-active"
    ]
    rewrite_queue = [row for row in rows if row["status"] == "needs-rewrite"]
    return {
        "scope": scope,
        "criteria": rows,
        "summary": {
            "total": len(rows),
            "verifiable": sum(row["status"] == "verifiable" for row in rows),
            "covered_by_parent": sum(
                row["status"] == "covered-by-parent" for row in rows
            ),
            "needs_rewrite": len(rewrite_queue),
            "blocking": len(blocking),
        },
    }
