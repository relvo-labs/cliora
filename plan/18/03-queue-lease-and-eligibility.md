# 03 — `AR-05`：佇列、資格、租約與重排

本票是佇列半的核心。它**沒有新的 protocol 訊息**（那是 `AR-06`），也**沒有新的 API**
（那是 `AR-04`）——它是 `services/runs.py` 這個新模組，以及它掛進 `api/ws/nodes.py` 的四條分支。

> **2026-08-10 裁決改寫了 §3 與 §4。** 資格判定從六條件變成**四條件**
> （綁定與 labels 延後），`authorize_workspace()` 從這條路徑上**完全消失**
> （run 不使用 workspace 綁定），dispatch 的檢查順序跟著換。

## 1. 訊息怎麼掛進既有的 WS 迴圈

`node_gateway`（`backend/app/api/ws/nodes.py:121`）的控制迴圈是一條 `if/elif` 鏈，
**最後一個分支是 `registry.resolve_response()`**，沒被前面接住的訊息會被當成
late／duplicate／unknown **丟棄並記一筆 `node_ws_unmatched_message` warning**。

所以本期新增的四個 node→central 型別，每一個都要**明確**加一條分支：

```python
elif message.type == "runner.register":
    await RunnerService(session).register(node_id, message.payload)
    await session.commit()
    await websocket.send_text(_frame("runner.registered", node_id, message.request_id, {...}))
elif message.type == "runner.poll":
    # 認領就發生在這裡（§2）。命中則直接回一個 run.offer 訊框。
    offer = await RunService(session).poll(node_id, message.payload)
    await session.commit()
    await websocket.send_text(_frame("run.offer", node_id, new_request_id(), offer or {"run_id": None}))
elif message.type in _RUN_EVENTS:          # accept / decline / lease_renew / progress
    await RunService(session).apply_event(node_id, message)
    await session.commit()
elif message.type == "run.log_chunk":
    RunLogBuffer.append(...)               # 記憶體，不 commit（§6）
elif message.type in ("run.complete", "run.failed"):
    await RunService(session).finish(node_id, message)
    await session.commit()
```

**`GATE-AR-DISPATCH-COVERAGE`**（`08-…md` §4）拿 contract 的型別 enum 反查這條鏈：
每一個 `runner.*`／`run.*` 且方向是 node→central 的型別，都必須在 `nodes.py` 裡出現一次。
漏一個的症狀是「訊息不見了但沒有錯誤」，那是本期最難查的 bug。

### 一條絕對不能寫的東西

**不得在這條迴圈（或它呼叫的任何服務）裡 `await registry.request(...)`。**
那個 future 是由**這條迴圈自己**呼叫 `resolve_response()` 解開的
（`registry.py:276` ← `nodes.py:276`），在迴圈裡等它必然逾時。
`GATE-AR-NO-REQUEST-IN-LOOP` 對 `api/ws/nodes.py` 與 `services/runs.py`／`services/runners.py`
做文字掃描，出現 `registry.request(` 就紅。

同理**不得 `asyncio.create_task` 去做需要 DB 的事**：那條連線只有**一個** `AsyncSession`
（`Depends(get_session)`），SQLAlchemy 的 AsyncSession 不可並行使用，
第一次併發就會炸在 `InterfaceError`。真的需要背景工作時開自己的 session
（`RunReaper` 就是這樣做的，§5）。

## 2. claim-then-offer

`runner.poll { runner_id, capacity }` 進來時，服務層做三步：

```text
1. 找出候選 run（§3 的四條件查詢），按 queued_at 取最多 `capacity` 個 id
2. 對每個候選 id 逐一嘗試原子認領，第一個成功的就是答案
3. 命中 → 組出 spec（含 source：repo URL ＋ ref）並發 run.offer；沒命中 → 回一個空的 offer

   **spec 的 `source` 在這裡才組出來**，用的是 run 上 dispatch 時的快照
   （`repository_id`／`source_kind`／`source_ref`，`02-…md` §2.3），不是現讀 `tasks`。
   repo URL 由 `project_repositories` 的三欄拼出（`04b-…md` §5.2）——
   **拼接發生在 Central，而 host allowlist 在 daemon 再驗一次**，兩層。
```

原子認領就是那一條 UPDATE：

```sql
UPDATE task_runs
   SET runner_id = :runner_id,
       status = 'claimed',
       claimed_at = now(),
       lease_expires_at = now() + :lease_timeout,
       runtime = :runtime
 WHERE id = :run_id
   AND runner_id IS NULL
   AND status = 'queued'
RETURNING id;
```

**回 0 列就是被別人領走了**，換下一個候選。這條 `WHERE` 是「雙重領取不可能」的唯一保證，
而且它是 `backend/app/` 裡**唯一**一個寫 `runner_id` 的地方——
`GATE-AR-SINGLE-CLAIM` 用文字掃描斷言 `SET runner_id` 只出現一次
（`run.decline` 走 `runner_id = NULL`，模式不同，掃描規則要能分辨）。

### 為什麼認領在 poll 當下，而不是等 `run.accept`

三條，前兩條是這個 repo 的事實不是偏好：

1. **Central 端不能在 WS 迴圈裡等回應**（§1 的死鎖）。
2. **daemon 端沒有為自己發出的請求做關聯表**：`dispatch()`（`connection.go:494`）
   只有一條 `switch env.Type`，`runner.poll` 送出去之後沒有任何東西在等它的答案。
3. 認領在 poll 當下之後，`run.accept` 與 `run.decline` 變成**開工回報**與**釋放**，
   而不是一個要處理競爭的協商。競爭窗口從「offer 送出到 accept 回來」縮成
   「同一條 UPDATE 的交易內」——也就是零。

代價寫進 ADR 0029：**一個領走之後就死掉的 runner，會讓那張卡等到租約逾時**（180 秒）
才回到佇列。這正是租約存在的理由，不是新增的問題。

### `run.decline`

runner 在收到 offer 之後發現自己開不了工（磁碟滿、runtime 剛好被停用）時發 `run.decline`。
服務層把 run 放回 `queued`、清空 `runner_id`／`claimed_at`／`lease_expires_at`，
**`attempt` 不變**，並在記憶體裡記一筆 `(run_id, runner_id) → now()+60s` 的冷卻，
讓同一個 runner 的下一次 poll 跳過它。

冷卻表是本期**唯一**一個不進 DB 的狀態。理由寫在程式碼裡：
它跨 Central 重啟不需要保留，重啟之後最壞情況是多一次 decline。

## 3. 四條件資格查詢

規劃原本寫五條件（`research/02/01` D17）。**2026-08-10 裁決之後本期只有四條**：
綁定（`project_agents`）延後到 V2.3，labels 比對是後續功能。

```sql
SELECT r.id, r.repository_id, r.source_kind, r.source_ref
  FROM task_runs r
  JOIN tasks t          ON t.id = r.task_id
  JOIN agent_runners ag ON ag.id = :runner_id AND ag.enabled     -- ① runner 啟用
 WHERE r.status = 'queued'
   AND t.stage = 'ready'                                          -- ② 卡片在 ready
   AND NOT EXISTS (SELECT 1 FROM task_dependencies d
                     JOIN tasks dt ON dt.id = d.depends_on_id
                    WHERE d.task_id = t.id AND dt.stage <> 'done')  -- ③ 相依滿足
   AND (r.runtime IS NULL OR r.runtime = ANY(:runner_runtimes))     -- ④ 能力（只比 runtime）
   AND (r.assigned_runner_id IS NULL
        OR r.assigned_runner_id = :runner_id)                       -- ⑤ 指定（D17b）
 ORDER BY r.queued_at
 LIMIT :capacity;
```

（編號到五是因為①是「這個 runner 現在能不能做事」而不是一個卡片條件；
ADR 0029 用「四條件」是把它算進 runner 的前置狀態。）

### 3.1 三個從這條查詢裡消失的東西，以及它們為什麼消失

| 消失的 | 原因 | 什麼時候回來 |
|---|---|---|
| `JOIN project_agents`（授權） | 裁決：現在每個 agent 都可以拉每個 project | **V2.3**，與 `project_secrets` 同期。SQL 裡留了註解標好它要插進哪一行——**插在最前面**，因為那時它授權的是機密 |
| `t.required_labels <@ ag.labels`（能力） | 裁決：label match 是後續功能 | 後續。欄位已在，**顯示但不比對**（`07-…md` §2） |
| `JOIN project_workspaces` ＋ `authorize_workspace()` | 裁決：run 不使用 workspace 綁定，它有自己的隔離目錄 | **永遠不會**。這是本期最重要的一個減法（見 §3.2） |

### 3.2 `authorize_workspace()` 從這條路徑上完全消失，而這是一個減法不是一個缺口

裁決之前，本計畫在這裡有一條「六條件的第六條」：runner 所在 node 上要有該 Project 的
workspace 綁定，而且 `authorize_workspace()` 要在認領當下重跑一次（紅線 2）。

**裁決把那整段拿掉了**，因為 run 不再碰 workspace。結果是三件事同時變好：

1. **`services/sessions.py:64` 的 `authorize_workspace()` 只剩一個呼叫者群組**
   （Session ＋ favorites），所以「兩份實作會漂」這個風險不必再擔一次。
2. **紅線 2 的適用範圍變乾淨**：它管使用者的 allowed root，而 Agent Run 從第一天就不在裡面。
   `research/02/00` §7 紅線 2 原本要解釋「隔離目錄為什麼不在 allowed root 內」，
   現在那句解釋在 V2.2 就成立。
3. **少一種「綁了 Project 但那台機器上沒有目錄」的無聲卡住狀態。**

換來的是一個新的前置條件，它落在 dispatch 而不是 poll：
**`source ≠ none` 的卡需要該 Project 登記過 repository**（§4 的第 ③ 步）。
這個檢查放在 dispatch 是刻意的——它是一個設定問題，
應該在人按下按鈕的那一刻就被指出來，而不是讓卡片安靜地排隊。

### 3.3 兩件仍然要寫進測試的事

1. **⑤ 不能被任何東西繞過。** 指定 A 的卡，B 來 poll 時候選集合必須是空的
   ——不是「B 領到了但被拒絕」，是**根本不在候選集合裡**。判準 1。
2. **`ORDER BY r.queued_at` 是唯一的排序。** 沒有優先權、沒有負載平衡、沒有 project 輪替
   （`research/02/00` §9）。這條 `ORDER BY` 就是「平台不做排程」在程式碼上的形式，
   而一條測試斷言它：兩張卡先進先出，即使第二張的 `risk` 是 `high`。

## 4. dispatch 的檢查順序與兩種失敗

檢查順序**寫死**（`00-…md` D13），因為錯誤訊息的可讀性取決於它：

```text
① 卡片本身能不能派
   stage=ready、相依滿足、沒有進行中的 run
② 本期做不到的宣告（D11）
   required_secrets 非空                  → 409 TASK_REQUIRES_SECRETS   （V2.3 起生效）
   delivery ∈ {branch,pull_request,existing_pr} → 409 TASK_DELIVERY_UNSUPPORTED（V2.3／V2.4）
③ source ≠ none 時：該 Project 有沒有登記 repository
   沒有                                   → 409 PROJECT_NO_REPOSITORY
   有但 host 不在平台的 allowlist 內        → 409 REPOSITORY_HOST_NOT_ALLOWED
④ 若指定了 runner
   a. runner enabled                      → 不過：409 AGENT_DISABLED
   b. runtime 相符                        → 不過：409 AGENT_RUNTIME_MISMATCH
⑤ 建立 task_runs（status=queued，快照 repository_id／source_kind／source_ref）→ 202
```

**③ 是裁決帶來的新一步，而且它取代了原本的第一順位。**
裁決之前最先擋下的授權類問題是「這個 runner 沒綁這個專案」（一個要 Admin 修的東西）；
現在是「這個專案還沒有登記 repository」（一個要在 Project Settings 修的東西）。
所以 409 的訊息要**直接指向那個畫面**，而不是只說「缺少設定」。

**④ 少了三個檢查**（綁定、node 上有 workspace、labels），這是裁決的直接後果。
剩下的兩個仍然足以支撐 D17b 邊界 2——**兩種失敗必須分得出來**：

| 情況 | 回應 | 卡片顯示 |
|---|---|---|
| 指定的 runner 不符資格（④a／④b） | `409` ＋ **指名是哪一個條件** | 不入佇列，dispatch 當下就擋下 |
| 指定的 runner 暫時離線或忙碌 | `202` 正常入佇列 | 「等待指定的 Agent：dev-vm-01（目前離線）」 |
| **沒有指定**，但目前沒有符合資格的 runner | `202` 正常入佇列 | 「等待可用的 Agent」 |

第二列與第三列的文案**逐字不同**，各有一條測試斷言字串——
分不出這兩種，使用者就分不出「我設定錯了」跟「再等一下就好」。

「有沒有符合資格的 runner」在第三列是一個**提示性的查詢**（不影響是否入佇列）：
把 §3 的資格查詢的 `runner_id` 條件拿掉跑一次，數量為零就用那句文案。
它是提示不是閘門——一台 runner 可能三秒後才註冊。

## 5. 租約 sweep（`RunReaper`）

一個週期性 sweep，不是 `shell_reaper` 的 per-item timer（`00-…md` D10）。
掛在 `main.py` 既有的 `lifespan` 上，沿用 `_rearm_shell_reaper`（`main.py:73`）的形狀：
**啟動時先 reconcile 一次**，然後進迴圈。

```text
間隔 = CLIORA_RUN_LEASE_TIMEOUT_S / 3（預設 60 秒）
每一輪，用自己的 AsyncSession（不是 WS 連線那一個）：

A. 租約逾時   status IN ('claimed','running') AND lease_expires_at < now()
              → status='lost'；然後重排（§6）
B. 等回覆逾時 status='waiting_for_input' AND waiting_since < now() - 24h
              → status='failed'、error_code='RUN_WAITING_TIMEOUT'
              → 卡片 stage='blocked'，訊息串寫一筆 event
C. log 保留期  task_runs.logs_expire_at < now() → 刪該 run 的 run_logs 整組
```

🆕 **A 判的是「runner 活著嗎」，不是「child 在前進嗎」**（D21）。
後者由 daemon 用事件流的 idle timer 在本地判，逾時送 `run.failed{RUN_IDLE_TIMEOUT}`。
**兩個機制刻意分開**：把租約續租改成「只在 child 有活動時才續」會讓
「runner 掛了」與「child 掛了」長得一樣，而它們的收斂路徑不同
（前者重排，後者是 run 失敗）。Central 這一側**不需要**知道 idle 的門檻值。

三件事要寫清楚：

- **`waiting_for_input` 也在租約續租的範圍內**（runner 仍活著，只是在等人），
  所以 A 的條件不含它；B 用的是另一個計時器 `waiting_since`。
  兩個計時器是刻意的：租約問的是「runner 還在嗎」，`waiting_since` 問的是「人還在嗎」。
- **sweep 一輪處理的列數有上限**（預設 200），超過就留到下一輪。
  一個 Central 停機兩天之後回來，不該用一條交易更新幾千列。
- **C 是一個刪除迴圈，要分批 commit**。與 A／B 放在同一輪但不同交易——
  log 清理失敗不該讓租約回收也失敗。

## 6. 重排

`lost` 是終態（`02-…md` §4 第 3 點）。重排**新建一列**：

```text
新 run：seq = 舊 seq + 1
        attempt = 舊 attempt + 1
        assigned_runner_id = 舊 assigned_runner_id     ← 維持指定（D17b）
        status = 'queued'
```

`attempt > CLIORA_RUN_MAX_ATTEMPTS`（預設 3）時**不建新列**，改成：

- `tasks.stage = 'blocked'`
- 訊息串一筆 `kind='event'`：有指定時「指定的 Agent `<name>` 連續 3 次未能完成」，
  無指定時「連續 3 次未能完成」——**兩句話不同**，與 §4 同一條理由。
- `activity_events` 一筆 `run.finished`，`actor_kind='system'`。

**維持指定要有測試**，而且測的是「run 上的快照」而不是「卡片上的欄位」：
測試流程是 dispatch 指定 runner A → run 變 `lost` → **在重排前把卡片的
`assigned_runner_id` 改成 runner B** → 重排出來的新 run 的 `assigned_runner_id`
仍然是 A。這是 `02-…md` §2.3 那個快照欄位存在的唯一理由，沒有這條測試它會被當成冗餘欄位刪掉。

## 7. run log 的接收（Central 側）

`run.log_chunk` **不 commit**，也不逐 chunk 寫 DB（`00-…md` D3）。

```text
RunLogBuffer（行程內，key = run_id）
  append(seq, data, truncated)
    - 累計位元組 > CLIORA_RUN_LOG_MAX_BYTES 時：不再收，設 truncated 旗標，
      累加 task_runs.log_truncated_bytes（下次 flush 時一起寫）
    - 緩衝 ≥ 64 KiB 或距上次 flush ≥ 2 秒 → flush
  flush(run_id)  → 一列 run_logs + 更新 task_runs.log_bytes
  flush 由：下一個 chunk 進來時檢查、run 結束時強制、以及 RunReaper 每輪掃一次逾時緩衝
```

三個後果要寫進 ADR 0030：

1. **Central 崩潰會掉最後 ≤64 KiB 的 log。** **2026-08-11 裁決：接受。**
   理由是 log 是診斷（可重跑）而不是交付物；
   **產物走 HTTP 並逐件落地（D4）、訊息走 API 並逐筆 commit，兩者都不走這條路。**
   要寫進 ADR 0030 的 Consequences（`01-…md` §4），不是只寫在這裡的程式碼旁邊。
2. **截斷從中間發生，不是從尾巴。** 出口條件 14 要的是「明示截斷位元組數」，
   而一次 run 的開頭（環境、命令）與結尾（結果、錯誤）都比中間有用。
   實作：達到上限之後改成保留**最後 512 KiB 的環形緩衝**，flush 時在接縫處插入一列
   `truncated=true` 的標記列，內容是「已省略 N 位元組」。
   🆕 **環形緩衝以「行」為單位而不是位元組**（D21：內容是 JSONL 事件）——
   一個被切成兩半的事件在 UI 上渲染不出來，所以寧可少留一行也不留半行。
3. **`RunLogBuffer` 是行程內狀態**，Central 是單行程部署（既有的
   `NodeConnectionRegistry` 已經依賴這個前提）。要改多行程時，這兩個東西一起改，
   寫在 ADR 0029 的 Consequences。

## 8. 測試清單（本票）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | 兩個 node 的 poll 在同一個 tick 交錯 | 只有一列 `task_runs.runner_id` 非空；另一個拿到空 offer（50 次確定性併發，`08-…md` §2.1） |
| 2 | 指定 A 的卡，B 來 poll | **候選集合為空**（不是「B 領到但被拒」） |
| 3 | 兩張卡，第二張 `risk=high` | 先進先出。**沒有優先權**（§3.3 第 2 點） |
| 4 | 未指定的卡，兩個不同 Project | 同一個 runner 兩邊都領得到（**本期沒有綁定**，判準 1） |
| 5 | `runner.poll` 但 `agent_runners.enabled = false` | 候選集合為空 |
| 6 | `run.decline` | 回 `queued`、`attempt` 不變、同一 runner 60 秒內不再拿到它 |
| 7 | offer 的 spec | `source` 來自 run 上的**快照**；改卡片的 `repository_id` 不影響進行中的 run |
| 8 | 租約逾時 | `lost` → 新列 `seq+1`、`attempt+1` |
| 9 | 重排前改卡片的 `assigned_runner_id` | 新 run 仍指向原本的 runner（§6） |
| 10 | attempt 用完 | 不建新列、卡片 `blocked`、事件文案含或不含 runner 名稱（有無指定不同） |
| 11 | `waiting_for_input` 24h | `failed` ＋ `RUN_WAITING_TIMEOUT` ＋ 卡片 `blocked` |
| 12 | `waiting_for_input` 的 run 不佔 `max_concurrent` | 一個 runner `max_concurrent=1`，一個 run 在等回覆時仍能領第二張卡；但超過 `max_waiting` 就不再領 |
| 13 | log 超過上限 | `log_truncated_bytes > 0`、有一列 `truncated=true`、總量不超過上限 |
| 14 | log 全速輸出時 | 同 node 的終端 echo p95 不比 `AR-00` 的基線差 20% 以上（判準：出口條件 18） |
| 15 | dispatch：`source: repo` 但 Project 沒登記 repository | 409 `PROJECT_NO_REPOSITORY`，**訊息指向 Project Settings** |
| 16 | dispatch：`required_secrets` 非空 | 409 `TASK_REQUIRES_SECRETS`，訊息含「V2.3 起生效」 |
| 17 | dispatch：指定離線 runner vs 沒有可用 runner | 兩者都 202，**`waiting_reason` 不同、文案逐字不同** |
| 18 | `GATE-AR-NO-REQUEST-IN-LOOP` | `nodes.py`／`runs.py`／`runners.py` 裡沒有 `registry.request(` |
| 19 | `GATE-AR-SINGLE-CLAIM` | `SET runner_id = :runner_id` 在 `backend/app/` 只出現一次 |
| 20 | **`services/runs.py` 不 import `authorize_workspace`** | 文字掃描。裁決之後 run 與 workspace 授權**在程式碼上沒有交集**，而這條斷言讓它保持沒有交集（§3.2） |
