from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.traceability.cli import _sanitize_evidence_text, main
from scripts.traceability.evidence import snapshot, validate_gate_results
from scripts.traceability.model import (
    TRACE_ROOT,
    TraceData,
    load_json,
    load_trace_data,
    markdown_anchors,
    sha256_path,
)
from scripts.traceability.render import rendered_documents
from scripts.traceability.validate import coverage, validate_selectors, validate_static


def _write_results(
    path: Path,
    *,
    commit: str,
    tree_state: str = "clean",
    gates_hash: str | None = None,
    status: str = "passed",
    gate_id: str = "GATE-BROWSER-E2E",
    environment: dict[str, str] | None = None,
) -> None:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    declared = next(
        gate.get("environment", [])
        for gate in load_json(TRACE_ROOT / "gates.json")["gates"]
        if gate["id"] == gate_id
    )
    reported = environment or {leg: "executed" for leg in declared}
    value = {
        "schema_version": 1,
        "run_id": "test-run",
        "commit": commit,
        "tree_state": tree_state,
        "generated_at": now,
        "gate_definition_sha256": gates_hash or sha256_path(TRACE_ROOT / "gates.json"),
        "runner": {
            "provider": "pytest",
            "os": "linux",
            "arch": "amd64",
            "profile": "test",
        },
        "gates": [
            {
                "id": gate_id,
                "started_at": now,
                "finished_at": now,
                "duration_ms": 1,
                "status": status,
                "command": ["pytest"],
                "exit_code": 0 if status == "passed" else None,
                "selectors": [],
                "environment": {"profile": "test", **reported},
                "artifacts": [],
                **(
                    {"skip_reason": "runner prerequisite absent"}
                    if status == "skipped"
                    else {}
                ),
            }
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def test_committed_registry_is_valid_and_covered() -> None:
    data = load_trace_data()
    assert validate_static(data) == []
    assert validate_selectors(data) == []
    result = coverage(data)
    # Pinned on purpose: every one of these numbers moving is a reviewable event.
    # Nothing is blocking and nothing is awaiting a rewrite, which is what lets
    # full release blocking stay on.
    # 2026-07-31: +8 for FR-SHELL-001 (the system terminal, ADR 0021), -1 for
    # SCOPE-011.AC-01 leaving the active set as `deprecated`/superseded.
    # 2026-07-31: +2 for FR-TERM-001.AC-13/AC-14 (plan/09) — the terminal filling
    # the height it was given, measured, and the page not scrolling because of a
    # second height formula. Both were true-by-intention before and asserted by
    # nothing, which is how the CLI panel spent three phases at half height.
    # 2026-08-01: +24 for port forwarding (plan/11, ADR 0022) — FR-TUNNEL-001 (8),
    # FR-TUNNEL-002 (5), FR-TUNNEL-003 (4), FR-TUNNEL-004 (6) and SCOPE-013.AC-01. All 24
    # are `verifiable`: every one of them has an automated assertion, which for this phase
    # is the point — the credential, the host key and the three-layer policy are the parts
    # that cannot be reviewed into correctness.
    # 2026-08-01: +9 for the privileged node posture (plan/12, ADR 0023) —
    # SEC-007.AC-02/AC-03, FR-RUNTIME-003.AC-02, FR-RUNTIME-004.AC-02/03/04,
    # FR-SHELL-001.AC-09 and FR-TERM-004.AC-06/AC-07. Two of the nine are not
    # `automated`: the installer's disclosure is `inspection` and browser scrolling is
    # `measurement`, because both are claims about a real machine — and FR-TERM-004.AC-04
    # ("at least 5000 lines") is the reason that distinction matters here. It had been
    # marked covered since P1 while tmux's default of 2000 lines quietly failed it, so
    # this phase treats "a number in a config file" and "the behaviour on a node" as
    # different things on purpose.
    # 2026-08-26: +26 for image drop and general workspace file upload
    # (FR-FILE-007/008 and related scope/security criteria). Twenty-four are
    # verifiable; FR-FILE-008.AC-04/AC-05 remain non-blocking verification gaps
    # reported by the coverage command above.
    # 2026-09-08: +11 for the visual refresh (plan/28, ADR 0027) — NFR-006's
    # eight criteria plus FR-TERM-001.AC-15/AC-16 and FR-TERM-005.AC-06. All
    # eleven are verifiable, so `blocking` stays 0.
    #
    # NFR-006 is worth a sentence of its own. Until this phase, none of the 115
    # requirements was about legibility, keyboard operation or visual theming —
    # so the five contrast failures measured in shipped code (a site-wide focus
    # ring at 2.85:1, the Terminate confirm button at 4.09:1, every input border
    # at 1.37:1, six of eight status badges under 4.5:1) were not waived. There
    # was simply nothing in this registry that could go red about them. That is
    # the gap these eight close, and it is why three of them are `measurement`
    # rather than `automated`: whether a theme switch keeps a live session, and
    # whether a page overflows at 390px, are claims about a real browser.
    # 2026-09-16: +7 that this ledger never recorded. NFR-007 (mobile operability,
    # plan/29, commit 22827cb) registered seven criteria without updating the census
    # below, so the gate has been failing on master since that merge. Writing the
    # correction as its own line rather than folding it into the next one is the
    # point: a running total that silently absorbs a discrepancy stops being a
    # census and becomes a number someone edits until the test passes.
    #
    # 2026-09-16: +10 for workspace file download (plan/30, ADR 0028) —
    # FR-FILE-011.AC-01..AC-10. All ten are verifiable, so `blocking` stays 0.
    # Four are `critical` risk and it is worth saying which, because they are not
    # the obvious ones: the sensitive policy in the read-out direction (AC-02), the
    # absence of range fields on the wire (AC-05), the octet-stream/nosniff response
    # (AC-06), and Central keeping no byte (AC-10). Getting the feature wrong makes
    # it not work; getting those four wrong sends a secret off the node or runs
    # workspace content in the console's own origin.
    assert result["summary"] == {
        "total": 468,
        "verifiable": 335,
        "covered_by_parent": 131,
        "needs_rewrite": 0,
        "blocking": 0,
    }


def test_baseline_debt_is_exactly_what_is_still_open() -> None:
    """The debt list is the gate's allowlist. If it drifts from the real gap set in
    either direction the gate stops meaning anything. It is empty now, so this also
    asserts that nothing has been quietly added back."""
    result = coverage(load_trace_data())
    open_now = {
        row["criterion_id"]
        for row in result["criteria"]
        if (row["missing"] and row["criticality"] == "must")
        or row["status"] == "needs-rewrite"
    }
    listed = {
        entry["criterion_id"]
        for entry in load_json(TRACE_ROOT / "baseline-debt.json")["entries"]
    }
    assert open_now == listed


def test_an_absorbed_bullet_names_a_criterion_that_carries_the_verification() -> None:
    """A data_shape or constraint bullet is excused from having its own test only
    because another criterion covers it. If that parent were itself absorbed, the
    claim would be excused by nothing."""
    data = load_trace_data()
    index = data.criterion_index()
    absorbed = [
        criterion
        for _, criterion in index.values()
        if criterion.get("classification") in {"constraint", "data_shape", "example"}
    ]
    assert absorbed, "the Pass B classification is missing"
    verified = {
        link["from"]
        for link in data.links
        if link["type"] == "verified_by" and link["role"] == "primary"
    }
    for criterion in absorbed:
        parent = index[criterion["covered_by"]][1]
        assert parent.get("classification", "criterion") == "criterion"
        assert criterion["covered_by"] in verified, criterion["id"]


def test_an_absorbed_bullet_may_not_keep_its_own_verification_claim() -> None:
    data = load_trace_data()
    absorbed = {
        criterion["id"]
        for _, criterion in data.criterion_index().values()
        if criterion.get("classification", "criterion") != "criterion"
    }
    claiming = [
        link["id"]
        for link in data.links
        if link["from"] in absorbed and link["type"] == "verified_by"
    ]
    assert claiming == []


def test_requirement_schema_rejects_unknown_fields() -> None:
    schema = load_json(TRACE_ROOT / "schema" / "requirements.schema.json")
    document = copy.deepcopy(load_json(TRACE_ROOT / "requirements.json"))
    document["requirements"][0]["invented"] = True
    errors = list(Draft202012Validator(schema).iter_errors(document))
    assert any(
        "Additional properties are not allowed" in error.message for error in errors
    )


def test_static_validation_finds_duplicate_id() -> None:
    original = load_trace_data()
    requirements = copy.deepcopy(original.requirements_doc)
    requirements["requirements"].append(copy.deepcopy(requirements["requirements"][0]))
    data = TraceData(
        requirements, original.links_doc, original.gates_doc, original.waivers_doc
    )
    findings = validate_static(data)
    assert any(item.code == "id.duplicate" for item in findings)


def test_static_validation_finds_missing_anchor() -> None:
    original = load_trace_data()
    requirements = copy.deepcopy(original.requirements_doc)
    requirements["requirements"][0]["criteria"][0]["source_anchor"] = "missing-anchor"
    data = TraceData(
        requirements, original.links_doc, original.gates_doc, original.waivers_doc
    )
    findings = validate_static(data)
    assert any(item.code == "anchor.missing" for item in findings)


def test_static_validation_rejects_target_path_escape() -> None:
    original = load_trace_data()
    links = copy.deepcopy(original.links_doc)
    candidate = next(
        item for item in links["links"] if item["target"]["kind"] == "code"
    )
    candidate["target"]["locator"] = "../outside.py"
    data = TraceData(
        original.requirements_doc, links, original.gates_doc, original.waivers_doc
    )
    findings = validate_static(data)
    assert any(item.code == "path.escape" for item in findings)


def test_static_validation_rejects_gate_working_directory_escape() -> None:
    original = load_trace_data()
    gates = copy.deepcopy(original.gates_doc)
    gates["gates"][0]["working_directory"] = "../outside"
    data = TraceData(
        original.requirements_doc, original.links_doc, gates, original.waivers_doc
    )
    findings = validate_static(data)
    assert any(item.code == "gate.path_escape" for item in findings)


def test_selector_validation_finds_missing_token() -> None:
    original = load_trace_data()
    links = copy.deepcopy(original.links_doc)
    candidate = next(
        item
        for item in links["links"]
        if item["target"]["kind"] in {"pytest", "gotest", "vitest", "playwright"}
    )
    candidate["target"]["locator"] += "#THIS_SELECTOR_DOES_NOT_EXIST"
    if candidate["target"]["kind"] == "pytest":
        candidate["target"]["locator"] = candidate["target"]["locator"].replace(
            "#", "::"
        )
    data = TraceData(
        original.requirements_doc, links, original.gates_doc, original.waivers_doc
    )
    findings = validate_selectors(data)
    assert any(item.code == "selector.unresolved" for item in findings)


def test_coverage_detects_removed_primary_link() -> None:
    original = load_trace_data()
    links = copy.deepcopy(original.links_doc)
    removed = next(
        item
        for item in links["links"]
        if item["from"] == "FR-AUTH-001.AC-01" and item["type"] == "implemented_by"
    )
    links["links"].remove(removed)
    data = TraceData(
        original.requirements_doc, links, original.gates_doc, original.waivers_doc
    )
    result = coverage(data)
    row = next(
        item
        for item in result["criteria"]
        if item["criterion_id"] == "FR-AUTH-001.AC-01"
    )
    assert row["missing"] == ["implemented_by"]
    assert result["summary"]["blocking"] == 1


def test_critical_criterion_cannot_be_waived() -> None:
    original = load_trace_data()
    waivers = copy.deepcopy(original.waivers_doc)
    now = datetime.now(UTC)
    waivers["waivers"].append(
        {
            "id": "WVR-2026-001",
            "criteria": ["SEC-001.AC-01"],
            "release": "test",
            "reason": "test",
            "impact": "test",
            "compensating_controls": ["test"],
            "owner": "security",
            "approvers": ["security", "release"],
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "revisit_trigger": "test",
            "status": "active",
        }
    )
    requirements = copy.deepcopy(original.requirements_doc)
    criterion = next(
        criterion
        for requirement in requirements["requirements"]
        if requirement["id"] == "SEC-001"
        for criterion in requirement["criteria"]
        if criterion["id"] == "SEC-001.AC-01"
    )
    criterion["risk"] = "critical"
    data = TraceData(requirements, original.links_doc, original.gates_doc, waivers)
    findings = validate_static(data)
    assert any(item.code == "waiver.non_waivable" for item in findings)


def test_markdown_anchors_resolve_criterion_text() -> None:
    anchors = markdown_anchors(Path("research/prd.md"))
    assert anchors["fr-auth-001-ac-01"] == "使用者可使用有效帳號登入。"
    assert anchors["mvp-ac-20-ac-01"] == "所有重要操作均有 Audit Log。"


def test_renderer_is_deterministic() -> None:
    data = load_trace_data()
    first = rendered_documents(data)
    second = rendered_documents(data)
    assert first == second
    assert all(content.endswith("\n") for content in first.values())


def test_gate_results_reject_stale_commit_and_dirty_tree(tmp_path: Path) -> None:
    requested = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(path, commit="b" * 40, tree_state="dirty")
    errors = validate_gate_results(path, commit=requested)
    assert any("stale commit" in error for error in errors)
    assert any("clean tree" in error for error in errors)


def test_gate_results_reject_definition_hash_mismatch(tmp_path: Path) -> None:
    commit = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(path, commit=commit, gates_hash="0" * 64)
    errors = validate_gate_results(path, commit=commit)
    assert any("definition hash" in error for error in errors)


def test_gate_results_reject_missing_artifact(tmp_path: Path) -> None:
    commit = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(path, commit=commit)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["gates"][0]["artifacts"] = [
        {"path": "missing.txt", "size": 1, "sha256": "0" * 64}
    ]
    path.write_text(json.dumps(value), encoding="utf-8")
    errors = validate_gate_results(path, commit=commit)
    assert any("missing artifact" in error for error in errors)


def test_gate_results_reject_artifact_path_escape(tmp_path: Path) -> None:
    commit = "a" * 40
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("not evidence", encoding="utf-8")
    path = tmp_path / "gate-results.json"
    _write_results(path, commit=commit)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["gates"][0]["artifacts"] = [
        {
            "path": "../outside.txt",
            "size": outside.stat().st_size,
            "sha256": "0" * 64,
        }
    ]
    path.write_text(json.dumps(value), encoding="utf-8")
    errors = validate_gate_results(path, commit=commit)
    assert any("escapes evidence root" in error for error in errors)


def test_required_skip_never_becomes_verified(tmp_path: Path) -> None:
    commit = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(path, commit=commit, status="skipped")
    value = snapshot(load_trace_data(), path, commit=commit)
    mvp_rows = [
        row
        for row in value["criteria"]
        if row["criterion_id"].startswith("MVP-")
        and "GATE-BROWSER-E2E" in row["required_gates"]
    ]
    assert mvp_rows
    assert all(row["verdict"] == "skipped" for row in mvp_rows)
    assert value["verdict"] == "blocked"


def test_passing_gate_without_executed_selector_is_not_verified(tmp_path: Path) -> None:
    commit = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(path, commit=commit)
    value = snapshot(load_trace_data(), path, commit=commit)
    mvp_rows = [
        row
        for row in value["criteria"]
        if row["criterion_id"].startswith("MVP-")
        and "GATE-BROWSER-E2E" in row["required_gates"]
    ]
    assert mvp_rows
    assert all(row["verdict"] == "selector-unproven" for row in mvp_rows)


def test_current_result_schema_has_explicit_utc_instants() -> None:
    schema = load_json(TRACE_ROOT / "schema" / "gate-results.schema.json")
    assert schema["properties"]["generated_at"]["format"] == "date-time"


def test_evidence_text_redacts_tokens_and_private_home() -> None:
    value = _sanitize_evidence_text(
        "Bearer secret enroll_abcdef eyJabc.def.ghi /home/neil/private"
    )
    assert "secret" not in value
    assert "abcdef" not in value
    assert "eyJabc" not in value
    assert "/home/neil/" not in value


def test_bootstrap_requires_explicit_force() -> None:
    assert main(["bootstrap"]) == 2


def test_an_expired_waiver_stops_excusing_its_criterion() -> None:
    """Failure injection 9 from plan/06 §2. A waiver whose window has closed must
    stop suppressing the gap on its own, without anyone remembering to revoke it."""
    original = load_trace_data()
    criterion_id = "FR-FILE-006.AC-04"
    now = datetime.now(UTC)

    # Manufacture the gap rather than borrowing one from the committed registry:
    # real gaps are meant to reach zero, and this test must keep working when
    # they do.
    links = copy.deepcopy(original.links_doc)
    links["links"] = [
        link
        for link in links["links"]
        if not (link["from"] == criterion_id and link["type"] == "verified_by")
    ]

    def waivers(created: datetime, expires: datetime) -> dict:
        return {
            "schema_version": 1,
            "waivers": [
                {
                    "id": "WVR-2026-900",
                    "criteria": [criterion_id],
                    "release": "test",
                    "reason": "injection fixture",
                    "impact": "none, this waiver only exists inside the test",
                    "compensating_controls": ["none"],
                    "owner": "test-infra",
                    "approvers": ["test-infra", "release"],
                    "created_at": created.isoformat().replace("+00:00", "Z"),
                    "expires_at": expires.isoformat().replace("+00:00", "Z"),
                    "revisit_trigger": "never, it is a fixture",
                    "status": "active",
                }
            ],
        }

    def row_for(doc: dict) -> dict:
        data = TraceData(original.requirements_doc, links, original.gates_doc, doc)
        return next(
            item
            for item in coverage(data)["criteria"]
            if item["criterion_id"] == criterion_id
        )

    live = row_for(waivers(now - timedelta(days=1), now + timedelta(days=30)))
    assert live["modifier"] == "waived-active"

    expired = row_for(waivers(now - timedelta(days=60), now - timedelta(days=1)))
    assert expired["modifier"] is None
    assert expired["missing"] == ["verified_by"]


def test_a_browser_matrix_leg_that_never_ran_is_not_verified(tmp_path: Path) -> None:
    """Failure injection 7 from plan/06 §2. A green Chromium-only run must not
    satisfy the criteria that a three-browser gate claims to cover."""
    commit = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(
        path,
        commit=commit,
        environment={"chromium": "executed", "firefox": "skipped", "webkit": "skipped"},
    )
    assert validate_gate_results(path, commit=commit) == []

    data = load_trace_data()
    value = snapshot(data, path, commit=commit)
    incomplete = [
        row
        for row in value["criteria"]
        if "GATE-BROWSER-E2E" in row["required_gates"]
        and row["incomplete_environments"]
    ]
    assert incomplete
    assert all(row["verdict"] != "verified" for row in incomplete)
    assert any(
        "webkit" in leg for row in incomplete for leg in row["incomplete_environments"]
    )


def test_a_result_must_account_for_every_declared_matrix_leg(tmp_path: Path) -> None:
    commit = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(path, commit=commit, environment={"chromium": "executed"})
    errors = validate_gate_results(path, commit=commit)
    assert any("does not report environment leg firefox" in error for error in errors)
    assert any("does not report environment leg webkit" in error for error in errors)


def test_a_result_may_not_invent_an_environment_the_gate_does_not_declare(
    tmp_path: Path,
) -> None:
    commit = "a" * 40
    path = tmp_path / "gate-results.json"
    _write_results(
        path,
        commit=commit,
        environment={
            "chromium": "executed",
            "firefox": "executed",
            "webkit": "executed",
            "internet-explorer": "executed",
        },
    )
    errors = validate_gate_results(path, commit=commit)
    assert any("does not declare" in error for error in errors)


def test_shards_from_different_commits_are_not_merged(tmp_path: Path) -> None:
    """plan/06 §4: a verdict assembled from two revisions is worse than none."""
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    _write_results(first, commit="a" * 40, gate_id="GATE-BACKEND-UNIT")
    _write_results(second, commit="b" * 40, gate_id="GATE-DAEMON-RACE")
    out = tmp_path / "merged.json"
    assert main(["merge", str(first), str(second), "--out", str(out)]) == 4
    assert not out.exists()


def test_shards_merge_into_one_result_per_gate(tmp_path: Path) -> None:
    commit = "a" * 40
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    _write_results(first, commit=commit, gate_id="GATE-BACKEND-UNIT")
    _write_results(second, commit=commit, gate_id="GATE-DAEMON-RACE")
    out = tmp_path / "merged.json"
    assert main(["merge", str(first), str(second), "--out", str(out)]) == 0
    merged = load_json(out)
    assert [gate["id"] for gate in merged["gates"]] == [
        "GATE-BACKEND-UNIT",
        "GATE-DAEMON-RACE",
    ]
    assert validate_gate_results(out, commit=commit) == []


def test_the_same_gate_may_not_be_reported_twice_in_one_run(tmp_path: Path) -> None:
    commit = "a" * 40
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    _write_results(first, commit=commit, gate_id="GATE-BACKEND-UNIT")
    _write_results(second, commit=commit, gate_id="GATE-BACKEND-UNIT")
    out = tmp_path / "merged.json"
    assert main(["merge", str(first), str(second), "--out", str(out)]) == 4


def test_a_deprecated_criterion_must_name_its_replacement() -> None:
    """Otherwise the cheapest way to clear a coverage gap is to deprecate the
    criterion, and the requirement disappears instead of being answered."""
    original = load_trace_data()
    requirements = copy.deepcopy(original.requirements_doc)
    criterion = requirements["requirements"][0]["criteria"][0]
    criterion["lifecycle"] = "deprecated"
    criterion["review"] = {
        "classified_by": "product",
        "classified_at": "2026-07-27",
        "rationale": "injection fixture",
    }
    data = TraceData(
        requirements, original.links_doc, original.gates_doc, original.waivers_doc
    )
    findings = validate_static(data)
    assert any(item.code == "criterion.unreplaced" for item in findings)


def test_every_deprecated_criterion_in_the_registry_is_replaced_and_explained() -> None:
    data = load_trace_data()
    deprecated = [
        criterion
        for _, criterion in data.criterion_index().values()
        if criterion.get("lifecycle") == "deprecated"
    ]
    assert deprecated, "the PRD withdrawals are missing from the registry"
    superseded = {
        link["target"]["locator"] for link in data.links if link["type"] == "supersedes"
    }
    for criterion in deprecated:
        assert criterion["id"] in superseded
        assert criterion["review"]["rationale"]
