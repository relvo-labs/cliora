"""D94's pin: the read model's card, measured before the threshold was written.

**Measured 169,518 bytes on 2026-08-23** for 200 cards (35 fields) against the fixed
dataset, `scripts/cv/seed-dataset.py` seed 20260819. The threshold below is that
measurement plus 15 %.

The test builds **its own** fixture rather than reading that dataset, and that is the
reason it is a pin at all: the seeded dataset is written to by the other measurement
scripts (`measure-attention.py` queues runs on it, which lengthens `active_run_status` and
`active_run_runner_name` on the cards it touches), so re-running them moves the artifacts
by a percent or two without anything about either DTO having changed. On 2026-08-24 that
was 172,758 for the work card and 77,152 for the board card, against docstring figures of
169,518 and 75,952 — both inside the tolerances below, and neither a change to a DTO. **A
budget that moves when a neighbouring script runs is not a budget**, which is why the
numbers that gate anything are measured here and not read from `artifacts/`.

**The field this test kept out.** `readiness_missing` was added to the DTO during PX-30
and reverted the same day: the Ready-transition dialog needs which items are missing, the
field was already on `WorkRow`, and it looked free. It measured **+34,440 bytes (+20 %)**
and became the most expensive field in the payload, ahead of `project_id` — paid on every
card of every response for something one dialog needs about one card. The dialog reads
`/api/tasks/{id}` instead.

The upstream plan quoted 160 KB and derived it from "a bit more than twice 74 KB". The
number turned out to be almost exactly right and **the derivation was wrong twice over**:
74 KB has not been the board's size since `plan/19`, and the 89,251 bytes that replaced it
in `repositories/tasks.py`'s docstring is not `BoardCardDTO` at all — it comes from
`scripts/tk/measure_board_payload.py`, a synthetic generator with a hand-written summary
dict that predates the DTO. The real board card is 75,952 bytes on this fixture. A budget
that happens to be right for reasons that are wrong is a budget nobody can adjust.

Top five fields by bytes at 200 cards:

===========================  =======
`project_id`                 10,400
`id`                          9,000
`updated_at`                  8,800
`pending_human_action`        6,800
`execution_status`            6,580
===========================  =======

The most expensive field is the one the plan's list did not have. `project_id` is a uuid
and a long key name, two hundred times over — and it is **not optional**: My Work is
cross-project and a card it cannot link to is a row a reader cannot act on. Three of the
five are key names paid two hundred times over, which is why the cut list in
`plan/26/03` §4 starts with fields nobody reads rather than with fields that look big.
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.schemas import BoardCardDTO
from app.api.http.work import WorkItemCardDTO, _card
from app.db.models import Project, Role, Task, User
from app.security.passwords import hash_password
from app.services.tasks import TaskService
from app.services.work.attention import derive_attention
from app.services.work.items import DerivedItem
from app.services.work.rows import WorkRowReader

pytestmark = pytest.mark.asyncio

CARDS = 200
# The measurement, and the pin at +15 %.
WORK_ITEM_MEASURED = 169_518
WORK_ITEM_BUDGET = int(WORK_ITEM_MEASURED * 1.15)
# The board card on the *same* fixture. Not 89,251 — see the module docstring.
BOARD_CARD_MEASURED = 75_952
BOARD_CARD_TOLERANCE = 0.02


async def _fixture(session: AsyncSession) -> Project:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    username = f"size-{uuid.uuid4().hex[:8]}"
    owner = User(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        password_hash=hash_password("pw"),
        role_id=role.id,
    )
    session.add(owner)
    await session.flush()
    slug = f"size-{uuid.uuid4().hex[:8]}"
    project = Project(
        id=uuid.uuid4(),
        name=slug,
        slug=slug,
        status="active",
        owner_user_id=owner.id,
        next_card_seq=1,
    )
    session.add(project)
    await session.flush()
    stages = (
        ["backlog"] * 80 + ["ready"] * 40 + ["implementing"] * 20 + ["blocked"] * 20 + ["done"] * 40
    )
    for index in range(CARDS):
        session.add(
            Task(
                id=uuid.uuid4(),
                project_id=project.id,
                card_ref=f"DS-{index + 1}",
                title=f"資料集卡片 {index + 1}",
                stage=stages[index],
                source="none",
                delivery="none",
                risk=("low", "medium", "high")[index % 3],
            )
        )
    await session.flush()
    return project


async def test_the_work_item_card_stays_within_its_measured_budget(
    session: AsyncSession,
) -> None:
    """The pin. See the module docstring for the measurement and its date."""
    project = await _fixture(session)
    rows, runtime = await WorkRowReader(session).for_project(project)
    payloads = [
        json.loads(
            _card(
                DerivedItem(row=row, attention=derive_attention(row, runtime)), None
            ).model_dump_json()
        )
        for row in rows
    ]
    assert len(payloads) == CARDS
    body = json.dumps(payloads, ensure_ascii=False, separators=(",", ":"))
    measured = len(body.encode("utf-8"))
    assert measured <= WORK_ITEM_BUDGET, (
        f"{measured} bytes for {CARDS} cards exceeds the pinned {WORK_ITEM_BUDGET}. "
        "Re-measure with scripts/px/measure-dto.py --dto work and either cut a field "
        "(plan/26/03 §4 has the order) or move the pin deliberately."
    )
    # The field count is pinned too: a 36th field is a decision, and this is where it
    # gets made rather than noticed.
    assert len(WorkItemCardDTO.model_fields) == 35


async def test_the_board_card_did_not_grow(session: AsyncSession) -> None:
    """D48 asserted on **bytes**, not only on shape.

    The read model shares `active_runs()` and `blocking_counts()` with the V1 board, so
    somebody widening one of those queries for a new card makes the old card bigger while
    the OpenAPI diff stays empty. This is the test that notices.
    """
    project = await _fixture(session)
    cards = await TaskService(session).board(project.id, is_online=lambda _: False)
    payloads = [
        json.loads(
            BoardCardDTO(
                id=card.task.id,
                card_ref=card.task.card_ref,
                title=card.task.title,
                stage=card.task.stage,
                risk=card.task.risk,
                priority=card.task.priority,
                owner_user_id=card.task.owner_user_id,
                owner_name=card.owner_name,
                delivery=card.task.delivery,
                blocking_count=card.blocking_count,
                gates_approved_count=card.gates_approved_count,
                active_run_status=card.active_run_status,
                active_run_runner_name=card.active_run_runner_name,
                waiting_reason=card.waiting_reason,
                version=card.task.version,
                updated_at=card.task.updated_at,
            ).model_dump_json()
        )
        for card in cards
    ]
    body = json.dumps(payloads, ensure_ascii=False, separators=(",", ":"))
    measured = len(body.encode("utf-8"))
    lower = BOARD_CARD_MEASURED * (1 - BOARD_CARD_TOLERANCE)
    upper = BOARD_CARD_MEASURED * (1 + BOARD_CARD_TOLERANCE)
    assert lower <= measured <= upper, (
        f"BoardCardDTO is {measured} bytes for {CARDS} cards; it was "
        f"{BOARD_CARD_MEASURED}. D48 says this payload does not move."
    )
    assert len(BoardCardDTO.model_fields) == 16


async def test_the_work_item_card_carries_the_primary_attention_and_not_the_set(
    session: AsyncSession,
) -> None:
    """D107. The full signal list is the drawer's, not the card's.

    At two hundred cards the list is most of the payload and it drives no decision a
    person makes *from the board* — they open the card for that.
    """
    assert "attention_signals" not in WorkItemCardDTO.model_fields
    assert "primary_attention" in WorkItemCardDTO.model_fields
    assert "attention_count" in WorkItemCardDTO.model_fields
    del session
