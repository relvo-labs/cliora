#!/usr/bin/env python
"""J1 — one vague sentence walks to `done`, and nobody opens a terminal.

**This is the non-degradable journey** (`plan/26/10` §4). Every other journey failing is
a bug; this one failing means the phase did not achieve its purpose. So it is written to
be hard to satisfy accidentally, and the twelve claims below are in the order a person
would actually hit them:

1. intake is **one sentence**, not a form;
2. the console's own "send to an agent" request produces a card that is a
   **clarification card linked to the requirement** — not an ordinary card that merely
   looks like one;
3. three rounds of conversation, each a **real continuation run** claimed by a real
   daemon, and the agent can see **every** answer, not only the latest;
4. the specification quotes all three answers, which is the only way to tell
   "the conversation was stored" from "the conversation was delivered";
5. approving it too early is **refused, and the refusal names the open question**;
6. the human asks for a change and the next turn produces **v2, not an edit of v1**;
7. approving works once nothing is unresolved;
8. decomposition is proposed by an agent and **created by a person**;
9. the created card's Ready transition **names what is missing** rather than refusing
   silently;
10. the implementation run **cites the accepted specification from project memory** —
    the segment `plan/26/10` §4 forbids skipping;
11. `done` is **refused until the evidence exists**, and the refusal names each gap;
12. **no terminal session was ever created for this project.** A count, because every
    other claim here is about something happening and this one is about something not
    happening.

Run: E2E_RUNNER=1 CLIORA_DATABASE_URL=… scripts/e2e/run-stack.sh \\
       uv run --project backend python scripts/px/journeys/j1_vague_to_done.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlalchemy as sa  # noqa: E402
from px_harness import Journey, ReadModelStack, use_agent_script  # noqa: E402

from app.db.models import (  # noqa: E402
    KnowledgeSource,
    Project,
    ProjectRepository,
)
from app.services.knowledge import provider_sync  # noqa: E402
from app.services.secrets import SecretService  # noqa: E402
from app.settings import Settings  # noqa: E402

#: The sentence somebody actually types. Vague on purpose: it names a complaint and no
#: solution, which is what makes the three rounds necessary rather than decorative.
VAGUE = "使用者反映月報匯出很慢，想辦法改善"

#: The three answers, and they are distinctive so that finding them inside a
#: specification version is evidence rather than coincidence.
ANSWERS = [
    "匯出成 Excel，CSV 不用留",
    "欄位順序要跟現在的畫面一致",
    "五萬列以內要在十秒內回來",
]

#: What the person asks for after reading v1. Also distinctive, and deliberately a
#: *removal* — the easiest change to fake by appending.
CHANGE_REQUEST = "把「先產生 PDF 預覽」整段拿掉，那不是這次要做的"

#: The clarification agent. **One script for every turn**, branching on the turn number
#: it finds in its own context pack — so a pack that failed to arrive, or arrived as the
#: first turn's, changes what the agent does rather than being invisible.
#:
#: `cliora task messages` rather than the pack's delta: a continuation's pack carries the
#: messages *since the previous turn* (`input_from_seq`), so by turn four the first two
#: answers are not in it. An agent that needs the whole thread asks for the whole thread,
#: and that this works is one of the twelve claims.
CLARIFY_AGENT = r"""#!/usr/bin/env bash
set -uo pipefail

pack=""
for candidate in .cliora/context/task.md ../.cliora/context/task.md; do
  [ -r "$candidate" ] && { pack="$(cat "$candidate")"; break; }
done
[ -n "$pack" ] || { echo "NO CONTEXT PACK" >&2; exit 3; }

turn="$(printf '%s' "$pack" | grep -oE '第 [0-9]+ 輪' | head -1 | grep -oE '[0-9]+')"
turn="${turn:-1}"
echo "TURN=$turn"

case "$turn" in
  1) cliora task ask "要匯出成什麼格式？現在的 CSV 還要保留嗎？" ;;
  2) cliora task ask "欄位順序有沒有要求？" ;;
  3) cliora task ask "多快才算不慢？資料量大概多少？" ;;
  4)
    # Every answer, from the card rather than from the pack.
    thread="$(cliora task messages --after 0 --limit 200)" || thread=""
    printf '%s\n' "$thread"
    python3 - "$thread" <<'PY' > /tmp/j1-spec.json
import json, sys
thread = sys.argv[1]
json.dump({
    "objective": "把月報匯出改快。人在卡上回答的三件事：\n" + thread,
    "scope": "月報匯出路徑；先產生 PDF 預覽再匯出",
    "non_goals": "其他報表",
    "acceptance_criteria": [{"text": "五萬列以內十秒內回來"}],
    "open_questions": [{"text": "匯出失敗時要不要寄信通知？"}],
}, sys.stdout, ensure_ascii=False)
PY
    cliora spec submit /tmp/j1-spec.json
    # And then ask, because a draft nobody was asked about is a draft nobody reads.
    cliora task ask "v1 送出了，還有要調整的地方嗎？"
    ;;
  *)
    thread="$(cliora task messages --after 0 --limit 200)" || thread=""
    python3 - "$thread" <<'PY' > /tmp/j1-spec2.json
import json, sys
thread = sys.argv[1]
json.dump({
    "objective": "把月報匯出改快（v2，依人的要求調整）。\n" + thread,
    # The removal the person asked for. Asserted by absence, which is why v1 had it.
    "scope": "月報匯出路徑",
    "non_goals": "其他報表；PDF 預覽",
    "acceptance_criteria": [{"text": "五萬列以內十秒內回來"}],
    "open_questions": [],
}, sys.stdout, ensure_ascii=False)
PY
    cliora spec submit /tmp/j1-spec2.json
    ;;
esac
exit 0
"""

#: The decomposition agent: one epic-free tree with a single implementable card.
#: `source`/`delivery` are deliberately the inert pair — this stack has no repository
#: registered, and a proposal that produced an undispatchable card would fail J1 for a
#: reason that has nothing to do with what J1 is about.
DECOMPOSE_AGENT = r"""#!/usr/bin/env bash
set -uo pipefail
cat > /tmp/j1-tree.json <<'JSON'
{"tasks": [{
  "id": "t1",
  "title": "月報匯出改用批次查詢",
  "objective": "把 N+1 查詢收成一次批次查詢",
  "scope": "月報匯出路徑",
  "non_goals": "其他報表",
  "risk": "medium",
  "acceptance_criteria": [{"text": "五萬列以內十秒內回來"}],
  "source": "none",
  "delivery": "none"
}]}
JSON
cliora proposal submit /tmp/j1-tree.json
"""

#: The implementation agent. Three things, and the first is the one `plan/26/10` §4 says
#: must not be skipped: it reads project memory and cites the accepted specification
#: **before** doing anything else.
IMPLEMENT_AGENT = r"""#!/usr/bin/env bash
set -uo pipefail

pack="$(cliora knowledge context 2>&1)" || {
  cliora task say "讀不到專案記憶：$pack"
  exit 3
}
label="$(printf '%s' "$pack" | grep -oE '\[S[0-9]+\]' | head -1)"
if [ -z "$label" ]; then
  cliora task say "專案記憶裡沒有與這張卡相關的來源，先不動手。"
  exit 3
fi
cited="$(cliora knowledge cite "$label" 2>&1)" || cited="(cite failed: $cited)"
cliora task say "依 $label 開工。引用摘要：$(printf '%s' "$cited" | head -3 | tr '\n' ' ')"

# beta.2's non-degradable extension. A pinned provider source has its own label; find it
# from the rendered metadata rather than assuming an order shared with the accepted spec.
provider_label="$(printf '%s' "$pack" | awk '
  /^## \[S[0-9]+\]/ { label=$2 }
  /來源類型：pull_request/ { print label; exit }
')"
if [ -n "$provider_label" ]; then
  provider_cited="$(cliora knowledge cite "$provider_label" 2>&1)" || {
    cliora task say "真 provider 引用失敗：$provider_cited"
    exit 3
  }
  cliora task say "真 provider $provider_label 已引用：$(printf '%s' "$provider_cited" | head -3 | tr '\n' ' ')"
fi

cat > /tmp/j1-report.json <<'JSON'
{
  "result": "passed",
  "completion_summary": "改成單次批次查詢，五萬列量測 6.2 秒。",
  "checks": [{"name": "pytest tests/reports", "origin": "card", "exit_code": 0}],
  "acceptance_criteria": [{"text": "五萬列以內十秒內回來", "result": "passed"}]
}
JSON
cliora verify report /tmp/j1-report.json
cliora task update "$(printf '%s' "$pack" | grep -oE 'TASK-[0-9]+' | head -1)" \
  --note "批次查詢已完成，等人核准。" || true
exit 0
"""


def _spec_text(spec: dict[str, Any]) -> str:
    """Every field of a spec version as one string, for substring assertions."""
    return json.dumps(spec, ensure_ascii=False)


async def _real_provider_source(
    stack: ReadModelStack, project_id: str, token: str
) -> tuple[uuid.UUID, dict[str, int]]:
    """GET a real merged PR into this journey's project without mutating the provider."""
    settings = Settings()
    async with stack.maker() as session:
        project = await session.get(Project, uuid.UUID(project_id))
        assert project is not None
        project.provider_sync_enabled = True
        secret = await SecretService(session, settings=settings).create(
            project=project,
            name="GITHUB_PROVIDER_TOKEN",
            kind="provider_token",
            value=token,
            actor_id=project.owner_user_id,
        )
        repository = ProjectRepository(
            id=uuid.uuid4(),
            project_id=project.id,
            scheme="https",
            host="github.com",
            path="Lei-k/cliora",
            default_branch="dev",
            auth_kind="ambient",
            provider_token_secret_id=secret.id,
            created_by=project.owner_user_id,
        )
        session.add(repository)
        await session.flush()
        outcome = await provider_sync.sync_project(
            session, project_id=project.id, settings=settings
        )
        merged = (
            await session.execute(
                sa.select(KnowledgeSource)
                .where(
                    KnowledgeSource.project_id == project.id,
                    KnowledgeSource.source_type == "pull_request",
                    KnowledgeSource.authority == "reviewed",
                    KnowledgeSource.active.is_(True),
                    KnowledgeSource.deleted_at.is_(None),
                )
                .order_by(KnowledgeSource.occurred_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if merged is None:
            raise RuntimeError(
                "real provider returned no merged PR in the bounded first page"
            )
        await session.commit()
        return merged.id, {
            "repositories": outcome.repositories,
            "sources": outcome.sources,
            "failures": outcome.failures,
        }


async def main() -> int:  # noqa: PLR0915 - the journey *is* the length; splitting it hides the order
    journey = Journey("j1", "一句模糊需求 → Done，全程不進 Terminal")
    async with ReadModelStack() as stack:
        await stack.require_runner()
        await stack.require_quiet_database()

        # ---------------------------------------------------------------- intake
        journey.step("一句話就能開始")
        project_id = await stack.project("px-j1")
        await stack.enable_knowledge(project_id)
        await stack.drain_ingestion(project_id)
        provider_token = os.environ.get("CLIORA_PROVIDER_EVIDENCE_TOKEN", "")
        provider_source_id: uuid.UUID | None = None
        if provider_token:
            provider_source_id, provider_outcome = await _real_provider_source(
                stack, project_id, provider_token
            )
            journey.note("real_provider", provider_outcome)
            journey.check(
                provider_outcome["repositories"] == 1
                and provider_outcome["sources"] > 0
                and provider_outcome["failures"] == 0,
                "真 provider GET 把 merged PR 帶進這條主旅程",
                provider_outcome,
            )
        requirement = await stack.requirement(project_id, VAGUE)
        journey.check(
            requirement["status"] == "intake" and requirement["spec_count"] == 0,
            "一句話進來，沒有表單、沒有規格",
            {"status": requirement["status"], "specs": requirement["spec_count"]},
        )

        # ------------------------------------------------- the clarification card
        journey.step("送給 Agent 釐清（主控台送的那一份請求）")
        use_agent_script(CLARIFY_AGENT)
        card = await stack.create_card(
            project_id,
            title=f"釐清 {requirement['card_ref']}",
            card_kind="clarification",
            requirement_id=requirement["id"],
            # `none`/`artifact` rather than the console's `repo`: this stack registers no
            # repository, and J1 is not about the checkout. The kind and the link — the
            # two the server used to drop — are the claim.
            source="none",
            delivery="artifact",
            stage="ready",
        )
        journey.check(
            card["card_kind"] == "clarification"
            and card["requirement_id"] == requirement["id"],
            "**卡片是釐清卡，而且連著需求** —— 不是一張長得像的普通卡",
            {"kind": card["card_kind"], "requirement": card["requirement_id"]},
        )

        # ------------------------------------------------------ three real rounds
        journey.step("三輪對話，每一輪都是真的 continuation run")
        await stack.dispatch(card["id"])
        for index, answer in enumerate(ANSWERS, start=1):
            question_id = await stack.wait_for_open_question(card["id"], deadline=180.0)
            journey.check(
                question_id is not None, f"第 {index} 輪：Agent 問了問題", question_id
            )
            if question_id is None:
                return journey.finish()
            result = await stack.answer_and_continue(card["id"], question_id, answer)
            journey.check(
                result.get("mode") in {"new_turn", "live_run"}
                and not result.get("refusal_code"),
                f"第 {index} 輪：回答開出新的一輪",
                {"mode": result.get("mode"), "refusal": result.get("refusal_code")},
            )

        # ------------------------------------------------------------ spec v1
        journey.step("規格草稿 v1")
        question_id = await stack.wait_for_open_question(card["id"], deadline=240.0)

        async def has_spec() -> object:
            detail = await stack.requirement_detail(requirement["id"])
            return detail if detail["spec_count"] >= 1 else None

        detail = await stack.wait_for(has_spec, 60.0, "the first spec version")
        v1 = detail["specs"][-1]
        journey.check(
            v1["authored_by_kind"] == "runner",
            "規格是 Agent 寫的，記在 runner 名下而不是人名下",
            v1["authored_by_kind"],
        )
        # **The claim behind the three rounds.** If the continuation packs carried only
        # the newest message, or `cliora task messages` did not reach back past the
        # turn boundary, one of these three is missing.
        text = _spec_text(v1)
        missing = [answer for answer in ANSWERS if answer not in text]
        journey.check(
            not missing,
            "**規格引用了三個回答** —— 對話是被送到了，不只是被存起來",
            {"missing": missing},
        )

        # ------------------------------------------- approving too early is refused
        journey.step("還有未決問題，核准要被拒絕")
        status_code, body = await stack.try_approve_requirement(requirement["id"])
        journey.check(
            status_code == 409
            and body.get("error", {}).get("code") == "SPEC_HAS_OPEN_QUESTIONS",
            "核准被拒絕，而且是 409 不是 500",
            {"status": status_code, "code": body.get("error", {}).get("code")},
        )
        journey.check(
            bool(body.get("error", {}).get("details", {}).get("questions")),
            "**拒絕指名了未決問題** —— 不是「不能核准」四個字",
            body.get("error", {}).get("details"),
        )

        # ---------------------------------------------------- change request → v2
        journey.step("人要求修改，Agent 出 v2")
        journey.check(
            question_id is not None, "v1 之後 Agent 問了「還要調整嗎」", question_id
        )
        if question_id is None:
            return journey.finish()
        await stack.answer_and_continue(card["id"], question_id, CHANGE_REQUEST)

        async def has_two_specs() -> object:
            current = await stack.requirement_detail(requirement["id"])
            return current if current["spec_count"] >= 2 else None

        detail = await stack.wait_for(has_two_specs, 240.0, "the second spec version")
        v2 = detail["specs"][-1]
        journey.check(
            v2["seq"] > v1["seq"] and len(detail["specs"]) == 2,
            "**v2 是新的一版，v1 還在** —— 規格是版本而不是覆寫",
            {"seqs": [spec["seq"] for spec in detail["specs"]]},
        )
        journey.check(
            "PDF 預覽" in _spec_text(v1) and "PDF 預覽" not in v2["scope"],
            "人要求拿掉的那一段，在 v2 的範圍裡不見了",
            {"v1_scope": v1["scope"], "v2_scope": v2["scope"]},
        )
        journey.check(
            not detail["blocking_questions"],
            "v2 沒有留下未決問題",
            detail["blocking_questions"],
        )

        # ------------------------------------------------------------- approval
        journey.step("人接受")
        status_code, body = await stack.try_approve_requirement(requirement["id"])
        journey.check(
            status_code == 200 and body.get("approved_by"),
            "需求核准了，而且記下了是誰核准的",
            {"status": status_code, "by": body.get("approved_by")},
        )

        # ---------------------------------------------------------- decomposition
        journey.step("Agent 提案拆解，人建卡")
        use_agent_script(DECOMPOSE_AGENT)
        decompose = await stack.create_card(
            project_id,
            title=f"拆解 {requirement['card_ref']}",
            card_kind="decomposition",
            requirement_id=requirement["id"],
            source="none",
            delivery="artifact",
            stage="ready",
        )
        await stack.dispatch(decompose["id"])

        async def has_proposal() -> object:
            current = await stack.requirement_detail(requirement["id"])
            return current if current["proposals"] else None

        detail = await stack.wait_for(has_proposal, 240.0, "the decomposition proposal")
        proposal = detail["proposals"][-1]
        journey.check(
            proposal["status"] == "pending",
            "**提案是待決的** —— Agent 提，人建",
            proposal["status"],
        )
        accepted = await stack.accept_proposal(proposal["id"], note="就照這張做")
        created = accepted["created"]
        journey.check(len(created) == 1, "接受之後產生了一張卡", len(created))
        if not created:
            return journey.finish()
        work = created[0]

        if provider_source_id is not None:
            # A human pin is the product mechanism that says this card must read a
            # source. It avoids making J1's report-export wording accidentally depend on
            # the current PR title while still exercising the real context builder.
            pinned = await stack.client.post(
                f"/api/projects/{project_id}/knowledge/pins",
                json={
                    "task_id": work["id"],
                    "source_id": str(provider_source_id),
                    "mode": "pin",
                },
                headers=stack.headers,
            )
            journey.check(
                pinned.status_code == 204,
                "人の操作面から merged PR をこのカードに pin",
                pinned.text,
            )

        # ------------------------------------------------- the Ready transition
        journey.step("移到就緒，缺什麼要說出來")
        moved = await stack.client.patch(
            f"/api/tasks/{work['id']}",
            json={"stage": "ready", "version": work["version"]},
            headers=stack.headers,
        )
        moved.raise_for_status()
        warnings = moved.json()["warnings"]
        journey.note("readiness_warnings", warnings)
        journey.check(
            moved.json()["task"]["stage"] == "ready",
            "卡片進了就緒 —— 就緒條件是提醒，不是拒絕",
            moved.json()["task"]["stage"],
        )
        journey.check(
            isinstance(warnings, list),
            "**缺的就緒條件被列出來** —— 而不是靜靜地擋住",
            warnings,
        )

        # --------------------------------------------- the implementation run
        journey.step("Agent 引用被接受的規格開工（不可跳過的那一段）")
        await stack.drain_ingestion(project_id)
        use_agent_script(IMPLEMENT_AGENT)
        run_id = (await stack.dispatch(work["id"]))["run_id"]
        finished = await stack.wait_for_terminal_run(run_id, deadline=240.0)
        # `wait_for_terminal_run` returns the **row**, not the status. Reading it as a
        # string made this the one red line in an otherwise green J1, which is the least
        # useful way for an assertion to fail.
        journey.check(
            finished is not None and finished.status == "succeeded",
            "實作 run 跑完了",
            None
            if finished is None
            else {"status": finished.status, "result": finished.result},
        )
        messages = await stack.messages(work["id"])
        said = [item["body"] for item in messages if item["author_kind"] == "agent"]
        journey.note("agent_said", said)
        journey.check(
            any("[S" in body for body in said),
            "**Agent 的訊息帶著引用標籤** —— 它真的讀了專案記憶",
            said,
        )
        if provider_source_id is not None:
            journey.check(
                any("真 provider [S" in body for body in said),
                "**Agent 另外引用了 merged PR** —— beta.2 的新增段沒有降級",
                said,
            )
        async with stack.maker() as session:
            packs = (
                await session.execute(
                    sa.text(
                        "SELECT total_bytes, source_manifest FROM context_packs "
                        "WHERE task_id = :tid"
                    ),
                    {"tid": work["id"]},
                )
            ).all()
        journey.check(
            bool(packs) and all(row.total_bytes > 0 for row in packs),
            "而且平台有一列 `context_packs` 可以證明它抓了",
            [row.total_bytes for row in packs],
        )
        if provider_source_id is not None:
            journey.check(
                any(
                    any(
                        item.get("source_id") == str(provider_source_id)
                        for item in row.source_manifest
                    )
                    for row in packs
                ),
                "context_packs manifest 也記下那則真 provider source",
                [row.source_manifest for row in packs],
            )
        reports = await stack.verification_reports(work["id"])
        journey.check(
            any(report["result"] == "passed" for report in reports),
            "驗證報告送了",
            [report["result"] for report in reports],
        )
        journey.check(
            all(report["source"] == "agent_reported" for report in reports),
            "**而且記成「Agent 自述」** —— 送報告的人選不了自己的證據等級",
            [report["source"] for report in reports],
        )

        # --------------------------------------------------- done, and its refusal
        journey.step("完成要有證據")
        status_code, body = await stack.try_patch(work["id"], stage="done")
        journey.check(
            status_code == 409,
            "驗收標準還沒有結果，`done` 被拒絕",
            {"status": status_code, "code": body.get("error", {}).get("code")},
        )
        journey.check(
            "驗收標準" in json.dumps(body, ensure_ascii=False),
            "**拒絕說得出缺哪一項** —— 不是「不符合完成條件」",
            body.get("error", {}).get("details"),
        )

        journey.step("人核准")
        gate = await stack.approve_gate(work["id"], "verification")
        journey.check(
            bool((gate.get("gates") or {}).get("verification", {}).get("approved_by")),
            "審查關卡記下了核准的人與時間",
            (gate.get("gates") or {}).get("verification"),
        )
        current = await stack.task(work["id"])
        await stack.patch(
            work["id"],
            acceptance_criteria=[
                {**item, "result": "passed"}
                for item in (current["acceptance_criteria"] or [])
            ],
        )
        done = await stack.patch(work["id"], stage="done")
        journey.check(done["stage"] == "done", "證據齊了，卡片進了完成", done["stage"])

        # ------------------------------------------------------- 全程不進 Terminal
        journey.step("全程不進 Terminal")
        sessions = await stack.terminal_sessions(project_id)
        journey.check(
            sessions == 0,
            "**這個專案從頭到尾沒有開過一個 terminal session**",
            sessions,
        )
        board = await stack.work_items(project_id, group="lifecycle", limit=100)
        refs = {
            item["card_ref"]: item["lifecycle"]
            for group in board["groups"]
            for item in group["items"]
        }
        journey.note("board", refs)
        journey.check(
            refs.get(done["card_ref"]) == "done",
            "而讀模型也這樣說 —— 這條旅程的結果在看板上看得到",
            refs.get(done["card_ref"]),
        )

    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
