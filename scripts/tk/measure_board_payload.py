"""M1 — how big is a 200-card board response? (plan/17/01-…md §2.2)

The decision this feeds is the *shape* of `GET /api/projects/{id}/board`, and a shape
is expensive to change once the frontend, the e2e suite and the tests are written —
so it has to be answered before `TK-04`, which is before the tables exist. That rules
out measuring a live endpoint and rules in measuring the payload, which is the half
of M1 that actually drives the decision: server time on a few hundred rows of a
single indexed table is not what makes a board slow, bytes over the wire is.

Two candidate shapes, both rendered from the same synthetic project:

* **full** — every field the Task Detail view shows, including acceptance criteria
  text and the six gates with approver and timestamp;
* **summary** — what a card actually renders on a board (`plan/17/07-…md` §2.1):
  card_ref, title, risk, owner, blocked-by count, delivery, stage, version.

Threshold (`plan/17/01-…md` §2.2): over 512 KB → the endpoint pages per lane.

    python scripts/tk/measure_board_payload.py --cards 200 --out artifacts/tk/local/m1.json

The wall-clock half of M1 is measured after `TK-04` by the live-stack Playwright case
named `M1 records p50 and p95 for a real 200-card board`; it writes
`artifacts/tk/local/m1-live.json`. Keeping that half out of this synthetic script
prevents JSON encoding time from being mislabeled as a database/API measurement.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import uuid
from pathlib import Path
from typing import Any

STAGES = ["backlog", "blocked", "ready", "implementing", "verify", "done"]
RISKS = ["low", "medium", "high", "critical"]
DELIVERIES = ["none", "artifact", "branch", "pull_request", "existing_pr"]
READINESS = [
    "problem_stated",
    "acceptance_criteria",
    "scope_bounded",
    "dependencies_known",
    "verification_defined",
    "risk_assessed",
    "context_pointers",
]
GATES = ["requirements", "architecture", "ui", "implementation", "verification", "release"]


def _card(rng: random.Random, seq: int, *, full: bool) -> dict[str, Any]:
    card_id = str(uuid.UUID(int=rng.getrandbits(128), version=4))
    summary: dict[str, Any] = {
        "id": card_id,
        "card_ref": f"TASK-{seq}",
        "title": "Workspace file tree API returns entries sorted by name " + str(seq),
        "stage": STAGES[seq % len(STAGES)],
        "risk": rng.choice(RISKS),
        "priority": "normal",
        "owner_user_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
        "owner_name": "someone.developer",
        "delivery": rng.choice(DELIVERIES),
        "blocking_count": rng.choice([0, 0, 0, 1, 2]),
        "version": rng.randint(1, 40),
        "updated_at": "2026-08-09T04:15:00Z",
    }
    if not full:
        return summary
    return summary | {
        "description": "A paragraph of description that a real card carries. " * 3,
        "objective": "One sentence of objective.",
        "scope": "Two or three sentences of scope. " * 2,
        "non_goals": "One sentence of non-goals.",
        "acceptance_criteria": [
            {
                "id": f"AC-{n:02d}",
                "text": "The endpoint answers 200 with entries sorted by name, "
                "directories first, and never leaks a server absolute path.",
                "result": rng.choice([None, "passed", "failed"]),
            }
            for n in range(1, 6)
        ],
        "readiness": {key: rng.choice([True, False]) for key in READINESS},
        "gates": {
            key: (
                None
                if rng.random() < 0.6
                else {
                    "approved_by": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
                    "approved_at": "2026-08-08T10:00:00Z",
                }
            )
            for key in GATES
        },
        "links": {"pr": None, "spec": ".cliora/reference/spec.md"},
        "source": "repo",
        "base_branch": "main",
        "target_branch": "main",
        "required_labels": ["docker", "node20"],
        "required_secrets": [],
    }


def _board(cards: list[dict[str, Any]]) -> dict[str, Any]:
    lanes = {stage: [] for stage in STAGES}
    for card in cards:
        lanes[card["stage"]].append(card)
    return {
        "lanes": [
            {
                "stage": stage,
                "label": stage,
                "wip_suggested": 3,
                "count": len(lanes[stage]),
                "cards": lanes[stage],
            }
            for stage in STAGES
        ]
    }


def _measure(payload: dict[str, Any]) -> dict[str, int]:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return {"bytes": len(raw), "gzip_bytes": len(gzip.compress(raw, 6))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    full = _board([_card(rng, n, full=True) for n in range(1, args.cards + 1)])
    rng = random.Random(args.seed)
    summary = _board([_card(rng, n, full=False) for n in range(1, args.cards + 1)])

    result = {
        "cards": args.cards,
        "threshold_bytes": 512 * 1024,
        "full": _measure(full),
        "summary": _measure(summary),
    }
    result["verdict"] = (
        "summary shape fits in one response"
        if result["summary"]["bytes"] <= result["threshold_bytes"]
        else "page per lane"
    )
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
