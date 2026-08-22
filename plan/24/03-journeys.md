# 03 — 七條旅程（`CE-04`…`CE-07`）

編號沿用 [`research/03/10`](../../research/03/10-verification-and-exit.md) §3 與
[`plan/23/08`](../23/08-verification-and-exit.md) §4。**J1a 是不可降級的那一條。**

## 0. 兩處必須先更正的斷言

寫這一節時逐條核對了 `plan/23/08` §4 的斷言與現在的程式碼，**有兩條寫的不是程式在做的事**。
本期不改程式（D68），所以改的是斷言——並且說清楚為什麼。

### 0.1 J3：「卡片徽章來自投影欄」——目前前端不讀那個欄位

`CV-13` 的驗收語是「**本期先寫入不顯示**」，而它確實是這樣做的：
`tasks.waiting_for_actor` 與 `open_question_count` 由
`ConversationService._reproject` 唯一地寫入、由 `TaskDTO` 送出
（`schemas.py:1125-1129`、`tasks.py:243`），而 `frontend/src/` 裡
**沒有任何一處讀它們**（`grep` 無結果）。畫面上那個「⚠ 等待你的回覆」徽章，
來源是 `openQuestion`——server 回的 questions 清單
（`ConversationPanel.vue:46`），不是投影欄，也不是「最後一則訊息的 kind」。

**所以 J3 的斷言拆成兩句**，各自證明一半：

| 斷言 | 怎麼證 |
|---|---|
| 伺服器**算對了**：`GET /api/tasks/{id}` 的 `waiting_for_actor == "human"`、`open_question_count == 1` | API 斷言 |
| 瀏覽器**沒有猜**：徽章出現，且它的來源是 questions 清單 | 畫面斷言 ＋ `GATE-CV-NO-CLIENT-WAITING-DERIVATION`（它比對的是「最後一則訊息是 question」這個 idiom） |

投影欄真正被畫出來是 `beta.1` 的 `PX-` 工作。本期能證明的是它**被算對了**，
而那正是 `beta.1` 會依賴的東西。

### 0.2 J1a：「只有人類的 `decision` 讓 readiness 前進」——`decision` 不改任何 readiness

`decision` 這個 kind 在 `backend/app/` 裡只有兩個出現點：
`conversation.py:65` 的常數與 `agents.py:692` 的權限檢查
（沒有 `task.approve` → 403）。**它沒有任何 readiness 副作用**，
這是刻意的，也正是出口條件 8（「Agent `proposal` 不改正式 readiness」）成立的原因。

真正會改 readiness 的是 V2.5 既有的路徑——
`POST /api/requirements/{id}/approve` 與 `POST /api/proposals/{id}/accept`
（`requirements.py:205,239`），兩者都是 human-only。

**所以 J1a 的斷言改成三句**：

1. proposal 之後，卡片的 readiness／`stage`／`gates` **完全沒有變**；
2. 人類的「接受」寫進一則 `kind='decision'` 的訊息，作者是人、`author_kind='user'`；
3. **run token 送同一則 `decision` 會拿到 403 `AGENT_CANNOT_DECIDE`**（這條就是 J9，在 J1a 裡順帶再證一次）。

這三句是可執行的；原句「只有人類的 decision 讓 readiness 前進」則描述了一個
**沒有人實作、而且刻意不實作**的行為。`CE-15` 要把這一段回寫進 `plan/23/08` §4。

---

## 1. 旅程總表

| # | 旅程 | 層（D69） | 檔案 | 出口條件 |
|---|---|---|---|---|
| **J1a** | 三輪釐清 ＋ proposal ＋ 要求修改 ＋ 接受 | 瀏覽器 | `conversation.spec.ts` | **11** |
| J3 | 認領 → Running → 提問 → 顯示等待 | 瀏覽器 | `conversation.spec.ts` | 19（補強） |
| J5 | answer 之後 daemon 崩潰重啟 → 恰好一個 turn | API | `journeys/j5_chaos.py` | **5** |
| J6 | 20 則 comment 不喚醒 | API | `journeys/j6_comments.py` | 6（旅程層） |
| J7 | run 失敗 → 顯示原因 → 再派工 → 對話保留 | 瀏覽器 | `conversation.spec.ts` | 12（補強） |
| J8 | 兩人同時回答同一問題 | API | `journeys/j8_concurrent.py` | **2** |
| J9 | Agent 送 `decision` → 403 ＋ audit | API | `journeys/j9_decision.py` | 9（旅程層） |

J6 與 J9 已有等價的整合測試（`test_a_comment_does_not_wake_an_agent`、
`test_a_run_credential_cannot_write_a_decision`）。**仍然要寫成旅程**，
理由是那兩條測試都在同一個行程裡用同一個 session——
它們證明的是服務層的性質，不是「一個真的 run token 走 HTTPS 進來會被擋」。

---

## 2. J1a — 三輪釐清（`CE-05`，不可降級）

### 前置

`E2E_RUNNER=1`、`E2E_CONVERSATION=1`、`E2E_AGENT_SCRIPT=scripts/cv/agent/clarify.sh`。
卡片：`card_kind: clarification`、`source: none`、`delivery: none`、`stage: ready`
（與 `measure-answer-to-turn.py:_card` 相同的形狀——那張卡不需要 repo）。

### 步驟與斷言

| # | 動作 | 斷言 |
|---:|---|---|
| 1 | 瀏覽器登入 → `/projects/{id}/tasks/{taskId}` | 「對話」區塊在，composer 只有「留言」一顆按鈕 |
| 2 | 按「派給 Agent」 | `task_runs` 出現一列 `turn_seq=1`、`parent_run_id IS NULL` |
| 3 | 等 Agent 問 Q1（≤60s） | 串上出現 QuestionCard；徽章「⚠ 等待你的回覆」出現；composer **多出**「↩ 回覆並繼續」 |
| 4 | 輸入 A1，按「回覆並繼續」 | 提示語是「已回覆，並排入新的一輪。」（`mode == "new_turn"`）；`task_runs` 多一列 `turn_seq=2`、`parent_run_id` 指向第一列 |
| 5 | 等 Q2 → 回 A2 | `turn_seq=3`；**seq 連續無洞**：`SELECT array_agg(conversation_seq ORDER BY conversation_seq)` 是 `1..n` |
| 6 | 等 proposal | 串上出現 ProposalCard，含「接受」「要求修改」兩顆按鈕；**卡片 `stage` 與 `gates` 與步驟 2 之後完全相同**（§0.2 斷言 1） |
| 7 | 按「要求修改」→ 填理由 → 送出 | 一則 `kind='decision'`、`author_kind='user'` 的訊息；新的一輪 `turn_seq=4` |
| 8 | 等 proposal v2 | 舊的 ProposalCard 標示「已取代」，新的可操作（`newestProposalSeq`） |
| 9 | 按「接受」 | 第二則 `decision`；**readiness 仍然沒有變**（§0.2） |
| 10 | 全程 | **沒有任何一步進入 Terminal 頁面**：斷言 `page.url()` 從未落在 `/sessions` |

### 為什麼第 10 步要寫成斷言而不是靠自覺

出口條件 11 的字面是「三輪釐清 ＋ spec proposal ＋ 要求修改 ＋ 接受**可在同一 Drawer 完成**」。
一條「碰巧沒有開 Terminal」的旅程與一條「證明不需要 Terminal」的旅程，
差別就在有沒有人把它寫下來。用 `page.on("framenavigated")` 收集 URL，
最後斷言集合裡只有 `/login`、`/projects/…` 兩種前綴。

### 時間預算

四輪 ×（5s poll ＋ 子行程啟動）≈ 25s，加上瀏覽器操作，**單條旅程預算 3 分鐘**。
playwright 的預設 30s timeout 不夠，這條要 `test.setTimeout(180_000)`。

---

## 3. J3 — 提問 → 顯示等待（`CE-04`）

| # | 動作 | 斷言 |
|---:|---|---|
| 1 | 派工 → 等 Agent 提問 | `task_questions` 一列 `state='open'` |
| 2 | API | `GET /api/tasks/{id}` 的 `waiting_for_actor == "human"`、`open_question_count == 1`（§0.1） |
| 3 | 瀏覽器重新整理 | 徽章在；QuestionCard 是 open 樣式（**較粗的左邊框**，不是等待色——`plan/23/10` §2.9） |
| 4 | run 的狀態 | `task_runs` 那一列 `status='succeeded'`、`result='awaiting_input'`（D59 的推導），**而且租約已釋放** |

第 4 條是 J3 真正的價值：畫面上「還在等你」與資料庫裡「run 已經結束」
**同時**成立，正是這一期的核心主張。

---

## 4. J5 — chaos（`CE-06`）

**這一條是出口條件 5，也是 SR-1 finding 3 裡最重的一條。**

```text
① 造一個等待中的 run（parent run ＋ open question）
② POST /questions/{qid}/answer {resume:true}   ← 記下回應時間
③ 立刻 scripts/cv/daemon-ctl.sh kill           ← SIGKILL 整個 process group（D75）
④ scripts/cv/daemon-ctl.sh start + wait-online
⑤ 等 continuation 被認領（≤60s）
⑥ 斷言
```

### 六條斷言

| # | 斷言 | SQL / 檢查 |
|---:|---|---|
| 1 | **恰好一個 continuation** | `SELECT count(*) FROM task_runs WHERE resumed_question_id = :qid` → `1` |
| 2 | 那個 run 真的被認領且啟動 | `claimed_at IS NOT NULL AND started_at IS NOT NULL` |
| 3 | question 是 `answered`，且只有一則 answer | `task_questions.state`、`count(*) FROM task_messages WHERE kind='answer'` → 1 |
| 4 | seq 沒有洞 | `conversation_seq` 連續 |
| 5 | Agent 讀得到那則 answer | continuation 的 `input_from_seq <= answer.seq <= input_to_seq` |
| 6 | 舊的 run 沒有復活 | parent run 的 `status` 未改變 |

### 兩個一定要處理的時序陷阱

**① 殺得太晚等於沒殺。** 如果 daemon 在被殺之前已經 poll 到了那個 continuation，
測到的是「認領之後崩潰」，那是另一個（也有價值、但不是這一條）性質。
做法：**answer 之後立刻殺**，並斷言殺的當下 `claimed_at IS NULL`。
若不成立，旅程要**明說自己測到的是哪一種**，而不是照樣綠。

**② 殺得太早也不對。** 在 answer 的 HTTP 回應回來之前殺 daemon，
測到的是「Central 單獨運作」——daemon 根本還沒有參與。
所以順序是：等 201 回來 → 讀 `AnswerResult.mode == "new_turn"` → 殺。

### 為什麼用 `resumed_question_id` 而不是 `parent_run_id` 計數

`uq_task_runs_continuation` 是 `(parent_run_id, resumed_question_id)` 上的唯一索引。
只數 `parent_run_id` 的話，一個 parent 底下本來就可能有多輪（不同 question）；
唯一性成立的維度是這一對。`plan/23/08` §4 的原文寫的就是
`WHERE resumed_question_id = ?`，這裡沿用。

---

## 5. J6 — 20 則 comment 不喚醒（`CE-04`）

```text
① 造一個等待中的 run（question open，run 已終結）
② 連送 20 則 kind='comment'
③ 斷言：task_runs 的列數不變、question 仍 open、waiting_for_actor 仍是 human
```

**加一條 `plan/23` 的整合測試沒有的斷言**：其中第 10 則帶
與第 9 則相同的 `idempotency_key` 與**相同內容** → 回 `200` 而不是 `201`，
且訊息總數是 19 不是 20。冪等在旅程層走一次 HTTP，
是因為 `200 vs 201` 這件事只有真的 HTTP 回應說得出來。

**還要證反面**：run **還活著**（`waiting_for_input`，行程仍在輪詢）時，
一則 comment **會**關閉 question 但**不**建立 turn——那是 D67，
`plan/23` 實作時新增的規則，而它目前只有單元測試。
旅程版本：起一個會輪詢的 Agent（`clarify.sh` 的變體，`cliora task wait --timeout 30`），
送一則 comment，斷言 question 關了、`task_runs` 列數不變。

---

## 6. J7 — 失敗 → 顯示原因 → 再派工（`CE-07`）

依賴 `CE-01` 的第 ② 項（fakecli 造得出失敗）。

| # | 動作 | 斷言 |
|---:|---|---|
| 1 | 用會失敗的 agent 腳本派工（先 `cliora task ask` 再 exit 1） | run `status='failed'`；**question 仍然 open** |
| 2 | 瀏覽器看卡片 | 失敗原因顯示在 run 區塊；對話串**完整**（那則 question 在） |
| 3 | 按「派給 Agent」再派一次 | 新的 run；`conversation_seq` 從上一輪的最大值繼續，**沒有重新從 1 開始** |
| 4 | 新的 run 讀得到舊對話 | 情境包裡有那則未決問題（`render_continuation_context` 的第 2 段：「不論多舊，全部帶上」） |

第 1 步的斷言值得說明：**一個失敗的 run 不會關掉它問過的問題**。
這是 `finish()` 推導的另一半，而目前沒有任何測試涵蓋
「失敗 ＋ open question」這個組合（既有測試涵蓋的是 `complete` ＋ open question）。
如果它紅了，那是一個真的缺陷，處置照 D68 的表。

---

## 7. J8 — 兩人同時回答（`CE-07`）

```python
# 兩個請求真的同時在飛，用 asyncio.gather 而不是兩次 await
first, second = await asyncio.gather(
    answer(client_a, question_id, "A 的答案"),
    answer(client_b, question_id, "B 的答案"),
    return_exceptions=True,
)
```

| 斷言 | 值 |
|---|---|
| 一個 201、一個 409 | `sorted(status_codes) == [201, 409]` |
| 409 的 body | `code == "QUESTION_ALREADY_ANSWERED"`，`details` 含 `answered_by`／`answered_at` |
| 訊息 | `kind='answer'` 恰好一則 |
| continuation | `count(*) WHERE resumed_question_id = qid` → 1 |
| 輸的那一方打的字 | **沒有被寫入**——這是刻意的：answer 的 body 屬於那個 question，第二個人要另外留言 |

最後一列是這條旅程最容易被寫錯的地方。`plan/23/03` §2 的承諾是
「使用者打的字在**任何失敗後都不消失**」，那是**前端草稿**的承諾
（`MessageComposer` 的 localStorage），不是「伺服器會保存輸的那一則」。
旅程要分別證明兩件事：伺服器只寫一則；瀏覽器的 textarea 還留著那段文字。

**兩個「使用者」怎麼來**：兩組 access token，同一個帳號即可——
併發控制的維度是 question 不是 user。若要更真實，用 `scripts/pj/seed_users.py`
建第二個帳號；本旅程不需要，寫進註解說明為什麼不需要。

---

## 8. J9 — Agent 送 `decision`（`CE-07`）

```text
① 派工，讓 Agent 拿到一個真的 run token（.cliora/context/run.token）
② 用那個 token 直接 POST /api/cli/runs/{id}/messages {kind:"decision"}
③ 斷言 403 + code AGENT_CANNOT_DECIDE
④ 斷言 audit 有一列，且 payload 不含 body
⑤ 斷言那張卡的 task_messages 沒有多出任何一列
```

**token 從哪來**：`E2E_RUNNER_WORK_DIR/<run-id>/.cliora/context/run.token`，
由 `runner.WriteContext` 寫下（`plan/23/10` §9.1 修正後的檔名）。
旅程直接讀那個檔——這同時是**第三次**證明那條縫是通的
（第一次是 `context_seam_test.go` 的單元測試，第二次是 `CE-01` 的最小 run）。

第 ④ 條要讀 audit 表並斷言 `payload` 的鍵集合裡沒有 `body`——
SR-1 §1.5 的「audit 只記 metadata」目前是由一條斷言 payload 形狀的整合測試守著，
旅程版本讓它涵蓋真的 HTTP 路徑。

---

## 9. 這七條旅程之外，刻意不做的三件事

| 不做 | 為什麼 |
|---|---|
| **J4**（從 My Work 開 Drawer 回答） | My Work 與 Drawer 是 `beta.1` 的 `PX-` 工作，本期沒有那個畫面 |
| **多瀏覽器矩陣** | 既有 `ci.yml` 的 e2e job 已經跑三個瀏覽器；本期七條旅程只在 chromium 跑，理由與 `v2-projects.yml` 現況相同（`--project=chromium --workers=1`）。**寫進 [`09`](./09-open-measurements.md)** |
| **真實 Agent（Claude／Codex）** | 旅程證明的是平台，不是模型。`fakecli` 讓每一輪的行為是決定性的——用真的模型，一條紅掉的旅程無法分辨是平台壞了還是模型今天不想問問題 |
