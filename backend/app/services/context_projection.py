"""Building the context pack and getting it onto the node (TK-07/TK-10, ADR 0028).

Three things travel: the pack itself, the session credential, and the process notes
the pack points at. They go in **one** message after the session is already running —
never inside `SessionService.create`, because `session.start` has already succeeded by
then and a rollback would leave a tmux the platform does not know about (`plan/17`
D8).

**A failure here never fails a session.** Context is an addition; the session is the
product. The failure is recorded on the project timeline and the console offers a
retry.

The pack's budget is 4 KB (D8) and the first section is *how to report progress*,
because M2 — whether agents actually use the CLI — is the assumption the whole
internalised design rests on, and a paragraph at the end of a file is a paragraph
nobody reads.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Node, Task, TerminalSession
from app.logging import get_logger
from app.repositories.tasks import TaskRepository
from app.services.agent_auth import SessionTokenService
from app.services.process import EffectiveProcess, ProcessService
from app.settings import Settings, get_settings

log = get_logger("cliora.context")

# D8's budget. Not a limit on what we *can* send — the wire allows 64 KiB per file —
# but on what is useful: everything above this is better given as a path, because the
# agent has `Read` and `rg` and we do not know what it will need.
CONTEXT_BUDGET_BYTES = 4096

PROJECTION_UNSUPPORTED = "node_unsupported"
PROJECTION_FAILED = "failed"
PROJECTION_OK = "ok"


@dataclass(frozen=True, slots=True)
class ProjectionOutcome:
    status: str
    written: list[str]
    skipped: list[str]
    detail: str | None = None


def _context_blocks(
    *, task: Task | None, process: EffectiveProcess, blocking: list[str], api_base: str
) -> list[tuple[str, bool]]:
    """The Always-Included pack (D8).

    Section order is the decision here. "How to report progress" is first because the
    thing most likely to go wrong is not the agent misunderstanding the task — it is
    the agent never telling anyone what it did. Everything on-demand is a *path*, not
    a payload.
    """
    blocks: list[tuple[str, bool]] = []
    lines: list[str] = []
    if task is None:
        lines.append("# Cliora session (no task)")
        lines.append("")
        lines.append("這個 Session 沒有指定任務卡。以下工具仍可使用，但沒有卡片可以推進。")
    else:
        lines.append(f"# {task.card_ref} {task.title}")
    lines.append("")
    lines.append("## 你可以怎麼回報進度")
    lines.append("")
    lines.append("```")
    if task is not None:
        lines.append(f"cliora task get {task.card_ref}")
        lines.append(f'cliora task update {task.card_ref} --stage implementing --note "開始"')
    else:
        lines.append("cliora task list")
    lines.append("```")
    lines.append("")
    lines.append(
        "平台連不上時這些指令會失敗，但**你的工作不受影響**——繼續做，恢復連線後再執行一次。"
    )
    # public_base_url is configuration, not task content. Bound its rendering so
    # a malformed deployment URL cannot crowd mandatory acceptance criteria out.
    shown_api = api_base[:256]
    lines.append(f"`cliora context show` 讀本機檔案，不需要連線。API：{shown_api}")
    lines.append("")

    # The title + CLI instructions are mandatory and always first (D8/M2).
    blocks.append(("\n".join(lines) + "\n", True))

    if task is not None:
        for heading, value in (
            ("目標", task.objective),
            ("範圍", task.scope),
            ("非目標", task.non_goals),
        ):
            if value:
                blocks.append((f"## {heading}\n\n{value.strip()}\n\n", False))
        criteria = task.acceptance_criteria or []
        if criteria:
            criterion_lines = ["## 驗收標準", ""]
            for item in criteria:
                result = item.get("result") or "未驗"
                criterion_lines.append(f"- [{result}] {item.get('text', '')}")
            criterion_lines.append("")
            # Acceptance criteria are mandatory. The task write service bounds
            # their rendered bytes so this block plus the CLI preface is always
            # representable inside 4 KB.
            blocks.append(("\n".join(criterion_lines) + "\n", True))
        blocks.append((f"## 風險等級：{task.risk}\n\n", False))
        if blocking:
            blocks.append((f"## 尚未完成的前置任務\n\n{', '.join(blocking)}\n\n", False))

    reading = [
        "## 延伸閱讀（給路徑，不貼內容）",
        "",
        f"- `.cliora/process/{process.version}/` 車道、就緒條件、審查關卡",
        "- `.cliora/reference/` 專案參考資料（若有）",
        "",
        "車道："
        + " → ".join(f"{lane['stage']}（{lane.get('label', '')}）" for lane in process.lanes),
        "",
    ]
    blocks.append(("\n".join(reading) + "\n", False))
    return blocks


def _context_markdown(
    *, task: Task | None, process: EffectiveProcess, blocking: list[str], api_base: str
) -> str:
    """Unbudgeted rendering used by measurements and focused tests."""
    return "".join(
        text
        for text, _mandatory in _context_blocks(
            task=task, process=process, blocking=blocking, api_base=api_base
        )
    )


def _fit_blocks(blocks: list[tuple[str, bool]], *, more: str) -> str:
    """Keep the pack inside D8's budget without truncating mandatory text.

    Optional sections are dropped from the end. The CLI preface and every acceptance
    criterion are indivisible mandatory blocks; no byte slicing is used, so UTF-8 and
    requirement meaning both survive. Task writes keep the mandatory set bounded.
    """
    rendered = "".join(text for text, _mandatory in blocks)
    if len(rendered.encode()) <= CONTEXT_BUDGET_BYTES:
        return rendered

    kept = list(blocks)
    omitted = 0
    while True:
        notice = (
            f"\n> 已省略 {omitted} 個區塊以符合 4 KB 預算。完整內容：`{more}`\n" if omitted else ""
        )
        rendered = "".join(text for text, _mandatory in kept) + notice
        if len(rendered.encode()) <= CONTEXT_BUDGET_BYTES:
            return rendered
        removable = next(
            (index for index in range(len(kept) - 1, -1, -1) if not kept[index][1]), None
        )
        if removable is None:
            raise ValueError("mandatory context exceeds the 4 KB projection budget")
        kept.pop(removable)
        omitted += 1


def _process_notes(process: EffectiveProcess) -> str:
    lines = [
        "# 流程定義（來源：Monstrare, MIT）",
        "",
        f"版本：{process.version}",
        "",
        "## 車道",
        "",
    ]
    for lane in process.lanes:
        wip = lane.get("wip_suggested")
        suffix = f"（建議並行 {wip}）" if wip else ""
        lines.append(f"- `{lane['stage']}` {lane.get('label', '')}{suffix}")
    lines += ["", "## 就緒條件（缺項只警告，不阻擋）", ""]
    for item in process.readiness:
        lines.append(f"- `{item['key']}` {item.get('label', '')}：{item.get('hint', '')}")
    lines += ["", "## 審查關卡（一律由人核准，Agent 憑證沒有這個權限）", ""]
    for gate in process.gates:
        state = "可用" if gate.enabled else f"停用（{gate.disabled_reason}）"
        lines.append(f"- `{gate.key}` {gate.label} — {state}")
    lines += [
        "",
        "## 唯一會被拒絕的規則",
        "",
        "前置任務未完成時，卡片不能進入「就緒」之後的車道。拒絕訊息會指名是哪幾張卡。",
        "",
    ]
    return "\n".join(lines) + "\n"


class ContextProjectionService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._tokens = SessionTokenService(session, settings=self._settings)
        self._process = ProcessService(session)
        self._tasks = TaskRepository(session)

    async def build(
        self, *, terminal: TerminalSession, actor_id: uuid.UUID
    ) -> tuple[str, list[dict[str, str]]]:
        """Everything the projection message carries, ready to send.

        Issues the credential as part of building, because the credential is one of the
        files: separating them would create a moment where a token exists that nothing
        is going to deliver.
        """
        assert terminal.project_id is not None
        process = await self._process.effective()
        task: Task | None = None
        blocking: list[str] = []
        if terminal.task_id is not None:
            task = await self._tasks.get(terminal.task_id)
            if task is not None:
                blocking = await self._tasks.unfinished_dependencies(task.id)

        issued = await self._tokens.issue(
            terminal=terminal, project_id=terminal.project_id, actor_id=actor_id
        )
        more = f"cliora task get {task.card_ref}" if task else "cliora task list"
        pack = _fit_blocks(
            _context_blocks(
                task=task,
                process=process,
                blocking=blocking,
                api_base=self._settings.public_base_url or "",
            ),
            more=more,
        )
        files = [
            {
                "path": f".cliora/context/{terminal.id}.md",
                "mode": "0600",
                "data": base64.b64encode(pack.encode()).decode(),
            },
            {
                "path": f".cliora/context/{terminal.id}.token",
                "mode": "0600",
                "data": base64.b64encode(issued.value.encode()).decode(),
            },
            {
                "path": f".cliora/process/{process.version}/process.md",
                "mode": "0600",
                "data": base64.b64encode(_process_notes(process).encode()).decode(),
            },
        ]
        return process.version, files

    async def project(
        self, *, terminal: TerminalSession, node: Node, actor_id: uuid.UUID, registry: object
    ) -> ProjectionOutcome:
        """Send the pack. Never raises into the caller's request.

        A node whose daemon predates 0.8.0 is not an error: no message is sent at all,
        because an unknown type on an old daemon is a round trip that can only fail.
        The console turns this into "upgrade to 0.8.0" rather than a 500 (ADR 0028 §5).
        """
        if not node.context_projection:
            return ProjectionOutcome(
                status=PROJECTION_UNSUPPORTED,
                written=[],
                skipped=[],
                detail="agentd 0.8.0 is required to receive task context",
            )
        try:
            version, files = await self.build(terminal=terminal, actor_id=actor_id)
            message = await registry.request(  # type: ignore[attr-defined]
                terminal.node_id,
                "context.project",
                {
                    "session_id": str(terminal.id),
                    "process_version": version,
                    "files": files,
                },
                timeout_seconds=self._settings.file_upload_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - the caller must never see this
            # Deliberately broad: every failure mode here — offline node, timeout,
            # refusal — has the same consequence for the session, which is none.
            log.warning(
                "context_projection_failed",
                extra={"event": "context_projection_failed", "error": type(exc).__name__},
            )
            return ProjectionOutcome(
                status=PROJECTION_FAILED, written=[], skipped=[], detail=type(exc).__name__
            )
        if message.type != "context.projected" or not message.success:
            code = (message.error or {}).get("code") if message.error else None
            return ProjectionOutcome(
                status=PROJECTION_FAILED, written=[], skipped=[], detail=str(code)
            )
        payload = message.payload or {}
        return ProjectionOutcome(
            status=PROJECTION_OK,
            written=list(payload.get("written", [])),
            skipped=list(payload.get("skipped", [])),
        )
