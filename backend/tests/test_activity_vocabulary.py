"""The activity vocabulary, and the two places that must agree with it (PJ-06).

`activity_events.kind` is a *different* vocabulary from `audit_logs.action`, and the
difference is deliberate (see `services/activity.py`). That makes it easy to reach
for the wrong label map in the browser and get no error at all — `actionLabel` falls
through to showing the raw key, so the screen reads `workspace.bound` where it should
read a sentence. It looks unfinished rather than broken, which is exactly the kind of
defect that ships.

So the same rule the audit vocabulary already has applies here: every kind must have
a write site, and the browser must know every kind it can receive.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services import activity

ROOT = Path(__file__).resolve().parents[2]


def test_every_kind_has_a_write_site() -> None:
    """A kind nobody writes is a timeline entry that can never appear."""
    sources = [
        path.read_text(encoding="utf-8")
        for path in (ROOT / "backend/app").rglob("*.py")
        if path.name != "activity.py" and "migrations" not in path.parts
    ]
    blob = "\n".join(sources)
    names = {
        kind: name
        for name, kind in vars(activity).items()
        if isinstance(kind, str) and kind in activity.ALL_KINDS
    }
    unwritten = sorted(kind for kind, name in names.items() if name not in blob)
    assert unwritten == [], f"activity kinds defined but never written: {unwritten}"


def test_all_kinds_is_complete() -> None:
    declared = {
        value
        for name, value in vars(activity).items()
        if isinstance(value, str) and not name.startswith("_") and "." in value and name.isupper()
    }
    assert declared == set(activity.ALL_KINDS)


def test_the_frontend_labels_every_kind_it_can_receive() -> None:
    """A kind with no label renders as its raw key — readable, but obviously
    unfinished. This is the assertion that would have caught the timeline being
    pointed at the *audit* label map."""
    source = (ROOT / "frontend/src/utils/activityKinds.ts").read_text(encoding="utf-8")
    block = re.search(r"const LABELS: Record<string, string> = \{(.*?)\};", source, re.S)
    assert block is not None, "LABELS is missing from frontend/src/utils/activityKinds.ts"
    labelled = set(re.findall(r'"([^"]+)":', block.group(1)))
    assert labelled == set(activity.ALL_KINDS), (
        f"only on the server: {sorted(set(activity.ALL_KINDS) - labelled)}; "
        f"only in the browser: {sorted(labelled - set(activity.ALL_KINDS))}"
    )


def test_the_two_vocabularies_are_not_the_same_set() -> None:
    """Guards the assumption this whole module rests on.

    If they ever became identical, one label map would do and this separation would
    be dead weight — but they are not, and the overlap is empty, so a kind passed to
    `actionLabel` silently degrades instead of failing.
    """
    from app.services import audit

    assert set(activity.ALL_KINDS) & set(audit.ALL_ACTIONS) == set()
