from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_ROOT = REPO_ROOT / "traceability"
DOC_ROOT = REPO_ROOT / "docs" / "traceability"
OWNER_KEYS = {
    "product",
    "architecture",
    "security",
    "central",
    "daemon",
    "frontend",
    "test-infra",
    "operations",
    "release",
}

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class TraceData:
    requirements_doc: JsonObject
    links_doc: JsonObject
    gates_doc: JsonObject
    waivers_doc: JsonObject

    @property
    def requirements(self) -> list[JsonObject]:
        return self.requirements_doc["requirements"]

    @property
    def links(self) -> list[JsonObject]:
        return self.links_doc["links"]

    @property
    def gates(self) -> list[JsonObject]:
        return self.gates_doc["gates"]

    @property
    def waivers(self) -> list[JsonObject]:
        return self.waivers_doc["waivers"]

    def requirement_index(self) -> dict[str, JsonObject]:
        return {item["id"]: item for item in self.requirements}

    def criterion_index(self) -> dict[str, tuple[JsonObject, JsonObject]]:
        return {
            criterion["id"]: (requirement, criterion)
            for requirement in self.requirements
            for criterion in requirement["criteria"]
        }

    def gate_index(self) -> dict[str, JsonObject]:
        return {item["id"]: item for item in self.gates}

    def links_by_source(self) -> dict[str, list[JsonObject]]:
        result: dict[str, list[JsonObject]] = {}
        for link in self.links:
            result.setdefault(link["from"], []).append(link)
        return result


def load_json(path: Path) -> JsonObject:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(
            f"{path.relative_to(REPO_ROOT)}: top-level JSON must be an object"
        )
    return value


def dump_json(value: JsonObject) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def load_trace_data() -> TraceData:
    return TraceData(
        requirements_doc=load_json(TRACE_ROOT / "requirements.json"),
        links_doc=load_json(TRACE_ROOT / "links.json"),
        gates_doc=load_json(TRACE_ROOT / "gates.json"),
        waivers_doc=load_json(TRACE_ROOT / "waivers.json"),
    )


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def github_slug(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[^\w\u0080-\uffff -]", "", value)
    value = re.sub(r"\s+", "-", value)
    return re.sub(r"-+", "-", value).strip("-")


def markdown_anchors(path: Path) -> dict[str, str]:
    """Return anchor -> human text for explicit HTML anchors and headings."""
    lines = path.read_text(encoding="utf-8").splitlines()
    anchors: dict[str, str] = {}
    pending: list[str] = []
    explicit = re.compile(r'<a\s+id="([a-z0-9][a-z0-9._-]*)"></a>')
    heading = re.compile(r"^#{1,6}\s+(.+?)\s*$")
    for index, line in enumerate(lines):
        match = explicit.search(line)
        if match:
            pending.append(match.group(1))
            continue
        title_match = heading.match(line)
        if title_match:
            title = title_match.group(1).strip()
            anchors.setdefault(github_slug(title), title)
            for anchor in pending:
                anchors[anchor] = title
            pending.clear()
            continue
        if pending and line.strip() and not line.strip().startswith("<!--"):
            text = re.sub(r"^(\*|-|\d+\.)\s+", "", line.strip())
            text = re.sub(r"[`*_]", "", text)
            for anchor in pending:
                anchors[anchor] = text
            pending.clear()
    for anchor in pending:
        anchors[anchor] = anchor
    return anchors


def locator_path(kind: str, locator: str) -> tuple[Path | None, str | None]:
    if kind in {"requirement", "gate", "manual"}:
        return None, locator
    token: str | None = None
    raw_path = locator
    if kind == "pytest" and "::" in locator:
        raw_path, token = locator.split("::", 1)
    elif kind in {"gotest", "vitest", "playwright", "scenario"} and "#" in locator:
        raw_path, token = locator.split("#", 1)
    elif (
        kind in {"code", "plan", "adr", "source", "migration", "config"}
        and "#" in locator
    ):
        raw_path, token = locator.split("#", 1)
    return REPO_ROOT / raw_path, token


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
