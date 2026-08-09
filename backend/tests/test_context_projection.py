from types import SimpleNamespace

import pytest

from app.api.errors import ApiError
from app.services.context_projection import CONTEXT_BUDGET_BYTES, _context_blocks, _fit_blocks
from app.services.tasks import MAX_ACCEPTANCE_CRITERIA_CONTEXT_BYTES, TaskService


def _process() -> SimpleNamespace:
    return SimpleNamespace(
        version="2026.08-1",
        lanes=[{"stage": "backlog", "label": "待辦"}],
    )


def test_context_budget_drops_optional_sections_but_preserves_all_acceptance_criteria() -> None:
    criteria = [
        {"id": f"AC-{index}", "text": f"必須保留的驗收標準 {index}：" + "驗" * 45, "result": None}
        for index in range(12)
    ]
    task = SimpleNamespace(
        card_ref="TASK-12",
        title="Workspace File Tree API",
        objective="目標" * 1000,
        scope="範圍" * 1000,
        non_goals="非目標" * 1000,
        acceptance_criteria=criteria,
        risk="high",
    )

    pack = _fit_blocks(
        _context_blocks(task=task, process=_process(), blocking=["TASK-1"], api_base="https://x"),
        more="cliora task get TASK-12",
    )

    assert len(pack.encode()) <= CONTEXT_BUDGET_BYTES
    assert pack.index("你可以怎麼回報進度") < pack.index("驗收標準")
    for item in criteria:
        assert item["text"] in pack
    assert "已省略" in pack
    assert "cliora task get TASK-12" in pack


def test_task_write_refuses_acceptance_criteria_that_cannot_fit_context() -> None:
    service = TaskService(None)  # type: ignore[arg-type]
    criteria = [{"text": "驗" * (MAX_ACCEPTANCE_CRITERIA_CONTEXT_BYTES + 1)}]

    with pytest.raises(ApiError) as raised:
        service._validated({"acceptance_criteria": criteria})

    assert raised.value.code == "TASK_CONTEXT_TOO_LARGE"
    assert raised.value.status_code == 422
