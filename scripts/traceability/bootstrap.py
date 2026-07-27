from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import REPO_ROOT, TRACE_ROOT, dump_json

PRIMARY_HEADING = re.compile(
    r"^## (FR-[A-Z]+-[0-9]{3}|SEC-[0-9]{3}|NFR-[0-9]{3}) (.+)$"
)
PRIMARY_ANCHOR = re.compile(
    r'^<a id="(?:fr-[a-z]+-[0-9]{3}|sec-[0-9]{3}|nfr-[0-9]{3})'
    r'(?:-ac-[0-9]{2})?"></a>$'
)

FAMILY: dict[str, dict[str, str]] = {
    "AUTH": {
        "owner": "central",
        "plan": "plan/02/02-auth-rbac.md",
        "code": "backend/app/services/auth.py",
        "test_kind": "pytest",
        "test": "backend/tests/db/test_auth_api.py",
        "gate": "GATE-BACKEND-DB",
    },
    "NODE": {
        "owner": "central",
        "plan": "plan/02/05-registry-node-status.md",
        "code": "backend/app/services/nodes.py",
        "test_kind": "pytest",
        "test": "backend/tests/db/test_node_api.py",
        "gate": "GATE-BACKEND-DB",
    },
    "INSTALL": {
        "owner": "daemon",
        "plan": "plan/02/06-installer-artifacts.md",
        "code": "daemon/internal/install",
        "test_kind": "gotest",
        "test": "daemon/internal/install",
        "gate": "GATE-DAEMON-RACE",
    },
    "RUNTIME": {
        "owner": "daemon",
        "plan": "plan/02/04-daemon-connection.md",
        "code": "daemon/internal/runtime",
        "test_kind": "gotest",
        "test": "daemon/internal/runtime",
        "gate": "GATE-DAEMON-RACE",
    },
    "WORKSPACE": {
        "owner": "daemon",
        "plan": "plan/04/01-path-security-and-protocol.md",
        "code": "daemon/internal/workspace",
        "test_kind": "gotest",
        "test": "daemon/internal/workspace",
        "gate": "GATE-DAEMON-RACE",
    },
    "SESSION": {
        "owner": "central",
        "plan": "plan/03/01-session-domain-api.md",
        "code": "backend/app/services/sessions.py",
        "test_kind": "pytest",
        "test": "backend/tests/db/test_sessions_api.py",
        "gate": "GATE-BACKEND-DB",
    },
    "TERM": {
        "owner": "frontend",
        "plan": "plan/03/06-xterm-integration.md",
        "code": "frontend/src/composables/useTerminalSession.ts",
        "test_kind": "playwright",
        "test": "frontend/tests/e2e/session.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    "FILE": {
        "owner": "daemon",
        "plan": "plan/04/03-read-only-file-policy.md",
        "code": "daemon/internal/files",
        "test_kind": "playwright",
        "test": "frontend/tests/e2e/files.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    "CONN": {
        "owner": "daemon",
        "plan": "plan/02/04-daemon-connection.md",
        "code": "daemon/internal/connection",
        "test_kind": "gotest",
        "test": "daemon/internal/connection",
        "gate": "GATE-DAEMON-RACE",
    },
}

SEC_CODE = {
    "SEC-001": "daemon/internal/workspace",
    "SEC-002": "daemon/internal/protocol/codec.go",
    "SEC-003": "backend/app/security/tokens.py",
    "SEC-004": "daemon/internal/files/policy.go",
    "SEC-005": "deploy/nginx/nginx.conf",
    "SEC-006": "backend/app/services/audit.py",
    "SEC-007": "daemon/internal/install/systemd.go",
}

REQUIREMENT_OVERRIDES: dict[str, dict[str, str]] = {
    "FR-AUTH-002": {
        "code": "backend/app/services/rbac.py",
        "test_kind": "pytest",
        "test": "backend/tests/db/test_permission_matrix.py",
        "gate": "GATE-BACKEND-DB",
    },
    "FR-NODE-001": {
        "test_kind": "pytest",
        "test": "backend/tests/db/test_node_registration.py",
        "gate": "GATE-BACKEND-DB",
    },
    "FR-NODE-002": {
        "code": "backend/app/services/registry.py",
        "test_kind": "pytest",
        "test": "backend/tests/test_registry.py",
        "gate": "GATE-BACKEND-UNIT",
    },
    "FR-NODE-005": {
        "test_kind": "pytest",
        "test": "backend/tests/test_node_guard.py",
        "gate": "GATE-BACKEND-UNIT",
    },
    "FR-INSTALL-001": {
        "code": "backend/app/services/enrollment.py",
        "test_kind": "pytest",
        "test": "backend/tests/db/test_enrollment_api.py",
        "gate": "GATE-BACKEND-DB",
    },
    "FR-WORKSPACE-004": {
        "code": "backend/app/services/favorites.py",
        "test_kind": "pytest",
        "test": "backend/tests/db/test_favorites_api.py",
        "gate": "GATE-BACKEND-DB",
    },
    "FR-WORKSPACE-005": {
        "code": "backend/app/services/favorites.py",
        "test_kind": "pytest",
        "test": "backend/tests/db/test_favorites_api.py",
        "gate": "GATE-BACKEND-DB",
    },
    "FR-SESSION-002": {
        "test_kind": "pytest",
        "test": "backend/tests/test_session_state.py",
        "gate": "GATE-BACKEND-UNIT",
    },
    "FR-SESSION-006": {
        "code": "daemon/internal/session",
        "test_kind": "gotest",
        "test": "daemon/internal/session",
        "gate": "GATE-DAEMON-INTEGRATION",
    },
}

SEC_VERIFY: dict[str, dict[str, str]] = {
    "SEC-001": {
        "test_kind": "gotest",
        "test": "daemon/internal/workspace",
        "gate": "GATE-DAEMON-RACE",
    },
    "SEC-002": {
        "test_kind": "pytest",
        "test": "backend/tests/contract/test_contract.py",
        "gate": "GATE-CONTRACT-CROSS-LANGUAGE",
    },
    "SEC-003": {
        "test_kind": "pytest",
        "test": "backend/tests/test_security.py",
        "gate": "GATE-SECURITY",
    },
    "SEC-004": {
        "test_kind": "gotest",
        "test": "daemon/internal/files",
        "gate": "GATE-DAEMON-RACE",
    },
    "SEC-005": {
        "test_kind": "scenario",
        "test": "scripts/p4/verify-edge.sh",
        "gate": "GATE-OPERATIONS",
    },
    "SEC-006": {
        "test_kind": "pytest",
        "test": "backend/tests/db/test_audit_coverage.py",
        "gate": "GATE-SECURITY",
    },
    "SEC-007": {
        "test_kind": "gotest",
        "test": "daemon/internal/install",
        "gate": "GATE-DAEMON-RACE",
    },
}

NFR_VERIFY: dict[str, dict[str, str]] = {
    "NFR-001": {
        "target": "scripts/p4/load/capacity.py",
        "gate": "GATE-PERFORMANCE",
    },
    "NFR-002": {
        "target": "daemon/internal/session",
        "gate": "GATE-DAEMON-INTEGRATION",
    },
    "NFR-003": {
        "target": "scripts/p4/load/capacity.py",
        "gate": "GATE-CAPACITY",
    },
    "NFR-004": {
        "target": "scripts/p4/evidence.sh",
        "gate": "GATE-OPERATIONS",
    },
    "NFR-005": {
        "target": ".github/workflows/p4.yml",
        "gate": "GATE-OPERATIONS",
    },
}

MVP_VALIDATION: dict[int, dict[str, str]] = {
    1: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/nodes.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    2: {"kind": "scenario", "target": "deploy/install.sh", "gate": "GATE-OPERATIONS"},
    3: {
        "kind": "gotest",
        "target": "daemon/internal/install",
        "gate": "GATE-OPERATIONS",
    },
    4: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/nodes.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    5: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/nodes.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    6: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/session.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    7: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/session.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    8: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/files.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    9: {
        "kind": "gotest",
        "target": "daemon/internal/workspace",
        "gate": "GATE-DAEMON-INTEGRATION",
    },
    10: {
        "kind": "gotest",
        "target": "daemon/internal/session",
        "gate": "GATE-DAEMON-INTEGRATION",
    },
    11: {
        "kind": "manual",
        "target": "live-cli-approval",
        "gate": "GATE-MANUAL-LIVE-CLI",
    },
    12: {
        "kind": "manual",
        "target": "live-cli-approval",
        "gate": "GATE-MANUAL-LIVE-CLI",
    },
    13: {
        "kind": "gotest",
        "target": "daemon/internal/session",
        "gate": "GATE-DAEMON-INTEGRATION",
    },
    14: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/session.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    15: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/files.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    16: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/files.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    17: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/files.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    18: {
        "kind": "pytest",
        "target": "backend/tests/db/test_sessions_api.py",
        "gate": "GATE-BACKEND-DB",
    },
    19: {
        "kind": "playwright",
        "target": "frontend/tests/e2e/session.spec.ts",
        "gate": "GATE-BROWSER-E2E",
    },
    20: {
        "kind": "pytest",
        "target": "backend/tests/db/test_audit_coverage.py",
        "gate": "GATE-SECURITY",
    },
}

MVP_TO_REQUIREMENT = {
    1: "FR-INSTALL-001",
    2: "FR-INSTALL-002",
    3: "FR-INSTALL-003",
    4: "FR-NODE-002",
    5: "FR-RUNTIME-001",
    6: "FR-NODE-003",
    7: "FR-RUNTIME-002",
    8: "FR-WORKSPACE-002",
    9: "FR-WORKSPACE-003",
    10: "FR-SESSION-001",
    11: "FR-TERM-001",
    12: "FR-TERM-001",
    13: "FR-SESSION-006",
    14: "FR-SESSION-006",
    15: "FR-FILE-001",
    16: "FR-FILE-002",
    17: "FR-FILE-005",
    18: "FR-NODE-002",
    19: "FR-SESSION-005",
    20: "SEC-006",
}

TECH_TO_REQUIREMENT = {
    1: "SEC-005",
    2: "SEC-007",
    3: "SEC-003",
    4: "SEC-003",
    5: "SEC-001",
    6: "SEC-001",
    7: "SEC-002",
    8: "SEC-006",
    9: "SEC-004",
    10: "SEC-006",
    11: "FR-AUTH-002",
    12: "FR-INSTALL-003",
    13: "SEC-003",
    14: "NFR-003",
    15: "NFR-003",
}


@dataclass
class RequirementSeed:
    id: str
    title: str
    source_path: str
    source_anchor: str
    criterion_anchors: list[str]


def _clean_lines(path: Path, anchor_pattern: re.Pattern[str]) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not anchor_pattern.match(line.strip())
    ]


def _outside_fence(lines: list[str]) -> list[bool]:
    flags: list[bool] = []
    fenced = False
    for line in lines:
        if line.strip().startswith("```"):
            fenced = not fenced
            flags.append(False)
        else:
            flags.append(not fenced)
    return flags


def _criterion_indices(lines: list[str], start: int, end: int) -> list[int]:
    outside = _outside_fence(lines[start:end])
    block = lines[start:end]
    marker = next(
        (i for i, line in enumerate(block) if line.strip() == "驗收條件："), None
    )
    candidates: list[int] = []
    if marker is None:
        for offset, line in enumerate(block):
            stripped = line.strip()
            if (
                outside[offset]
                and stripped
                and stripped != "---"
                and not stripped.startswith("#")
            ):
                candidates.append(start + offset)
                break
    table_body = False
    for offset, line in enumerate(block):
        if not outside[offset]:
            continue
        if re.match(r"^\* .+", line) or re.match(r"^[0-9]+\. .+", line):
            if marker is None or offset > marker:
                candidates.append(start + offset)
        if marker is None and re.match(r"^\|\s*-+", line):
            table_body = True
            continue
        if marker is None and table_body and line.startswith("|"):
            candidates.append(start + offset)
        elif table_body and line.strip() and not line.startswith("|"):
            table_body = False
    if candidates:
        return sorted(set(candidates))
    for offset, line in enumerate(block):
        stripped = line.strip()
        if (
            outside[offset]
            and stripped
            and stripped != "---"
            and not stripped.startswith("#")
        ):
            return [start + offset]
    raise ValueError(f"no criterion candidate after line {start + 1}")


def _inject_primary(path: Path) -> list[RequirementSeed]:
    lines = _clean_lines(path, PRIMARY_ANCHOR)
    headings = [
        (index, match.group(1), match.group(2))
        for index, line in enumerate(lines)
        if (match := PRIMARY_HEADING.match(line))
    ]
    insertions: dict[int, list[str]] = {}
    seeds: list[RequirementSeed] = []
    for index, requirement_id, title in headings:
        end = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if re.match(r"^#{1,2}\s+", lines[candidate])
            ),
            len(lines),
        )
        requirement_anchor = requirement_id.lower()
        insertions.setdefault(index, []).append(f'<a id="{requirement_anchor}"></a>')
        candidates = _criterion_indices(lines, index + 1, end)
        anchors: list[str] = []
        for number, candidate in enumerate(candidates, 1):
            anchor = f"{requirement_anchor}-ac-{number:02d}"
            anchors.append(anchor)
            insertions.setdefault(candidate, []).append(f'<a id="{anchor}"></a>')
        seeds.append(
            RequirementSeed(
                id=requirement_id,
                title=title,
                source_path=path.relative_to(REPO_ROOT).as_posix(),
                source_anchor=requirement_anchor,
                criterion_anchors=anchors,
            )
        )
    output: list[str] = []
    for index, line in enumerate(lines):
        output.extend(insertions.get(index, []))
        output.append(line)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return seeds


def _inject_numbered_section(
    path: Path,
    *,
    start_heading: str,
    end_heading: str,
    prefix: str,
    digits: int,
) -> list[RequirementSeed]:
    prefix_pattern = re.compile(
        rf'^<a id="{re.escape(prefix.lower())}-[0-9]{{{digits}}}'
        rf'(?:-ac-[0-9]{{2}})?"></a>$'
    )
    lines = _clean_lines(path, prefix_pattern)
    start = lines.index(start_heading)
    end = lines.index(end_heading)
    outside = _outside_fence(lines)
    numbered = [
        (index, match.group(1), match.group(2))
        for index in range(start + 1, end)
        if outside[index] and (match := re.match(r"^([0-9]+)\. (.+)", lines[index]))
    ]
    insertions: dict[int, list[str]] = {}
    seeds: list[RequirementSeed] = []
    for index, raw_number, title in numbered:
        number = int(raw_number)
        item_id = f"{prefix}-{number:0{digits}d}".upper()
        anchor = item_id.lower()
        criterion_anchor = f"{anchor}-ac-01"
        insertions[index] = [
            f'<a id="{anchor}"></a>',
            f'<a id="{criterion_anchor}"></a>',
        ]
        seeds.append(
            RequirementSeed(
                id=item_id,
                title=title,
                source_path=path.relative_to(REPO_ROOT).as_posix(),
                source_anchor=anchor,
                criterion_anchors=[criterion_anchor],
            )
        )
    output: list[str] = []
    for index, line in enumerate(lines):
        output.extend(insertions.get(index, []))
        output.append(line)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return seeds


def _owner_for(requirement_id: str) -> str:
    if requirement_id.startswith("FR-"):
        return FAMILY[requirement_id.split("-")[1]]["owner"]
    if requirement_id.startswith(("SEC-", "TECH-SEC-")):
        return "security"
    if requirement_id.startswith("NFR-"):
        return "operations"
    if requirement_id.startswith("MVP-"):
        return "release"
    return "product"


def _kind_for(requirement_id: str) -> str:
    if requirement_id.startswith("FR-"):
        return "functional"
    if requirement_id.startswith("SEC-"):
        return "security"
    if requirement_id.startswith("NFR-"):
        return "non_functional"
    if requirement_id.startswith("MVP-"):
        return "mvp"
    if requirement_id.startswith("TECH-"):
        return "tech_security"
    return "scope"


def _requirement_entry(seed: RequirementSeed) -> dict[str, Any]:
    kind = _kind_for(seed.id)
    profile = {
        "functional": "automated",
        "security": "automated",
        "non_functional": "measurement",
        "mvp": "automated",
        "tech_security": "automated",
        "scope": "inspection",
    }[kind]
    risk = "high" if kind in {"security", "tech_security", "scope"} else "medium"
    return {
        "id": seed.id,
        "kind": kind,
        "title": seed.title,
        "source": {"path": seed.source_path, "anchor": seed.source_anchor},
        "lifecycle": "active",
        "applicability": ["mvp"] if kind != "scope" else ["all"],
        "criticality": "must",
        "owner": _owner_for(seed.id),
        "criteria": [
            {
                "id": f"{seed.id}.AC-{index:02d}",
                "source_anchor": anchor,
                "verification_profile": profile,
                "risk": risk,
            }
            for index, anchor in enumerate(seed.criterion_anchors, 1)
        ],
    }


def _link_id(criterion_id: str, link_type: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "-", criterion_id.upper()).strip("-")
    return f"LNK-{normalized}-{link_type.upper().replace('_', '-')}"


def _link(
    criterion_id: str,
    link_type: str,
    kind: str,
    locator: str,
    owner: str,
    *,
    gate_id: str | None = None,
    assertion: str,
    role: str = "primary",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": _link_id(criterion_id, link_type),
        "from": criterion_id,
        "type": link_type,
        "target": {"kind": kind, "locator": locator},
        "role": role,
        "assertion": assertion,
        "owner": owner,
        "applicability": ["mvp"],
    }
    if gate_id:
        value["gate_id"] = gate_id
    return value


def _links_for(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    requirement_id = requirement["id"]
    kind = requirement["kind"]
    owner = requirement["owner"]
    for criterion in requirement["criteria"]:
        criterion_id = criterion["id"]
        if kind == "functional":
            family = {
                **FAMILY[requirement_id.split("-")[1]],
                **REQUIREMENT_OVERRIDES.get(requirement_id, {}),
            }
            links.extend(
                [
                    _link(
                        criterion_id,
                        "planned_by",
                        "plan",
                        family["plan"],
                        owner,
                        assertion="Delivery work package for this functional criterion.",
                    ),
                    _link(
                        criterion_id,
                        "specified_by",
                        "source",
                        "research/tech.md",
                        owner,
                        assertion="Technical design constraining this functional criterion.",
                    ),
                    _link(
                        criterion_id,
                        "implemented_by",
                        "code",
                        family["code"],
                        owner,
                        assertion="Primary implementation surface for this criterion.",
                    ),
                    _link(
                        criterion_id,
                        "verified_by",
                        family["test_kind"],
                        family["test"],
                        owner,
                        gate_id=family["gate"],
                        assertion="Existing automated suite supporting this requirement family; exact assertion mapping remains baseline debt.",
                        role="supporting",
                    ),
                ]
            )
        elif kind in {"security", "tech_security"}:
            source_requirement = (
                requirement_id
                if kind == "security"
                else TECH_TO_REQUIREMENT[int(requirement_id.rsplit("-", 1)[1])]
            )
            if source_requirement in SEC_CODE:
                code = SEC_CODE[source_requirement]
            elif source_requirement.startswith("FR-"):
                code = FAMILY[source_requirement.split("-")[1]]["code"]
            else:
                code = "scripts/p4/load/capacity.py"
            verification = SEC_VERIFY.get(
                source_requirement,
                {
                    "test_kind": "pytest",
                    "test": "backend/tests/test_security.py",
                    "gate": "GATE-SECURITY",
                },
            )
            links.extend(
                [
                    _link(
                        criterion_id,
                        "specified_by",
                        "adr" if kind == "tech_security" else "source",
                        "docs/adr/0019-requirement-traceability.md"
                        if kind == "tech_security"
                        else "research/tech.md",
                        "security",
                        assertion="Security design and release baseline.",
                    ),
                    _link(
                        criterion_id,
                        "implemented_by",
                        "code",
                        code,
                        "security",
                        assertion="Primary enforcement surface for this security criterion.",
                    ),
                    _link(
                        criterion_id,
                        "verified_by",
                        verification["test_kind"],
                        verification["test"],
                        "security",
                        gate_id=verification["gate"],
                        assertion="Existing negative/adversarial suite supporting this control; exact assertion mapping remains baseline debt.",
                        role="supporting",
                    ),
                ]
            )
        elif kind == "non_functional":
            verification = NFR_VERIFY[requirement_id]
            links.extend(
                [
                    _link(
                        criterion_id,
                        "specified_by",
                        "source",
                        "research/tech.md",
                        "operations",
                        assertion="NFR threshold and operational design.",
                    ),
                    _link(
                        criterion_id,
                        "measured_by",
                        "scenario",
                        verification["target"],
                        "operations",
                        gate_id=verification["gate"],
                        assertion="Environment-qualified NFR measurement or operational gate.",
                    ),
                ]
            )
        elif kind == "mvp":
            number = int(requirement_id.rsplit("-", 1)[1])
            validation = MVP_VALIDATION[number]
            links.extend(
                [
                    _link(
                        criterion_id,
                        "refined_by",
                        "requirement",
                        MVP_TO_REQUIREMENT[number],
                        "release",
                        assertion="Underlying product or security requirement.",
                    ),
                    _link(
                        criterion_id,
                        "validated_by",
                        validation["kind"],
                        validation["target"],
                        "release",
                        gate_id=validation["gate"],
                        assertion="Release journey evidence for this MVP condition.",
                    ),
                ]
            )
        else:
            links.append(
                _link(
                    criterion_id,
                    "guards_scope",
                    "plan",
                    "plan/05/00-execution-plan.md",
                    "product",
                    assertion="Reviewed MVP non-goal and scope guard.",
                )
            )
    return links


def bootstrap() -> dict[str, int]:
    prd = REPO_ROOT / "research" / "prd.md"
    tech = REPO_ROOT / "research" / "tech.md"
    primary = _inject_primary(prd)
    scope = _inject_numbered_section(
        prd,
        start_heading="# 4. 非目標",
        end_heading="# 5. 使用者角色",
        prefix="SCOPE",
        digits=3,
    )
    mvp = _inject_numbered_section(
        prd,
        start_heading="# 19. MVP 驗收條件",
        end_heading="# 20. 風險與對策",
        prefix="MVP-AC",
        digits=2,
    )
    tech_security = _inject_numbered_section(
        tech,
        start_heading="# 23. 安全基準",
        end_heading="# 24. MVP 技術範圍",
        prefix="TECH-SEC",
        digits=2,
    )
    requirements = [
        _requirement_entry(seed) for seed in primary + mvp + tech_security + scope
    ]
    requirements.sort(key=lambda item: item["id"])
    links = [link for requirement in requirements for link in _links_for(requirement)]
    links.sort(key=lambda item: item["id"])
    (TRACE_ROOT / "requirements.json").write_text(
        dump_json({"schema_version": 1, "requirements": requirements}),
        encoding="utf-8",
    )
    (TRACE_ROOT / "links.json").write_text(
        dump_json({"schema_version": 1, "links": links}),
        encoding="utf-8",
    )
    return {
        "requirements": len(requirements),
        "criteria": sum(len(item["criteria"]) for item in requirements),
        "links": len(links),
    }


if __name__ == "__main__":
    print(json.dumps(bootstrap(), sort_keys=True))
