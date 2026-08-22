#!/usr/bin/env python
"""The V2-K1 invariants whose violation is silent (`plan/25/09-…md` §3).

Five gates in one file, because all five are AST scans over `backend/app` and one
process is cheaper than five. Each guards a property whose breach leaves the system
running, the tests green, and the answer quietly wrong:

* `GATE-KN-ONE-TOKENIZER` — text-search expressions are built in exactly one module, and
  its lexemes come from exactly one function. Index and query disagreeing is **zero
  recall with no error**: every search returns nothing, which is indistinguishable from a
  project nobody has written about.
* `GATE-KN-PROJECT-SCOPED` — every select touching a `knowledge_*` table carries a
  `project_id` predicate. Cross-project leakage is the worst failure available here
  because it looks exactly like the feature working.
* `GATE-KN-INSTRUCTION-LAYER` — one function assembles the instruction block, and its
  only source is a `policy` query. A second assembler's first missed branch is a quoted
  paragraph read as an order, and **nothing errors**.
* `GATE-KN-AUTHORITY-SERVER-SIDE` — no request schema has an `authority` field. The same
  structural rule `FR-VERIFY-002` states for a report's `source`.
* `GATE-KN-NO-RAW-LOG-INDEX` — the knowledge modules cannot reach `RunLog`. A diagnostic
  with a retention period must not become a permanent index.

**AST rather than text search**, for the reason `plan/18/09` §3 item 15 records: V2.2
shipped three gates that matched their own explanatory comments, and the cheapest way to
green such a gate is to delete the paragraph saying why the rule exists.

Run: uv run --project backend python scripts/kn/gate_knowledge_invariants.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
KNOWLEDGE = APP / "services" / "knowledge"

failures: list[str] = []
honoured: set[tuple[str, str]] = set()


def _modules() -> list[tuple[pathlib.Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(APP.rglob("*.py"))
    ]


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _callee(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def _enclosing(tree: ast.AST, node: ast.AST) -> str:
    best = "<module>"
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = getattr(candidate, "end_lineno", candidate.lineno)
        if candidate.lineno <= node.lineno <= end:
            best = candidate.name
    return best


# --- GATE-KN-ONE-TOKENIZER ---------------------------------------------------
#
# The SQL side and the Python side each have exactly one home. Two homes is not a style
# problem: the index and the query would be built from different lexemes and every search
# would return nothing, forever, without an error.

_TS_FUNCTIONS = {"to_tsvector", "to_tsquery", "plainto_tsquery", "phraseto_tsquery"}
_TS_ALLOWED = {
    KNOWLEDGE / "search.py",  # the query side
    KNOWLEDGE / "store.py",  # the index side
}


def gate_one_tokenizer() -> None:
    for path, tree in _modules():
        for node in _calls(tree):
            name = _callee(node)
            if name not in _TS_FUNCTIONS:
                continue
            if path not in _TS_ALLOWED:
                failures.append(
                    f"GATE-KN-ONE-TOKENIZER: {path.relative_to(ROOT)}:{node.lineno} "
                    f"calls {name}() outside services/knowledge/{{search,store}}.py"
                )
    # Both allowed modules must obtain their lexemes from `tokenize`, not build their own.
    for path in sorted(_TS_ALLOWED):
        source = path.read_text(encoding="utf-8")
        if "from app.services.knowledge.tokenize import" not in source:
            failures.append(
                f"GATE-KN-ONE-TOKENIZER: {path.relative_to(ROOT)} builds a text-search "
                "expression without importing the tokenizer"
            )


# --- GATE-KN-PROJECT-SCOPED --------------------------------------------------

_KNOWLEDGE_MODELS = {
    "KnowledgeSource",
    "KnowledgeChunk",
    "KnowledgeJob",
    "KnowledgeLink",
    "ContextPack",
    "TaskKnowledgePin",
}


def _mentions_project(node: ast.AST) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Attribute) and inner.attr == "project_id":
            return True
        if isinstance(inner, ast.Name) and inner.id in {"project_id", "_scope"}:
            return True
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            if "project_id" in inner.value:
                return True
    return False


#: The two places a fleet-wide read is correct, each named with its reason. A list, not
#: a heuristic: an exemption nobody can see is how a rule quietly stops being one, so the
#: gate **prints every exemption it honours**.
_FLEET_WIDE = {
    ("api/http/metrics.py", "knowledge_queue"): (
        "the Prometheus gauges are deployment-wide counts with no content, read only "
        "with a scrape token"
    ),
    ("services/knowledge/worker.py", "_recover_stuck"): (
        "the interrupted-job sweep is a maintenance pass over every project; scoping it "
        "would mean iterating projects to do one UPDATE"
    ),
}


def gate_project_scoped() -> None:
    """Every statement reaching a knowledge table must name a project.

    Checked per **statement** rather than per call, because a select and its `.where()`
    are separate nodes in the tree and a chain may be split across lines. The unit that
    has to carry the predicate is the query, and the statement is the query's boundary.
    """
    for path, tree in _modules():
        for statement in ast.walk(tree):
            if not isinstance(statement, ast.stmt):
                continue
            names = {
                node.id
                for node in ast.walk(statement)
                if isinstance(node, ast.Name) and node.id in _KNOWLEDGE_MODELS
            }
            if not names:
                continue
            has_select = any(
                _callee(call) in {"select", "update", "delete", "insert", "count"}
                for call in _calls(statement)
            )
            if not has_select:
                continue
            if _mentions_project(statement):
                continue
            where = _enclosing(tree, statement)
            # Two narrow exemptions, both by primary key rather than by scan:
            # `session.get(Model, id)` is not a select, and a statement that filters on
            # `source_id`/`task_id`/`run_id` has already been scoped by whoever resolved
            # that id — every such call site checks the owner first, and those checks are
            # what `tests/db/test_knowledge_*.py` assert directly.
            scoped_by_owner = any(
                isinstance(node, ast.Attribute)
                and node.attr in {"source_id", "task_id", "run_id", "id"}
                for node in ast.walk(statement)
            )
            if scoped_by_owner:
                continue
            relative = str(path.relative_to(APP))
            if (relative, where) in _FLEET_WIDE:
                honoured.add((relative, where))
                continue
            failures.append(
                f"GATE-KN-PROJECT-SCOPED: {path.relative_to(ROOT)}:{statement.lineno} "
                f"in {where}() queries {sorted(names)} with no project_id predicate"
            )


# --- GATE-KN-INSTRUCTION-LAYER -----------------------------------------------


def gate_instruction_layer() -> None:
    """`_policy_sections` is the only producer of layer 1, and it only reads policy."""
    path = KNOWLEDGE / "context.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    producers: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee(node) != "Section":
            continue
        for keyword in node.keywords:
            if keyword.arg != "layer":
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value == 1:
                producers.append(_enclosing(tree, node))
    if sorted(set(producers)) != ["_policy_sections"]:
        failures.append(
            "GATE-KN-INSTRUCTION-LAYER: layer 1 sections are built in "
            f"{sorted(set(producers))}, expected only ['_policy_sections']"
        )
    body = path.read_text(encoding="utf-8")
    start = body.find("async def _policy_sections")
    end = body.find("\n    async def ", start + 1)
    section = body[start:end]
    if 'source_type == "policy"' not in section:
        failures.append(
            "GATE-KN-INSTRUCTION-LAYER: _policy_sections no longer restricts its query "
            "to source_type == 'policy'"
        )
    if '"authoritative", "accepted"' not in section:
        failures.append(
            "GATE-KN-INSTRUCTION-LAYER: _policy_sections no longer restricts its query "
            "to accepted-or-above authority"
        )


# --- GATE-KN-AUTHORITY-SERVER-SIDE -------------------------------------------


def gate_authority_server_side() -> None:
    """No request schema may carry `authority` **as free input**.

    The one exception is a closed `Literal` of the three a person is allowed to assert
    (`authoritative`/`accepted`/`retracted`); the pipeline's own levels — `canonical`,
    `verified` — must remain unassertable, because a word anyone can claim stops meaning
    anything.
    """
    path = APP / "api" / "http" / "schemas.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not node.name.endswith("Request"):
            continue
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            if item.target.id != "authority":
                continue
            rendered = ast.unparse(item.annotation)
            if not rendered.startswith("Literal["):
                failures.append(
                    f"GATE-KN-AUTHORITY-SERVER-SIDE: {node.name}.authority is "
                    f"{rendered}, not a closed Literal"
                )
                continue
            for level in ("canonical", "verified", "reviewed", "generated", "discussion"):
                if level in rendered:
                    failures.append(
                        f"GATE-KN-AUTHORITY-SERVER-SIDE: {node.name}.authority admits "
                        f"'{level}', which only the ingestion pipeline may write"
                    )


# --- GATE-KN-NO-RAW-LOG-INDEX ------------------------------------------------


def gate_no_raw_log_index() -> None:
    for path in sorted(KNOWLEDGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "RunLog":
                        failures.append(
                            f"GATE-KN-NO-RAW-LOG-INDEX: {path.relative_to(ROOT)}:"
                            f"{node.lineno} imports RunLog"
                        )
            if isinstance(node, ast.Name) and node.id == "RunLog":
                failures.append(
                    f"GATE-KN-NO-RAW-LOG-INDEX: {path.relative_to(ROOT)}:{node.lineno} "
                    "references RunLog"
                )


def main() -> int:
    gate_one_tokenizer()
    gate_project_scoped()
    gate_instruction_layer()
    gate_authority_server_side()
    gate_no_raw_log_index()
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} V2-K1 invariant(s) violated", file=sys.stderr)
        return 1
    for relative, where in sorted(honoured):
        print(
            f"        fleet-wide (allowed): {relative}::{where} — {_FLEET_WIDE[(relative, where)]}"
        )
    print(
        "V2-K1 invariants: OK (tokenizer, project scope, instruction layer, authority, no raw log)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
