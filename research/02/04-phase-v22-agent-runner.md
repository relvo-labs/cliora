# V2.2 — Agent Runner 與任務認領（ticket 前綴 `AR-`）

## 目標

讓任務卡從「人在看板上推」變成「Agent 自己領走並執行」。

本階段**刻意不碰 git、不碰機密、不碰隔離目錄**——那些是 V2.3。這裡只證明一件事：工單掛得出去、被領得到、領走之後不會雙重領取、runner 死掉能重排、執行過程看得見。

先讓佇列與租約在**既有的 workspace 上**跑通（run 直接在 Project 綁定的 workspace 執行，等同一次無人值守的 Session），再在 V2.3 把工作目錄換成隔離的。這樣兩個高風險的東西不會在同一個階段同時上線。

## 前置條件

- V2.1 出口條件全數通過。
- D16、D17、D17b、D18、D24、D26、D27 已裁決。
- ADR 0028（Agent Runner 模型與 run 生命週期）、**ADR 0029（run 的輸出：log 與產物）** 已撰寫並接受。

## 工作包

### AR-01 — ADR 0028：Runner 模型

要寫清楚的五件事：

1. **Runner 是 `agentd` 的一個模式**（D16），重用既有的 enrollment、Ed25519 憑證、WSS、heartbeat。**不新增信任建立流程**——這是本 ADR 最重要的一句。
2. **拉取式認領**（D17）與其理由：平台不寫排程器，背壓天然。**指定 agent 是 poll 查詢的一個 `WHERE` 條件，不是推送**（D17b）——三個邊界（不繞過綁定授權、資格衝突在 dispatch 當下拒絕、預設不逾時退回）逐條寫進 Decision。
3. **租約語意**：續租週期、逾時判定、重排上限、用完進 `blocked`。
4. **Agent Run 不是 Session**：不進 `terminal_sessions`、不走 Terminal relay、不佔 writer 名額、沒有 tmux 持久化。兩條路徑在程式碼上分開。
5. **Alternatives rejected**：平台推送式派工（會長成排程引擎，且違反紅線 4 的「不自動指派」）、把 run 建成一種 Session（生命週期不同，會污染既有狀態機）、新做一支 runner binary（重複整條信任鏈）。

### AR-02 — ADR 0029：run 的兩種輸出（log 與產物）

一份 ADR 涵蓋兩者，因為它們是同一個問題的兩半：**run 產生的東西怎麼離開 node、存多久、誰清。**

**Part A — run log（D27）**：核心是那張「互動式 Session vs Agent Run」對照表，以及一句話：

> **這不構成「平台現在會存終端內容」的先例。** 互動式 Session 的承諾未變。

四條約束（有界、runner 端去識別、保留期、不是 Terminal relay）逐條寫進 Decision，各配一條測試。

**Part B — 卡片產物（D29）**：能力與宣告分開、存平台不存 node、三層配額、**提供時預設下載不渲染**、不可變、不保證不含機密。

**兩者的保留期不同，這是本 ADR 最重要的一句**：log 是**診斷**（保留期到期即刪），產物是**交付物**（跟著卡片走）。混為一談會讓卡片上出現死連結。

### AR-03 — Contract：runner 與 run 訊息（contract v1.10.0）

```text
runner.register    { runner_id, runtime, labels[], max_concurrent }
runner.registered  { accepted, reason? }
runner.poll        { runner_id, capacity }
run.offer          { run_id, task_id, project_id, spec }
run.accept         { run_id }
run.decline        { run_id, reason }
run.lease_renew    { run_id }
run.progress       { run_id, phase, message }
run.log_chunk      { run_id, seq, data, truncated }
run.complete       { run_id, result, summary }
run.failed         { run_id, error_code, message }
run.cancel         { run_id, reason }        ← 平台 → runner
```

`spec` 在本階段只含：runtime、workspace（V2.3 換成 source 定義）、情境包內容、允許的驗證指令清單、逾時。**不含機密**（V2.3 才有）。

fixtures：每個訊息 valid ＋ invalid（缺 `run_id`、未知 phase、`log_chunk` 超過大小、`capacity` 為負、非 UTC 時間、未知型別）。

### AR-04 — Daemon：runner 模式（`agentd` 0.8.0）

- `agentd serve --runner` 或設定檔開關；一個 node 可跑多個 runner（不同 runtime）。
- 容量控管：`max_concurrent`，滿了就不 poll。
- **執行 CLI 的方式**：非互動模式，argv 仍由既有的 `runtime` 套件組出（**SEC-002 的 argv 部分完全不變**）。這裡不是新的執行面，是既有 `BuildCommand` 的另一種呼叫情境——但它不掛 PTY、不進 tmux。
- 輸出處理：擷取 stdout/stderr → 分塊 → 大小上限 → 送 `run.log_chunk`。
- **去識別的掛勾點先做好**（本階段沒有機密可去識別，但介面要在，否則 V2.3 會變成事後補綴）。
- 逾時：run 層級硬逾時，到期送 `run.failed` 並清理程序。
- 收到 `run.cancel` 要能真的停下來（送訊號、等待、強制終止三段）。

### AR-05 — Central：run 生命週期與佇列

migration `0026`：

- `agent_runners`：`id`、`node_id`、`name`、`runtime`、`labels` JSONB、`max_concurrent`、`status`、`last_seen_at`、`registered_at`、`disabled_at`。
- `project_agents`：`project_id`、`runner_id`、`enabled`。唯一鍵。
- `task_runs`：`id`、`task_id`、`project_id`、`runner_id`（nullable）、`seq`、`status`、`attempt`、`claimed_at`、`lease_expires_at`、`started_at`、`finished_at`、`result`、`error_code`、`summary`、`created_by`。
- `run_logs`：`run_id`、`seq`、`data`、`truncated`、`received_at`（或存物件儲存，見下）。
- `task_messages`：`task_id`、`run_id`（nullable）、`author_kind`、`author_id`、`body`、`created_at`。

**狀態機**：

```text
queued → claimed → running → succeeded
                          ↘ failed
                          ↘ waiting_for_input → running
   ↑                      ↘ cancelled
   └── lost（租約逾時）→ 重排（attempt+1，上限 3）→ blocked
```

**原子認領**：`UPDATE task_runs SET runner_id=?, claimed_at=now(), lease_expires_at=? WHERE id=? AND runner_id IS NULL`。回傳 0 列就是被別人領走了，平台把這個 offer 撤回。

**資格判定**（五個條件，D17／D17b）：

```sql
WHERE t.stage = 'ready'
  AND NOT EXISTS (未完成的 dependsOn)
  AND EXISTS (project_agents 綁定)               -- 授權，不可被指定覆蓋
  AND runner.runtime = t.runtime
  AND t.required_labels <@ runner.labels          -- 能力
  AND (t.assigned_runner_id IS NULL
       OR t.assigned_runner_id = :runner_id)      -- 指定（D17b）
```

**指定不能繞過綁定**：第三行永遠先成立。否則持有 `run.dispatch` 的 Developer 就能把任務指給任意 runner，等於繞過 Admin 才有的 `agent.manage`。**這一條要有測試。**

**重排維持指定**：被指定的 run 變 `lost` 之後仍只給原本那個 runner；attempt 用完進 `blocked`，原因寫明「指定的 Agent 連續 3 次未能完成」。

**run_logs 的儲存**：先進 PostgreSQL（簡單、可查、與 audit 同一套備份）；若 `09` §5 的 M10 量測顯示體積失控，再改物件儲存。**先量再改**，不要一開始就做 S3。

### AR-06 — 看板作為溝通管道（D24）

- 卡片上的訊息串：使用者留言、Agent 回覆、系統事件（領取、開始、完成、失敗）三種混排，來源可辨識。
- Agent 用 `cliora task say` 發言；用 `cliora task messages --since` 拉取。**不做中斷式推送**（理由見 D24）。
- Agent 提問 → `cliora task ask` → run 進 `waiting_for_input`，卡片顯示「等待你的回覆」，租約續租但不計執行逾時。
- `waiting_for_input` 逾時（預設 24h）自動結束 run，卡片退 `blocked` 並寫明原因。**否則會有 run 永遠掛著佔容量。**

### AR-06b — 任務卡產物（D29）

**能力與宣告分開**：任何 run 隨時都能附加產物；`delivery: artifact` 的宣告與 Done Gate 留到 V2.4。

- 新 protocol 訊息 `run.artifact`（metadata）＋ 分塊上傳（或走 HTTP 端點，二選一，ADR 決定）。**產物上傳到平台，不留在 node**——run 目錄有保留期，卡片是永久的（D29 §3）。
- `task_artifacts`：`task_id`、`run_id`、`message_id`(nullable)、`filename`、`content_type`、`size`、`sha256`、`storage_ref`、`uploaded_by`、`created_at`。**不可變**，無 update 端點。
- CLI：`cliora task attach <file> [--message "說明"]`，也可 `cliora task say --attach`。
- 三層配額：單件 10 MB、單 run 件數上限、**專案總配額**（用盡時 runner 收到明確錯誤並顯示在卡片上，不是靜默失敗）。
- **提供時的安全規則（D29 §4，本工作包最容易做錯的地方）**：
  - 預設 `Content-Disposition: attachment` ＋ `X-Content-Type-Options: nosniff`，**一律下載不內嵌**。
  - 只有圖片／純文字／markdown 可內嵌預覽，走既有的預覽限制（ADR 0015 同一套）。
  - **HTML 產物不得在應用 origin 內渲染**（Cliora 是單一 origin 部署，ADR 0020）。
  - 存取控制繼承 Project（`project.view`），無公開連結、無可猜 URL。
- **不保證產物不含機密**：runner 端去識別只對 log 的文字串流有效。誠實寫進 ADR 與 UI 文案，不要暗示產物是安全的。

### AR-07 — RBAC 與 API

新增動作：`agent.view`、`agent.manage`（註冊、停用、綁定 Project）、`run.dispatch`（把一張卡掛上佇列）、`run.cancel`。角色歸屬見 `07` §5。

```text
GET    /api/agents                          agent.view
POST   /api/agents/{id}/projects             agent.manage   綁定
DELETE /api/agents/{id}/projects/{pid}       agent.manage
PATCH  /api/agents/{id}                      agent.manage   停用／並行度
POST   /api/tasks/{id}/dispatch              run.dispatch   掛上佇列
GET    /api/tasks/{id}/runs                  project.view
GET    /api/runs/{id}                        project.view
GET    /api/runs/{id}/logs                   project.view   分頁／串流
POST   /api/runs/{id}/cancel                 run.cancel
POST   /api/tasks/{id}/messages              project.view   留言（可帶 artifact_ids）
POST   /api/tasks/{id}/artifacts             （run 憑證或 project.view）上傳產物
GET    /api/artifacts/{id}                   project.view   下載（attachment，不內嵌）
DELETE /api/artifacts/{id}                   project.manage 僅配額用盡時，需理由 ＋ audit
```

`POST /dispatch` 接受 optional `assigned_runner_id`（不給＝任一符合資格者，這是預設）。

**兩種失敗要分得出來**（D17b 邊界 2）：

| 情況 | 回應 | 卡片顯示 |
|---|---|---|
| 指定的 runner **不符資格**（沒綁 Project／runtime 不符／labels 缺／已停用） | `409` ＋ 指名是哪一個條件 | 不入佇列，dispatch 當下就擋下 |
| 指定的 runner **暫時離線或忙碌** | `202` 正常入佇列 | 「等待指定的 Agent：dev-vm-01（目前離線）」 |

分不出這兩種，使用者就分不出「我設定錯了」跟「再等一下就好」。

### AR-08 — 前端

- **Agents 頁**（Infrastructure 群組下）：runner 清單、所在 node、runtime、labels、並行度、目前負載、綁定的 Project、啟用開關。
- **卡片上的「派給 Agent」**：預設「任一符合資格的 Agent」；可改為指定某一個。picker 列出該 Project 綁定的 runner 與其目前負載，**不符資格的顯示為停用並附原因**（不是隱藏——隱藏會讓人以為那台機器不存在）。
- **看板卡片顯示 run 狀態**：排隊中／執行中（哪個 agent）／等待回覆／失敗。
- **Run 詳情頁**：狀態、時間軸、log 串流（可跟隨、可搜尋、明示截斷）、取消按鈕。
- **卡片訊息串**：這是「平台作為橋樑」最直接的體現，要做得好用——輸入框固定在下方、Agent 的問題要醒目、系統事件用低調樣式。
- **產物區**：卡片上獨立一區列出所有產物（檔名、大小、來自哪次 run、時間）；訊息裡的附件同時出現在訊息與產物區。圖片顯示縮圖，其餘一律下載按鈕。**不做「在新分頁開啟」**（那等同內嵌渲染）。

## 這一階段明確不做

- 不碰 git（V2.3）。
- 不碰機密／環境變數（V2.3）。
- 不做隔離工作目錄——run 直接在 Project 綁定的 workspace 執行（V2.3 才換）。
- 不做 PR／MR（V2.4）。
- 不做自動指派、排程最佳化、負載平衡（`00` §9）。
- 不做「把 run 升級成互動 Session」（D26）。

## 出口條件

1. 一個 runner 綁兩個 Project，兩邊的卡片都能被它領走；沒綁的第三個 Project 的卡片**永遠不會被 offer**。
2. **未指定** agent 的卡片：任一符合資格的 runner 都領得到。
3. **指定** agent 的卡片：只有那一個 runner 領得到，其他符合資格的 runner **永遠不會被 offer 它**。
4. 指定一個**沒綁該 Project** 的 runner → dispatch **回 409 不入佇列**，訊息指名是綁定這一條（指定不繞過授權）。
5. 指定的 runner **離線** → 正常入佇列，卡片顯示「等待指定的 Agent（目前離線）」；上線後被它領走。**文案與「沒有可用的 Agent」不同。**
6. 兩個 runner 同時 poll 同一張卡 → **只有一個領到**，另一個收到撤回；`task_runs` 沒有兩列。
7. 執行中 kill 掉 runner 程序 → 租約逾時後標 `lost`、重排、被領走並完成；**被指定的卡重排時仍只給原本那個 runner**。
8. 重排三次都失敗 → 卡片進 `blocked`，原因寫明，不無限重試。
9. `run.cancel` → runner 真的停下來，程序不殘留（用 `ps` 驗證）。
10. Run log 超過上限 → 從中間截斷、明示截斷位元組數，不是靜默丟棄。
11. Agent `cliora task ask` → 卡片顯示等待回覆；使用者回覆後 Agent 拉得到；24h 未回覆自動退 `blocked`。
12. **互動式 Session 完全不受影響**：run 進行中同時開一個 Session，兩者互不干擾；`terminal_sessions` 沒有多出 run 的列。
13. Agent 在執行中 `cliora task attach report.md --message "初步發現"` → 訊息與產物同時出現在卡片；**run 目錄被清掉後產物仍可下載**。
14. 上傳一個 `.html` 產物 → 下載時帶 `Content-Disposition: attachment` 與 `nosniff`；**應用 origin 內沒有任何路徑會渲染它**。
15. 專案產物配額用盡 → runner 收到明確錯誤並顯示在卡片，**不是靜默失敗**。
16. 已附加的產物**沒有任何 API 可以修改**；刪除只有 `project.manage` 且需理由，寫 audit。
17. 旗標關閉：完整 V1 回歸全綠。

## 風險

| 風險 | 對策 |
|---|---|
| 雙重領取 | 原子 `UPDATE ... WHERE runner_id IS NULL`；出口條件 6 |
| runner 死掉任務永遠卡住 | 租約 ＋ 逾時重排 ＋ 上限；出口條件 7、8 |
| **指定的 agent 永遠不上線，卡片無聲卡住** | 卡片顯示「等待指定的 Agent（離線）」而非「排隊中」；D17b 刻意不做自動退回（在錯的機器上執行比多等更糟），需要時再做成卡片上的 opt-in 欄位 |
| 指定成為授權旁路 | 綁定檢查永遠先成立 ＋ 出口條件 4 |
| run log 撐爆資料庫 | 單 run 上限 ＋ 保留期 ＋ `10` §5 的 M10 量測，必要時改物件儲存 |
| **產物成為 stored XSS 管道** | 預設下載不渲染 ＋ `nosniff` ＋ 白名單預覽 ＋ HTML 絕不在應用 origin 渲染（出口條件 14）。**這是本階段最容易做錯的一項** |
| 產物撐爆磁碟 | 三層配額（單件／單 run／專案）；用盡時明確報錯（出口條件 15） |
| 產物隨 run 目錄被清掉 | 上傳到平台儲存，與 run 保留期無關（出口條件 13） |
| 產物含機密 | 無法保證，誠實寫進 ADR 與 UI；保障來自存取控制與機密可撤銷 |
| `waiting_for_input` 佔容量 | 24h 逾時自動結束（出口條件 11） |
| run 與 Session 的狀態機混在一起 | `task_runs` 是獨立的表與獨立的狀態機；出口條件 12 用 `terminal_sessions` 的列數驗證 |
| 無人值守執行在使用者的 workspace 上造成非預期變更 | **本階段的已知缺口**：V2.3 才隔離。所以 V2.2 建議只在測試專案啟用，並在 UI 明示「此 run 直接在 workspace 執行」 |
