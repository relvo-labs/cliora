# 10 — 實作進度與證據

> **狀態：`CV-00`…`CV-13` 已實作（2026-08-16），收尾補齊至 2026-08-19。**
> `make check` 全綠、**八個 gate** 全 PASS、Central **1762** 條測試、前端 **686** 條、daemon 全綠。
> 出口條件 **21／23 通過**；效能已量測（§5），release note 與 SR-1 已產出。
> **實作與計畫的十二處差異在 §2；剩下的兩項在 §7；2026-08-19 那一輪複查在 §9。**
>
> 沿用 `plan/17/09`／`plan/19/09`／`plan/22/11` 的體例：
> **這裡記的是實際發生的事**，與計畫不同時，**以這裡為準並回寫計畫**。

## 0. 開工前的裁決單

### A 類 — 擋開工

| ☑ | 決策 | 計畫的答案 | 裁決 | 日期 |
|---|---|---|---|---|
| ☑ | **D44** contract 動不動 | 不動 | **不動** | 2026-08-16 |
| ☑ | **D59** process 結束時 run 怎麼收 | Central 推導 `awaiting_input` | **採用推導** | 2026-08-16 |
| ☑ | **D42** 放不放寬單一未答問題 | 不放寬 | **不放寬** | 2026-08-16 |
| ☑ | **D61** 歷史問題怎麼 backfill | 用現行規則判定 | **用現行規則** | 2026-08-16 |

### B 類 — 實作時依計畫的答案執行，未另行裁決

| ☑ | 決策 | 落地 |
|---|---|---|
| ☑ | **D60** continuation 的分支名 | 沿用 root run 的 seq（`root_run_id` 欄位 ＋ `run_branch(task, run, root_seq)`） |
| ☑ | **D65** 第四個 renderer ＋ gate | `render_continuation_context`；gate 的 `CHOOSERS` 從一個名字變成三個（見 §2.6） |
| ☑ | **D66** 兩種等待 | 都保留，投影只有一個寫入點 |
| ☑ | **D51** 保留／附件／大小 | 永久保留、不新增附件路徑、20000 ＋ `MESSAGE_TOO_LARGE` |

## 1. Ticket 狀態

| ticket | 狀態 | 證據 |
|---|---|---|
| `CV-00` | ☑ | `plan/19/README.md` 狀態句已更正並註明原因；`alpha.1` known limitations 六條寫進 `docs/release-note-requirements-and-decomposition.md`（**2026-08-19 補**，見 §9） |
| `CV-01` | ☑ | `docs/adr/0035-conversation-run-and-turn.md`；PRD §8.17；`FR-CONV-001`…`-010` 註冊（168→178） |
| `CV-02` | ☑ | ADR `0036`／`0037`／`0041`；`contracts/CHANGELOG.md` 的「not one byte」一節 |
| `CV-03` | ☑ | migration `0040`，兩張新表 ＋ 14 欄；upgrade→downgrade→upgrade schema 逐位元組相同 |
| `CV-04` | ☑ | `services/conversation.py`；cursor 分頁、冪等、九個 machine code、`MessagePageDTO` |
| `CV-05` | ☑ | `ConversationService.answer`：CAS ＋ 訊息 ＋ continuation，單一交易 |
| `CV-06` | ☑ | `/api/cli/runs/conversation/{input,ack}` ＋ `conversation_consumers` |
| `CV-07` | ☑ | `finish()` 推導、`enqueue_continuation`、分支繼承、reaper 兩段掃描 |
| `CV-08` | ☑ | `agentd` 0.13.0：`messages --after`／`wait`／`say --reply-to --kind`／`propose-spec` |
| `CV-09` | ☑ | `render_continuation_context` 四段 ＋ 16 KiB 預算 ＋ 省略說明 |
| `CV-10` | ☑ | `components/project/conversation/`（5 個檔案）＋ 13 條元件測試 |
| `CV-11` | ☑ | `ProposalCard`：權限、要求修改的必填理由、已取代標示 |
| `CV-12` | ☑ | `scripts/cv/`：八個 gate ＋ 15 條 conversation 整合測試 ＋ 7 條 Go 測試 |
| `CV-13` | ☑ | `tasks.conversation_seq`／`open_question_count`／`waiting_for_actor` ＋ `TaskDTO` |

## 2. 與計畫的差異（十二處）

### 2.1 ★ 新增 D67：一般留言在「run 還活著」時關閉問題

**計畫說**（[`00`](./00-execution-plan.md) §0.1 D42、[`03`](./03-conversation-api.md) §2）：
`comment` 不續跑；只有 `answer` 關閉 question。

**實際發生**：既有測試
`test_a_second_question_is_refused_while_the_first_is_unanswered` 立刻紅了。
它的情境是——Agent 問、**人用普通留言回**、Agent 再問。V2.5 的規則下第三步是允許的
（任何使用者訊息都算答了）；新規則下 question 仍 open，Agent 永遠不能再問。

**這不是測試過時，是一個真的陷阱**：一個沒有按「回覆並繼續」的人，
會讓一個還活著的 Agent 永久失語。

**所以改成**（`services/conversation.py::_close_questions_a_live_run_is_waiting_on`）：

| 提問的 run 狀態 | 一般留言的效果 |
|---|---|
| `waiting_for_input`（行程還在輪詢） | **關閉 question**（V2.5 的規則），但**不建立 turn** |
| 已終結 | question **維持 open**；否則卡片會看起來閒置，而其實沒人在做事 |

兩條計畫的承諾都還成立：`comment` 不建立 turn、`answer` 不核准任何東西。
新增測試 `test_a_comment_unblocks_an_agent_that_is_still_running` 與
`test_a_comment_does_not_wake_an_agent` 各守一半。

**回寫**：[`01`](./01-decisions-and-governance.md) 應新增 D67；
[`03`](./03-conversation-api.md) §2 的表要補這一列。

### 2.2 欄位 12 → 14

`root_run_id`（D60）與 `resumed_question_id`（`uq_task_runs_continuation` 的另一半）
都是寫計畫時才發現的。[`02`](./02-data-layer.md) 已在寫作當下更新，
[`research/03/08`](../../research/03/08-data-model-and-contract.md) §1 也已經是 14 欄。

### 2.3 reaper 需要兩段掃描，不是一段

**計畫說**（[`04`](./04-answer-resume-and-turns.md) §4）：把 job B 從掃 run 改成掃 question。

**實際發生**：`test_an_unanswered_question_blocks_the_card_and_says_why` 紅了。
`run.progress` 的 `waiting_for_input` 旗標可以在**沒有任何 question** 的情況下
把 run 停在那個狀態，而那種 run 沒有 question 列可掃——它會永遠佔住租約。

**所以改成**：`_expire_waiting`（掃 question）＋ `_expire_parked_runs`
（掃沒有 question 的 parked run）兩段，分開而不是合併，因為它們回答的是不同問題。

### 2.4 continuation 被拒時回 201 ＋ `mode="refused"`，不是 409

**計畫說**（[`01`](./01-decisions-and-governance.md) D62）：answer 寫入、continuation 不建立、**回 409**。

**實作時發現**：那需要「先 commit 再 raise」，交易狀態很脆弱；而更根本的是
**回應碼會說謊**——answer 確實建立了，回 409 說的是「你的請求失敗了」。
一個 409 的 body 還要說「不過我們存下來了」，是更難讀的東西。

**所以改成**：`AnswerResult.mode = "refused"` ＋ `refusal_code`，HTTP 201，
卡片上留一則 `system` 訊息說明原因。前端對四種 mode 各說一句不同的話。

### 2.5 secret redaction 放在 `services/secrets.py`

**計畫說**（[`03`](./03-conversation-api.md) §10）：「Central 端在 message POST 也要跑一次」。

**實作時發現**：`GATE-SC-SINGLE-DECRYPT` 斷言**恰好一個模組**能把機密還原成明文，
理由是「每多一個呼叫者就多一條安全審查要追的路」。把 helper 放在別處會讓那個數字變成 2。

**所以改成**：`SecretService.redact()`，同一個模組，**不寫 audit、不動 `last_used_at`**
——沒有東西被交付，讀值正是為了不儲存它。

### 2.6 `GATE-RQ-CONTEXT-DISPATCH` 的 chooser 從一個變成三個名字

`_context_for` 仍是唯一的分派點，但它把「這張卡的種類會產生什麼」抽成 `_base_context`，
把 continuation 的組裝放進 `_continuation_context`。gate 的 `CHOOSERS` 集合列出三個，
形狀不變——**一處決定**這個性質仍成立，只是那一處現在有三個具名步驟。

### 2.7 `decision` 的權限檢查用 `may_perform` 依賴

`test_authorization_logic_is_confined_to_two_modules` 禁止 route 呼叫 `has_action`。
改用既有的 `may_perform(TASK_APPROVE)` 依賴（`task.force_done` 的先例）：
依賴給布林，route 決定。

### 2.8 `GATE-CV-CONTRACT-FROZEN` 的範圍是 `contracts/v1/`

**計畫說**：`contracts/` 全樹 sha256。

**實作時發現**：`CV-02` 要求在 `contracts/CHANGELOG.md` 寫「本期不動 contract 及理由」
——那句話本身會讓 gate 紅。**一個被解釋弄紅的 gate，會用刪掉解釋來變綠**
（`plan/18/09` §3 item 15 記過同一種失敗）。

**所以改成**：digest 只涵蓋 `contracts/v1/`（schema ＋ fixture，daemon 真正解碼的東西）。
`scripts/cv/capture-baseline.sh` 把理由寫在檔案裡。

### 2.9 `QuestionCard` 用形狀而不是 `--run-waiting`

`staticGuards.test.ts` 把等待色保留給 `BaseBadge` 與看板卡片（`plan/19` D24）。
question card 的 open 狀態改用**較粗的左邊框**，顏色與文字由徽章負責。
「不只用顏色」反而更嚴格地成立了。

### 2.10 `test_a_decision_needs_task_approve` 的前提是錯的

Developer **持有** `task.approve`——`rbac.py:103` 明說兩者的持有者刻意相同，
拆開的全部作用是「憑證的 scope 排得掉核准」。所以那條測試改成斷言真正的性質：
人寫得到 `decision`，run token 寫不到。

### 2.11 `GET /messages` 的回應形狀變更，改到三個消費者

計畫說兩個（前端 client、CLI）。實際是三個：還有
`backend/tests/db/test_run_credential.py` 的一條斷言。
三個都在本 repo 內、都在本期改完，前提成立。

### 2.12 `agentd` 版本要改兩個地方

`cmd/agentd/main.go` 的 `version` 與 `daemon/VERSION`，由
`TestVersionMatchesTheVersionFile` 綁在一起。

## 3. Gate 結果

```text
V2-C1 gates (baseline: artifacts/cv/local/baseline, f91d9c4)
  PASS  GATE-CV-{PROJECTION-ONE-WRITER,CONTINUATION-REFUSALS,APPEND-ONLY,NO-CLIENT-WAITING-DERIVATION}
  PASS  GATE-CV-CONTRACT-FROZEN
  PASS  GATE-CV-TOUCH-LIST
  PASS  GATE-CV-NO-LOG-IN-THREAD
  PASS  GATE-CV-MIGRATION-ROUNDTRIP
  PASS  GATE-RQ-CONTEXT-DISPATCH (re-run)
  PASS  GATE-SC-SINGLE-DECRYPT (re-run)
```

八個 gate 全 PASS（四個在第一行的 Python 程序裡）。`GATE-CV-MIGRATION-ROUNDTRIP` 沿用
`scripts/ar/gate-migration-roundtrip.sh`，只換降級目標——那個問題
（「降級之後 schema 是否逐位元組回到基線」）與 V2.2 問的是同一個，
第二份實作會在其中一份被修的第一天就不一致。基線由
`scripts/cv/capture-baseline.sh` 產生（`COMMIT` ＋ `contract-v1.sha256` ＋ `schema.txt`）。

## 4. 測試計數

| 套組 | 基線（`alpha.1`） | 本期後 | 新增 |
|---|---:|---:|---:|
| Central（pytest） | 1727 | **1762** | +35 |
| daemon（go test） | 全綠 | 全綠 | +7 |
| frontend（vitest） | 673 | **686** | +13 |

新增的 Central 測試集中在 `backend/tests/db/test_conversation.py`（15 條），
分成三組：**唯一性**（序號、冪等）、**原子性**（CAS、併發、留言不喚醒）、
**不可能性**（run token 不能決策、Viewer 不能發言、cursor 超前被拒）。

## 5. 效能量測

**已執行（2026-08-19）。** 20 個樣本、乾淨資料庫、真的 daemon 在輪詢：

```text
answer → turn 開始      P95 5.00s   中位數 4.94s   最差 5.59s   （目標 < 10s）
  answer commit          中位數 0.014s    ← Central
  queued → claimed       中位數 4.912s    ← runner 的 5 秒 poll
  claimed → 子行程啟動     中位數 0.016s    ← runtime（此處是 fakecli）
```

**幾乎整個延遲就是 poll 間隔**，這正是 [`08`](./08-verification-and-exit.md) §6 說
「如果是第一段，那就是 D44 的證據」的那一段。D44 選擇不動 contract 的代價，
量出來是平均半個 poll 間隔，其餘都在毫秒級。

重跑（輸出落在 `artifacts/*/local/`，與基線同一個慣例，不進版本控制）：

```bash
dropdb cliora_e2e && createdb cliora_e2e      # 見下面那個陷阱
CLIORA_DATABASE_URL=postgresql+asyncpg://…/cliora_e2e E2E_RUNNER=1 \
  scripts/e2e/run-stack.sh \
  uv run --project backend python scripts/cv/measure-answer-to-turn.py --samples 20
```

工具是 `scripts/cv/measure-answer-to-turn.py`，跑在 `E2E_RUNNER=1` 的 e2e 堆疊裡
（`scripts/e2e/run-stack.sh` 本期新增的 opt-in runner 模式）。
量到的區間是真的：人的回覆走 HTTP 進去，碼錶停在**真的 daemon** 寫的
`claimed_at`／`started_at` 上。**被造出來的是回覆之前的東西**——parent run 與那個
未答問題是直接寫進去的，因為那不在被量的區間上，而讓它自然發生只會替 setup 加上
一個與量測無關的競態。第三段是這個堆疊的行程啟動時間，與 Claude／Codex 無關，
所以它分開列。

**一個量測本身的陷阱，記在這裡因為它會再發生一次**：第一次跑出了一個 29.9 秒的樣本，
而原因不是平台——是同一個資料庫裡上一輪留下的 run 還在佔 runner 的 `max_concurrent`
名額。腳本現在會在開始前數還在飛的 run，**不是零就拒絕跑**：那個數字若被印出來，
就會被引用。

## 6. 出口條件

| ☑ | # | 條件 | 證據 |
|---|---:|---|---|
| ☑ | 1 | answer → 新 turn P95 < 10s | **P95 5.00s**（20 樣本）；`artifacts/cv/local/answer-to-turn.json`、§5 |
| ☑ | 2 | 每則 answer 至多一個 continuation | `test_two_people_answering_one_question_produce_one_turn` ＋ `uq_task_runs_continuation` |
| ☑ | 3 | retry 不產生重複訊息 | `test_the_same_idempotency_key_writes_one_message`（送 10 次，1 則） |
| ☑ | 4 | process 結束後 conversation 可從 DB 恢復 | `test_answering_closes_the_question_and_queues_exactly_one_turn` |
| ☐ | 5 | daemon 重啟後只處理一次 | **未做 chaos 測試**（§7） |
| ☑ | 6 | `comment` 不誤 resume | `test_a_comment_does_not_wake_an_agent`（20 則留言，run 數不變） |
| ☑ | 7 | `answer` 不誤 approve | answer 路徑不碰 `gates`；`GATE-CV-APPEND-ONLY` |
| ☑ | 8 | Agent `proposal` 不改 readiness | proposal 只是訊息，無 readiness 寫入路徑 |
| ☑ | 9 | run token 不能寫 `decision`、不能跨 task | `test_a_run_credential_cannot_write_a_decision`、既有 `_own_task` 回歸 |
| ☑ | 10 | Viewer 不可發言 | `test_a_viewer_reads_the_thread_and_cannot_write` |
| ☐ | 11 | 三輪釐清在同一畫面完成 | **未做 E2E**（§7） |
| ☑ | 12 | 清除 run log 後 conversation 完整 | `test_deleting_every_run_log_leaves_the_conversation_intact` |
| ☑ | 13 | 不以 raw log 作為 conversation 依賴 | `GATE-CV-NO-LOG-IN-THREAD` |
| ☑ | 14 | Secret value 不出現在 message | `test_a_secret_value_is_redacted_before_it_is_stored` |
| ☑ | 15 | contract 未變更 | `GATE-CV-CONTRACT-FROZEN` |
| ☐ | 16 | 未升級的 `agentd` 0.12.0 節點行為不變 | **未在真實節點驗證**（§7） |
| ☑ | 17 | `0040` 可 downgrade 且 schema 相同 | `GATE-CV-MIGRATION-ROUNDTRIP` |
| ☑ | 18 | backfill 的 question 判定與現行規則一致 | migration §⑧ 用 V2.5 的謂詞；`0040` 在有資料的庫上跑過 |
| ☑ | 19 | 前端不推導等待狀態 | `GATE-CV-NO-CLIENT-WAITING-DERIVATION` ＋ 元件測試 |
| ☑ | 20 | 使用者打的字在任何失敗後都不消失 | `test the draft survives a failed send` |
| ☑ | 21 | `make check` 全綠、七個 gate 全 PASS | §3 |
| ☑ | 22 | release note 列出 known limitations | `docs/release-note-ticket-conversation.md`，六條 |
| ☐ | 23 | `v2` → `dev` 由人工核准 | 流程，未執行 |

**21 項通過，2 項未完成。** 兩項都列在 §7，沒有一項是「做了但沒證明」。

出口條件之外還有一項 `research/03/CHECKLIST.md` §2 記著的：**SR-1 安全審查**。
[`docs/security-review-v2c1.md`](../../docs/security-review-v2c1.md) 已寫出並公開，
**但未簽核**——它自己的兩項未結發現就是下面 §7 的那兩項。

## 7. 未完成（兩項）→ **兩項都已於 2026-08-21 由 [`plan/24`](../24/README.md) 完成**

| # | 項目 | 結果 |
|---:|---|---|
| 1 | **chaos ／ 六條 E2E**（出口 5、11） | ☑ **七條旅程全部執行且通過**（J0 preflight ＋ J1a／J3／J5／J6／J7／J8／J9）。`GATE-CE-JOURNEY-COVERAGE` 拒絕任何一條被 skip 的執行。詳見 [`plan/24/10`](../24/10-implementation-status.md) §4 |
| 2 | **未升級節點的實測**（出口 16） | ☑ **已實測**，而答案比原本的說法窄：**線上（wire）相容，「完成」不相容**。0.12.0 帶著一個 V2.2 就在的缺陷（`CE-17`），沒有任何測試碰得到它，因為從來沒有人讓一個真的 daemon 把一個 run 跑完。修在 `agentd` 0.13.1 |

**而那兩項不只是被補上，它們各照出一個真的缺陷**——這正是「論證不是證據」這句話的代價：

| 缺陷 | 誰照出來的 | 影響 |
|---|---|---|
| `CE-16` run 的情境包沒有平台位址 | 第一條旅程的第一步 | run 裡的 `cliora` 從來連不上 Central；`CV-08` 的四個子命令在真的 run 裡從未成功 |
| `CE-17` `run.complete` 帶 `null git_remotes` 被靜默丟棄 | 第一次讓 run 跑到結束 | **沒有 git remote 的卡（每一張釐清卡）的 run 永遠不會結束**，症狀是租約過期 |

**2026-08-19 補齊的三項**（原本列在這裡）：效能量測（§5）、release note、SR-1 安全審查。
詳見 §9。

**已於收尾補齊的三項**（原本列在這裡）：

| 項目 | 落地 |
|---|---|
| `GATE-CV-MIGRATION-ROUNDTRIP` 腳本化 | `scripts/cv/gates.sh` ＋ `scripts/cv/capture-baseline.sh` 的 `schema.txt`；PASS |
| redaction 的單元測試 | `test_a_secret_value_is_redacted_before_it_is_stored`——斷言在**儲存的那一列**上，不是在回應上，因為被防止的正是儲存；並斷言 `last_used_at` 仍是 NULL（讀值以避免儲存，不是一次交付） |
| metrics | 四個計數器（messages／turns／duplicate_turn／question_expired）。**六個縮成四個**：兩個 histogram（`answer_to_turn_seconds`、`turns_per_task`）需要真實 runner 才量得到，與 §7 第 1 項同一個原因 |

**另外兩件本期刻意不做**，記在這裡以免被當成遺漏：

- **`POST /api/tasks/{id}/conversation/resume`**（[`research/03/02`](../../research/03/02-phase-c1-ticket-conversation.md) §6 列過）。
  沒有 answer 的續跑，要餵給新 turn 的 input 範圍是空的——它會啟動一輪讀不到任何新東西的執行。
  真正需要的動作是「重新派工」，而那個 endpoint 已經存在。**建議從計畫刪除而不是補做。**
- **人類編輯訊息**（ADR 0041 §5 已記為本期不做）。

## 8. 回寫清單

| 文件 | 回寫什麼 | 狀態 |
|---|---|---|
| [`01`](./01-decisions-and-governance.md) | 新增 **D67**（§2.1） | ☑ |
| [`03`](./03-conversation-api.md) §2 | kind 表補「留言在 live run 時關閉 question」 | ☑ |
| [`04`](./04-answer-resume-and-turns.md) §4 | reaper 是兩段掃描 | ☑ |
| [`01`](./01-decisions-and-governance.md) D62 | 拒絕時回 201 ＋ `mode`，不是 409 | ☑ |
| [`research/03/02`](../../research/03/02-phase-c1-ticket-conversation.md) §6 | 刪掉 `conversation/resume` | ☑ |
| [`research/03/08`](../../research/03/08-data-model-and-contract.md) §1 | `alpha.2` 是 14 欄不是 12 | ☑ 已是 14（§1 表格第二列） |
| [`research/03/CHECKLIST.md`](../../research/03/CHECKLIST.md) | `alpha.2` 段落打勾 | ☑ `CV-12` 已補齊為 ☑（`plan/24` 的七條旅程）；`CE-` 那一段是新的 |
| `docs/adr/0035`（與 0036／0037／0041） | 狀態從 proposed 改 accepted（需人工核准） | ☐ **仍待人工**——清單在 [`docs/release-checklist-alpha2.md`](../../docs/release-checklist-alpha2.md) §3，含「同時追認在 proposed 狀態下已完成的實作」那一句 |

## 9. 2026-08-19 的收尾

深入複查本期時發現的五件事，以及對它們做的處置。**四件是文件與交付物的缺口，
一件是程式的缺陷**——而那個缺陷是這次複查真正的收穫。

### 9.1 ★ run 裡的 `cliora` 從來找不到自己的憑證

daemon 把憑證寫成 `.cliora/context/run.token`（`runner.WriteContext`），
而 CLI 只讀 `<id>.token`。**兩邊各自的單元測試都是綠的，中間那條縫沒有任何測試。**
症狀是一個 staging run 的一生都在對著回應正常的平台印「無法連線到 Cliora」，
最後以 `RUN_DELIVERY_INCOMPLETE` 收場——`CV-08` 那四個子命令在真的 run 裡從來沒通過。

修在 `4a9a016`：讀的一邊退回 `run.token`（`run.token` 這個名字是有承載的——
`GATE-SC-NO-SECRET-TO-DISK` 按名字排除它），缺憑證改用 `NoCredentialMessage`
說實話而不是謊報離線，測試放在 `internal/cli/context_seam_test.go`。

**測試的位置本身是一個決定**：它最自然的家 `internal/runner/` 在禁區清單上。
放在那裡會讓 `GATE-CV-TOUCH-LIST` 紅——而一個被真話弄紅的 gate，會用刪掉真話來變綠
（`plan/18/09` §3 item 15、本檔 §2.8 各記過一次）。所以測試放在可以動的那一邊。

**同一件事也暴露了那個 gate 的洞**：它用 `git diff` 比對基線，
而**從沒被 `add` 過的新檔案不在 diff 裡**。這個修正的測試檔就在禁區底下待著，
gate 一路是綠的，直到它被 stage。現在也問 `git status --porcelain --untracked-files=all`，
並且有一個負面測試（在禁區丟一個檔案，gate 必須紅）。

### 9.2 效能量測（出口 1）→ §5

為了量它，`scripts/e2e/run-stack.sh` 新增了 opt-in 的 `E2E_RUNNER=1`：
兩個 feature flag、`runner` 設定區塊、以及 Central 那一側的 runner 啟用開關
（`enabled` 刻意不是 `runner.register` 設得動的東西）。
`daemon/cmd/fakecli` 同時獲得一個 runner 模式（`-p` ＋ JSONL 事件流），
否則它會被判定為 not runner-capable 而拿不到任何工作。

**這一段基礎設施正是 §7 第 1 項缺的東西**——六條 E2E 現在缺的是旅程本身，不是堆疊。

### 9.3 `CV-00` 只做了一半

證據欄只有 `plan/19/README.md` 的更正；
[`research/03/01`](../../research/03/01-architecture-decisions.md) §2 的**六條缺口**
沒有進 `alpha.1` 的 release note。已補進
`docs/release-note-requirements-and-decomposition.md`，
並註明其中四條已由本期關閉——否則讀那份 note 的人會以為它們還開著。

### 9.4 SR-1 安全審查

[`docs/security-review-v2c1.md`](../../docs/security-review-v2c1.md)，
[`08`](./08-verification-and-exit.md) §5 的十三列逐條列出證據。
十二列通過，一列（未升級節點）是**論證而非證據**。**未簽核**，理由寫在它的 §6。

審查過程中順手校正一個數字：計畫一直寫「RBAC 24 個動作」，`len(ALL_ACTIONS)` 是 **27**，
而 `rbac.py` 與基線逐位元組相同——**是文件的數字錯，不是程式多了動作**。

### 9.5 四處文件互相矛盾

| 文件 | 原本 | 現在 |
|---|---|---|
| [`09`](./09-open-measurements.md) §1 | 說 `turns_per_task` 有埋點 | 那個 histogram 在實作時被砍了（§7），改寫 |
| 本檔 §8 | `research/03/08` 的「12 欄」待回寫 | 早就是 14 欄，打勾 |
| `research/03/CHECKLIST.md` `CV-12` | ☑ 含「E2E、chaos」 | ◑，並指向 §7 |
| `research/03/CHECKLIST.md` `CV-04` | 八個 machine code | 九個 |
