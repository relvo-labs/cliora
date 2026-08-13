"""seed the default process definition: six lanes, seven readiness items, six gates

Revision ID: 0026_seed_process_definition
Revises: 0025_seed_task_actions
Create Date: 2026-08-09

TK-03 / FR-TASK-004 (ADR 0028 sec 1). Monstrare's process (MIT) as platform data.
This is the whole of "internalisation": the lanes, the Definition of Ready and the
Review Gates stop being a document someone has to persuade an agent to follow and
become rows the API can refuse against.

**Separate from 0025** even though both are seed data: role permissions and process
definitions are different domains with different natural keys, and folding them
together would mean a downgrade of one taking the other with it.

**`version` is a content version.** It becomes the directory name under
`.cliora/process/<version>/`, so a change to the wording below must come with a
change to it — `test_process_definition_version_tracks_its_content` fails otherwise,
because a stale version means a second session projects into a directory whose
contents no longer match.

Idempotent on `key`, matching every other seed here: re-running changes nothing.
Downgrade removes only the row it inserted.
"""

import json
from collections.abc import Sequence

from alembic import op

revision: str = "0026_seed_process_definition"
down_revision: str | None = "0025_seed_task_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY = "default"
VERSION = "2026.08-1"

# The six lanes. Wire values are Monstrare's `stage` vocabulary; the labels are
# `version2.md` §7.3's Chinese ones (research/02/01 D3). WIP figures are advice:
# the lane count changes colour and nothing is refused, which is Monstrare's own
# semantics and the reason a board stays usable.
LANES = [
    {"stage": "backlog", "label": "待辦", "order": 1, "wip_suggested": None},
    {"stage": "blocked", "label": "阻塞", "order": 2, "wip_suggested": None},
    {"stage": "ready", "label": "就緒", "order": 3, "wip_suggested": 8},
    {"stage": "implementing", "label": "進行中", "order": 4, "wip_suggested": 3},
    {"stage": "verify", "label": "驗證中", "order": 5, "wip_suggested": 3},
    {"stage": "done", "label": "完成", "order": 6, "wip_suggested": None},
]

# Definition of Ready, seven items. In V2.1 these **warn and never refuse**
# (ADR 0028 sec 1): enforcing all seven from day one is how a board stops being
# written to, and an unused board is a source of truth nobody updates.
READINESS = [
    {
        "key": "problem_stated",
        "label": "問題已陳述",
        "hint": "一句話說清楚要解決什麼，而不是要做什麼",
    },
    {
        "key": "acceptance_criteria",
        "label": "驗收標準逐項可檢查",
        "hint": "每一條都要能回答「做到了沒有」",
    },
    {"key": "scope_bounded", "label": "範圍與非目標已界定", "hint": "寫出不做什麼比寫做什麼有用"},
    {"key": "dependencies_known", "label": "相依已辨識", "hint": "前置卡片已建立並連上"},
    {"key": "verification_defined", "label": "驗證方式已定義", "hint": "要跑哪個指令、看哪個輸出"},
    {"key": "risk_assessed", "label": "風險等級已評估", "hint": "涉及授權、寫入面或對外副作用時提高"},
    {"key": "context_pointers", "label": "情境指路已備妥", "hint": "給路徑，不要把大文件貼進卡片"},
]

# Review Gates, six. `requires_human` is a constant today and is written as data
# anyway: "an agent's output is not an approval" needs somewhere it can be pointed
# at, and V2.2's runner code will read this rather than re-deriving it.
#
# `depends_on_integration` on the `ui` gate is what makes the derived disable in
# `services/process.py` possible: without tunnel integration there is no way to
# preview a mockup, and a gate that can never be satisfied is a deadlock rather than
# rigour (D31, ADR 0028 sec 8).
GATES = [
    {"key": "requirements", "label": "需求審查", "order": 1, "requires_human": True},
    {"key": "architecture", "label": "架構審查", "order": 2, "requires_human": True},
    {
        "key": "ui",
        "label": "介面審查",
        "order": 3,
        "requires_human": True,
        "depends_on_integration": "tunnel",
    },
    {"key": "implementation", "label": "實作審查", "order": 4, "requires_human": True},
    {"key": "verification", "label": "驗證審查", "order": 5, "requires_human": True},
    {"key": "release", "label": "發布審查", "order": 6, "requires_human": True},
]

# Form content, not form structure: the structure lives in the frontend and the
# wording lives here, because V2.4's minimal override changes the wording.
TEMPLATES = {
    "task": {
        "objective": "這張卡要達成什麼？一句話。",
        "scope": "包含哪些？",
        "non_goals": "刻意不做哪些？",
        "acceptance_criteria": "逐項寫成可檢查的敘述。",
    },
    "spec": {
        "objective": "這個需求要解決的問題。",
        "scope": "涵蓋範圍。",
        "non_goals": "明確排除的部分。",
        "open_questions": "還不確定、需要提問的地方。未解決時規格不得核准。",
    },
}


def _literal(value: object) -> str:
    """A JSONB literal for a raw `op.execute`.

    Doubling the quote is not decoration: one apostrophe in a label — and these are
    labels people will edit — would otherwise end the string literal and turn the
    rest of the seed into SQL.
    """
    return json.dumps(value, ensure_ascii=False).replace("'", "''")


def upgrade() -> None:
    op.execute(
        "INSERT INTO process_definitions "
        "(id, key, version, source, lanes, readiness, gates, templates) "
        f"SELECT gen_random_uuid(), '{KEY}', '{VERSION}', 'monstrare', "
        f"'{_literal(LANES)}'::jsonb, "
        f"'{_literal(READINESS)}'::jsonb, "
        f"'{_literal(GATES)}'::jsonb, "
        f"'{_literal(TEMPLATES)}'::jsonb "
        f"WHERE NOT EXISTS (SELECT 1 FROM process_definitions WHERE key = '{KEY}');"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM process_definitions WHERE key = '{KEY}';")
