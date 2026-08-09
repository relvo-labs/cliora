"""The seeded process definition, and the one property its version has to hold.

`version` is not a serial. It becomes the directory name under
`.cliora/process/<version>/`, and the projection treats "that directory already
exists" as success (ADR 0028 sec 2) — so if the wording changes while the version
does not, a workspace that already has the old directory keeps it forever and every
agent there reads a stale process.

The digest below is therefore a **tripwire, not a checksum of correctness**: change
the seed content and this fails, and the fix is to bump `VERSION` and paste the new
digest. That is one deliberate action instead of one silently skipped one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "backend/app/db/migrations/versions/0026_seed_process_definition.py"

# sha256 of the canonical JSON of (lanes, readiness, gates, templates).
# Bump `VERSION` in the migration whenever this changes.
CONTENT_DIGEST = "9989e9cdd46b2e642701c852fdc201bb50c46c2e7b8cf25e44cdda36e2c2595c"
EXPECTED_VERSION = "2026.08-1"


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_seed_process_definition", SEED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(module: ModuleType) -> str:
    payload = json.dumps(
        [module.LANES, module.READINESS, module.GATES, module.TEMPLATES],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def test_process_definition_version_tracks_its_content() -> None:
    module = _seed_module()
    assert module.VERSION == EXPECTED_VERSION
    assert _digest(module) == CONTENT_DIGEST, (
        "the seeded process content changed. Bump VERSION in "
        "0026_seed_process_definition.py and update CONTENT_DIGEST here — a stale "
        "version leaves every existing workspace projecting into a directory whose "
        "contents no longer match."
    )


def test_the_six_lanes_are_monstrare_s_vocabulary() -> None:
    """Wire values are Monstrare's; only the labels are localised (D3).

    Renaming a stage is a data migration, not a copy edit: `tasks.stage` holds these
    strings and V2.3's branch naming reads them.
    """
    module = _seed_module()
    assert [lane["stage"] for lane in module.LANES] == [
        "backlog",
        "blocked",
        "ready",
        "implementing",
        "verify",
        "done",
    ]


def test_every_gate_requires_a_human() -> None:
    """The data-layer form of "an agent's output is not an approval" (ADR 0028 sec 1).

    A constant today. Asserted so that adding a seventh gate without the flag fails
    here rather than being discovered when an agent approves something.
    """
    module = _seed_module()
    assert all(gate["requires_human"] for gate in module.GATES)


def test_only_the_ui_gate_depends_on_an_integration() -> None:
    """One gate has a derived-disable rule, and it is the mockup one (D31).

    If a second gate ever gains a dependency, `services/process.py::effective` already
    handles it — but the *console* wording is written for one, so this fails to make
    that a decision rather than a surprise.
    """
    module = _seed_module()
    dependent = [gate["key"] for gate in module.GATES if gate.get("depends_on_integration")]
    assert dependent == ["ui"]


def test_the_seven_readiness_items_all_carry_a_hint() -> None:
    """A readiness item with no hint is a checkbox nobody knows how to satisfy."""
    module = _seed_module()
    assert len(module.READINESS) == 7
    assert all(item.get("hint") for item in module.READINESS)
