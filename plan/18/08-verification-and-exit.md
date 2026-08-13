# 08 — `AR-12`：驗證、出口條件與合併關卡

> **2026-08-10 裁決改寫了 §5 的出口條件（17 → 23）與 §6 的安全審查（四節 → 五節）。**
> 新增的都與「Agent 自己拉專案到隔離目錄」有關；移除的三條是綁定與 labels 的
> （它們移到 V2.3 的出口條件，`research/02/10` §2.5）。

## 1. 共通完成定義（每張 ticket）

沿用 `research/02/10` §1，本期不放寬任何一條：

- 新 API 在 boundary 完成 authentication、resource-level authorization 與 validation；
  錯誤回穩定 machine code、安全訊息與 `request_id`。
- 新 protocol 訊息先進 `contracts/v1/schemas/` 與 fixtures（含 invalid），再寫兩邊實作。
- 新 RBAC 動作在**同一張 ticket** 內接上強制點；`UNENFORCED_ACTIONS` 保持空集合。
- 所有時間 aware，傳輸 RFC 3339 UTC。
- 每個平台側寫入動作寫一筆 audit；**Agent 的動作 actor 標示為 runner，不冒充人類**。
- 每一種新儲存都回答 ADR 0024 W2：**誰清這個、什麼時候清**（本期三個不同的答案，
  `01-…md` §4）。

## 2. 測試矩陣

| 層 | 範圍 | 位置 |
|---|---|---|
| 契約 | 12 valid ＋ 17 invalid，三個語言都跑；既有 fixture 逐檔未變（以 `AR-00` 的清單為準，開工當下是 109 個檔） | `contracts/v1/fixtures/`、`make contract` |
| DB | 八張表的上下行、狀態機、原子認領的併發、產物配額、repository 欄位驗證 | `backend/tests/db/` |
| API | 十七條端點 × 三角色 × 兩種憑證 × 兩個旗標 | `backend/tests/api/` |
| daemon 單元 | `BuildRunCommand` 的 argv、三段終止、分塊器（**不切斷 JSON 行**）、`RunCapable` 探測（**含流式旗標**）、**三個計時器各自的判定**、**git argv 封閉表、URL 驗證、啟動自檢** | `daemon/internal/{runtime,gitfetch,connection}` |
| daemon 整合 | **真實 repo 的 mirror ＋ worktree ＋ 移除 origin**、配額、保留期清理 | `daemon/internal/gitfetch`（`-tags integration`） |
| CLI | 四個子命令、離線兩句訊息逐字、三個配額錯誤的人話 | `daemon/internal/cli` |
| 前端單元 | Agents 頁、訊息串、產物區（含 `v-html`／`target="_blank"` 的否定斷言） | `frontend/src/**/*.test.ts` |
| e2e（live stack） | 認領→**clone**→執行→完成、kill→重排、cancel→無殘留、ask→回覆、attach→下載、**workspace `git status` 全程為空** | `scripts/e2e/` |
| 效能 | run log 全速時的終端 echo 延遲 vs `AR-00` 基線 | `scripts/ar/measure_*.py` |

### 2.1 併發測試怎麼寫

出口條件 5 要的是「兩個 runner 在同一個 tick 對同一張卡 poll」。
不能靠 sleep 湊，要用一個確定性的做法：

```text
1. 建一張 queued 的 run；兩個 node 各自有一個 enabled 的 runner，runtime 相符
   （本期沒有綁定，所以「兩個 runner 都有資格」是預設狀態，不必先設定什麼）
2. 用 asyncio.gather 同時呼叫 RunService.poll(nodeA) 與 RunService.poll(nodeB)
   （兩個各自的 AsyncSession，模擬兩條 WS 連線）
3. 斷言：恰好一個回傳非空 offer；task_runs 只有一列 runner_id 非空
4. 重複 50 次（不同的 gather 順序），全部通過
```

**兩個各自的 session 是重點**——用同一個 session 跑兩次不會經過真正的
交易隔離，那條 `WHERE runner_id IS NULL` 就沒被測到。

## 3. 六個 gate

| Gate | 斷言 | 沿用／新做 |
|---|---|---|
| `GATE-AR-SCHEMA-ADDITIVE` | `0028 → head` 的 schema diff 只有新增 | 沿用 `scripts/pj/gate-schema-additive.sh` |
| `GATE-AR-MIGRATION-ROUNDTRIP` | upgrade → downgrade → 與 `AR-00` 基線逐位元組相同 | 沿用 `scripts/tk/gate-migration-roundtrip.sh` |
| `GATE-AR-CONTRACT-ADDITIVE` | 既有 fixture 逐檔未變（`AR-00` 的清單）；`manifest.json` 具名豁免並列印 | 沿用 `scripts/tk/gate-contract-additive.sh` |
| `GATE-AR-TOUCH-LIST` | 節點側與平台側的允許／禁區清單（`04-…md` §7、`00-…md` D16） | **新做**（禁區與 V2.1 不同，且比它更嚴：`files/`、`workspace/`、`go.mod` 都進禁區） |
| `GATE-AR-FLAG-OFF` | 兩個旗標各自關閉時的 404 集合與 OpenAPI 一致 | 沿用 `scripts/tk/gate-flag-off.sh` 並擴充第二個旗標 |
| 🆕 `GATE-AR-NO-GIT-DEP` | `daemon/go.mod` 與 `go.sum` 零 diff | **新做**。git 走執行檔不走 library（`04b-…md` §5.1），而這是那個決定唯一可機器判定的形式 |

### 3.1 本期新增的六條掃描式斷言

它們不是傳統意義的 gate（沒有基線檔），但同樣是 `make check` 的一部分：

| 名稱 | 掃什麼 | 為什麼 |
|---|---|---|
| `GATE-AR-NO-REQUEST-IN-LOOP` | `api/ws/nodes.py`、`services/runs.py`、`services/runners.py` 不得出現 `registry.request(` | 那是 `00-…md` D1 的死鎖，而它的症狀（逾時）看起來像網路問題 |
| `GATE-AR-SINGLE-CLAIM` | `SET runner_id = :runner_id` 在 `backend/app/` 只出現一次 | 「雙重領取不可能」的唯一保證是那一條 UPDATE；第二個寫入點會靜默廢掉它 |
| `GATE-AR-DISPATCH-COVERAGE` | contract 裡每個 node→central 的 `runner.*`／`run.*` 型別，都在 `nodes.py` 的 `elif` 鏈裡出現 | 漏一個的症狀是「訊息不見了但沒有錯誤」（`03-…md` §1） |
| `GATE-AR-NO-HTML-SINK` | 新增的前端檔案不得出現 `v-html`／`target="_blank"`／`<iframe`；OpenAPI 沒有任何回應宣告 `text/html` | `00-…md` D14 的機器形式（判準 14） |
| 🆕 `GATE-AR-NO-WORKSPACE-IN-RUNS` | `backend/app/services/runs.py`／`runners.py` 不得出現 `authorize_workspace`／`project_workspaces`／`ProjectWorkspace`；`daemon/internal/connection/runner_handlers.go` 不得 import `internal/workspace` 或 `internal/files` | **裁決的機器形式**：run 與使用者的 workspace 授權**在程式碼上沒有交集**，而這條斷言讓它保持沒有交集（`03-…md` §3.2、`04-…md` §7） |
| 🆕 `GATE-AR-NO-REPO-URL-FIELD` | OpenAPI 的 `repositories` request schema 沒有 `url` 欄位 | 「不可表示勝過過濾」（`06-…md` §2.3） |

## 4. 旗標關閉回歸

**兩個旗標，三種組合**（`research/02/10` §3 的套組在本期要跑三次）：

| 組合 | 期望 |
|---|---|
| `PROJECTS=false`, `RUNS=false` | 完整 V1 回歸全綠；導覽五項；OpenAPI 與 V1 基線一致 |
| `PROJECTS=true`, `RUNS=false` | 完整 V1＋V2.0＋V2.1 回歸全綠；導覽六項；本期端點全 404；`runner.register` 被拒 |
| `PROJECTS=true`, `RUNS=true` | 本期功能全綠 |

**第二種組合是本期最重要的一種**：它是「組織想要看板但不想要無人值守執行」
的部署姿態（`research/02/08` §8 兩個旗標的理由），而它必須是一個**真的被測過**的狀態，
不是一個理論上的組合。

`agentd` 0.9.0 在 `RUNS=false` 的部署上行為與 0.8.0 相同：
`runner.register` 被拒之後**不重試、不影響其他功能**、log 一行說明。

## 5. 出口條件（23 條）

上游 `research/02/04` §出口條件的 23 條逐條對應（2026-08-10 裁決改寫）。
🆕 標示的是裁決新增的，~~刪除線~~ 標示的是移到 V2.3 的。

| # | 條件 | 怎麼證 |
|---|---|---|
| 1 | **未指定** agent 的卡：任一 runner 都領得到 | 兩個 runner 輪流領到（本期沒有綁定，「任一」就是字面意思） |
| 2 | **指定** agent 的卡：只有那一個領得到 | 另一個 runner 的**候選集合為空**（不是「領到但被拒」） |
| 3 | 指定**已停用**或**runtime 不符**的 runner → 409 不入佇列 | 狀態碼 ＋ **訊息指名是哪一條** ＋ `task_runs` 沒有新列 |
| 4 | 指定的 runner **離線** → 入佇列，文案與「沒有可用的 Agent」**不同** | 兩條測試各斷言一句字串 |
| 5 | 兩個 runner 同時 poll → 只有一個領到 | §2.1 的 50 次確定性併發測試 |
| 6 | 🆕 **`source: repo` → run 目錄裡出現 clone**，`commit_sha` 回報並顯示 | live-stack；**第二次 run 走 mirror**（比對耗時與 mirror mtime） |
| 7 | 🆕 **run 目錄不在任何 allowed root 內** | `filesystem.list` 回 `WORKSPACE_OUTSIDE_ALLOWED_ROOT`；**daemon 在 run root 落在 allowed root 內時拒絕啟動並指名**（正反兩向都測） |
| 8 | 🆕 **平台的任何路徑都沒有碰使用者的 workspace** | run 進行中與結束後，對該 Project 每一個綁定 workspace 做 `git status --porcelain` **完全為空** ＋ `GATE-AR-TOUCH-LIST`（`files/`、`workspace/` 零 diff）。⚠️ **原本這一條寫「Agent Run 讀寫不到使用者的 workspace」，那是一句平台沒有實作的保證**——已改（`04b-…md` §3.4） |
| 8b | 🆕 **混合用途的 node 是看得見的** | `allowed_roots: []` → `runner.register` 回報 `dedicated: true`，Agents 頁顯示「專用 runner」；非空 → `dedicated: false` ＋ **⚠ 混合用途（Agent 可讀取那些目錄）**，`agentd doctor` 印同一行（`04b-…md` §3.5） |
| 9 | 🆕 **run 摘要記錄得出這個 run 有沒有動到遠端** | `git remote -v`（**userinfo 已遮**）與 `git log --oneline --branches --not --remotes` 的行數都在 `run.complete` 與 Run 詳情頁上；另有一條測試斷言 **Agent 在 run 目錄裡 `git push` 到 scratch 遠端會成功**（不是被擋）——那條測試的存在本身就是裁決的記錄 |
| 10 | 🆕 缺 git 憑證時 clone **秒級失敗** | `run.failed` 的時間戳與 `queued_at` 相差 < 30 秒（**不是 6 小時**）。idle timer 救不了這一種：clone 在 `run.accept` 之前，還沒有事件流 |
| 11 | kill runner → 租約逾時、重排、完成；**指定的卡重排仍只給原本那個** | e2e ＋ `03-…md` §6 的「重排前改卡片」測試 |
| 12 | 重排三次都失敗 → 卡片 `blocked`，原因寫明，不無限重試 | `task_runs` 停在 3 列；事件文案含或不含 runner 名稱 |
| 13 | `run.cancel` → **process group 下無殘留** | 掃 `/proc/*/stat` 第 5 欄（不是 `ps` 目視） |
| 14 | Run log 超過上限 → **從中間截斷、明示位元組數** | `log_truncated_bytes > 0`；有一列 `truncated=true`；總量不超過上限；🆕 **截斷不切斷一行 JSON**（每一列 `data` 的每一行都能 `json.loads`） |
| 14b | 🆕 **一個「還在跑但很慢」的 run 不會被誤殺** | fakecli 變體每 60 秒吐一個事件、共 20 分鐘 → run **正常完成**（不是 `RUN_IDLE_TIMEOUT`、不是 `RUN_TIMEOUT`、不是 `lost`）。**這是 D21 的核心斷言** |
| 14c | 🆕 **一個真的掛住的 child 在 idle 上限內被收掉** | fakecli 變體吐三個事件之後睡 10 分鐘 → `run.failed{RUN_IDLE_TIMEOUT}` 在 `idle_timeout_seconds` 之後（**不是等 6 小時牆鐘**） |
| 14d | 🆕 **runner 掛了與 child 掛了是兩種不同的結果** | kill runner 程序 → `lost` → 重排（條件 11）；child 掛住 → `RUN_IDLE_TIMEOUT` → **不重排**。兩者的 `task_runs` 列與卡片狀態各不相同 |
| 15 | `cliora task ask` → 等待回覆 → 回覆後拉得到；24h 自動退 `blocked` | e2e ＋ `RunReaper` 的時鐘注入測試 |
| 16 | **互動式 Session 完全不受影響** | run 進行中開 Session，兩者互不干擾；**`terminal_sessions` 的列數在整段 run 期間不變**；`GATE-AR-TOUCH-LIST` ＋ `GATE-AR-NO-WORKSPACE-IN-RUNS` |
| 17 | `cliora task attach` → 訊息與產物同時出現；**run 目錄清掉後仍可下載** | e2e：跑完 → 觸發保留期清理 → 目錄不見了、`run_logs` 為空 → 產物下載仍 200 |
| 18 | 🆕 **`delivery: none` 的卡有變更 → `git diff` 附成產物** | 產物存在、`content_type = text/plain`、摘要含檔案數；**未追蹤檔案只計數不打包**（`04b-…md` §6） |
| 19 | `.html` 產物下載帶 `attachment` ＋ `nosniff`；**應用 origin 內沒有路徑會渲染它** | 四個標頭 ＋ `GATE-AR-NO-HTML-SINK` 的兩條機器斷言 |
| 20 | 專案產物配額用盡 → runner 收到明確錯誤並顯示在卡片 | 413 ＋ `details` ＋ CLI 的那句人話 ＋ 卡片上的錯誤列 |
| 21 | 🆕 **run 目錄配額用盡 → 停止領取新工作並回報原因** | Agents 頁顯示「磁碟用盡（4.8 / 5.0 GB）」**而非「離線」**（三種狀態三種文案，`07-…md` §2） |
| 22 | 產物**沒有任何 API 可以修改**；刪除只有 `project.manage` 且需理由 ＋ audit | OpenAPI 斷言 ＋ 三條 API 測試 |
| 23 | **雙旗標關閉：完整 V1＋V2.0＋V2.1 回歸全綠** | §4 的三種組合 ＋ 既有 fixtures 零變更 ＋ 三角色導覽逐像素一致 |
| ~~—~~ | ~~runner 綁兩個 Project／沒綁的第三個永不 offer~~ | **移到 V2.3**（`research/02/10` §2.5 條件 6）。裁決：本期每個 agent 都可以拉每個 project |
| ~~—~~ | ~~指定沒綁該 Project 的 runner → 409（指定不繞過授權）~~ | **移到 V2.3**。規則不變，本期沒有可以被繞過的授權 |
| ~~—~~ | ~~缺少 label 的 runner 不被 offer~~ | **移到後續**。欄位在，不比對 |

**額外一條（本計畫加的，不在上游清單上）**：

| # | 條件 | 怎麼證 |
|---|---|---|
| 24 | run log 全速輸出時，**同一個 node 上互動終端的 echo 延遲 p95 不比 `AR-00` 基線差 20% 以上** | `scripts/ar/measure_terminal_latency.py`，對照 `artifacts/ar/local/baseline/terminal-latency.json` |

它是條件 16（互動式 Session 完全不受影響）在**效能面**的形式。
條件 16 現在的證法（`terminal_sessions` 列數 ＋ 兩條 gate）只證了**功能面**
——一條變頓的終端也是「受影響」。

## 6. 安全審查

`docs/security-review-v22.md`，**五節**（`00-…md` D15）：

| 節 | 主題 | 對應票 | 完成時點 |
|---|---|---|---|
| 1 | 認領授權與「指定」——**邊界是 enrollment**，以及「程式碼落在哪台機器」的變化 | `AR-05` | `AR-05` 合併前 |
| 2 | run 憑證的發行、範圍與失效 | `AR-08` | `AR-08` 合併前（大綱見 `05-…md` §3） |
| 3 | log 邊界、去識別掛勾、保留期 | `AR-07` | `AR-07` 合併前 |
| 4 | **產物的接收與提供路徑（stored XSS、配額、不可變）** | `AR-09` | **`AR-09` 合併前**（閘門四） |
| 5 | 🆕 **run 目錄隔離、配額與 git 取得** | `AR-07b` | `AR-07b` 合併前 |

五節**各自獨立**，不合寫成一段「Agent 執行環境安全審查」——
它們的邊界測試是五組不同的東西（沿用 `research/02/10` §6 對 V2.3 的同一條要求）。

**第 1 節本期要回答的問題變了。** 原本是「指定能不能繞過綁定」；
裁決之後沒有綁定，所以它要回答的是一個**姿態問題**：

> 本期任何 enroll 過的 node 上的 runner 都能領任何專案的卡片、拉任何專案的程式碼。
> 授權邊界是 `enrollment.manage`（Admin）。**接受這個姿態的部署前提是什麼？**

**先寫清楚什麼「不是」新的**：人本來就看得到所有專案
（`api/http/projects.py:109` 的 docstring ＋ ADR 0027 Consequences：
「two teams sharing one Cliora see each other's project names — a real disclosure,
accepted deliberately」），也本來就能在任何 node 的 allowed root 上開 Session 讀程式碼。

**真正變的一件事**：以前 `project_workspaces` 是 Admin 刻意建立的
「這個專案的程式碼住在這幾台機器」紀錄，現在 runner 繞過它——
一個專案的原始碼可以落在任何一台有 runner 的 node 上，而沒有人決定過那件事。

**再加上第二次裁決（憑證不必唯讀）的組合效果**：一張卡的 blast radius 是
「它落在哪台機器能碰到什麼」。所以要寫下來的部署前提是
**runner node 應該是專用的，不與需要不同信任等級的東西共用**——
而 ADR 0023 的「node 是可拋棄的隔離 VM」已經是這個方向，本節只是把它說到底。

**第 4 節要回答的核心問題只有一個**：
**一個 Agent 產生的檔案，有沒有任何路徑能讓它在 `https://<cliora-host>/` 這個 origin 下被執行？**
答案要是「沒有，而且這裡是三條證明它的機器斷言」。

**第 5 節要回答的核心問題有兩個**：

1. **run 目錄與使用者的 allowed root 有沒有任何一條互通的路徑？**
   ⚠️ **這一節最重要的一句是把問題問對。** 正確的答案不是「沒有」，而是分成兩半：
   **平台的路徑沒有**（條件 7、8、8b ＋ `GATE-AR-NO-WORKSPACE-IN-RUNS`）；
   **Agent 的程序有**——它與 agentd 同一個 OS 使用者，而 allowed roots 必須被那個使用者讀寫
   （`04b-…md` §3.4）。第二半由部署姿態承擔，而平台的貢獻是**回報**（`dedicated` 旗標）
   而不是強制。**這一節不得寫成「run 目錄是隔離的所以讀不到」**——那是本期最容易寫出來的一句假話。
2. **一個 Agent 用機器的 git 憑證能做什麼，而平台看得到什麼？**
   **答案是「git 能做的任何事，包含 push——這是刻意給的」**（2026-08-10 第二次裁決）。
   這一節要寫的不是處置清單而是三件事：
   ① 收斂點是紅線 5 的原則（沒有人 merge 的分支不影響任何人）與 node 的部署姿態；
   ② 平台提供的是**可觀測性**（run 摘要的兩行），不是阻止；
   ③ **紅線 4 第 1、2 條的措辭要改**，因為它們約束的是平台的 push 路徑而不是 Agent
   （`04b-…md` §5.5）。**不得寫成「我們擋不住，抱歉」**——那個框架已經被撤回。

## 7. `scripts/ar/evidence.sh`

沿用 `scripts/tk/evidence.sh` 的形狀，一次跑完所有非瀏覽器的本機 gate：

```bash
run "GATE-AR-SCHEMA-ADDITIVE"      bash scripts/pj/gate-schema-additive.sh artifacts/ar/local/baseline/schema.txt
run "GATE-AR-MIGRATION-ROUNDTRIP"  bash scripts/ar/gate-migration-roundtrip.sh artifacts/ar/local/baseline/schema.txt
run "GATE-AR-CONTRACT-ADDITIVE"    bash scripts/ar/gate-contract-additive.sh
run "GATE-AR-TOUCH-LIST"           bash scripts/ar/gate-touch-list.sh
run "GATE-AR-FLAG-OFF"             bash scripts/ar/gate-flag-off.sh
run "GATE-AR-NO-REQUEST-IN-LOOP"   bash scripts/ar/gate-no-request-in-loop.sh
run "GATE-AR-SINGLE-CLAIM"         bash scripts/ar/gate-single-claim.sh
run "GATE-AR-DISPATCH-COVERAGE"    python3 scripts/ar/gate_dispatch_coverage.py
run "GATE-AR-NO-HTML-SINK"         bash scripts/ar/gate-no-html-sink.sh
run "GATE-AR-NO-GIT-DEP"           bash scripts/ar/gate-no-git-dep.sh
run "GATE-AR-NO-WORKSPACE-IN-RUNS" bash scripts/ar/gate-no-workspace-in-runs.sh
run "GATE-AR-NO-REPO-URL-FIELD"    python3 scripts/ar/gate_no_repo_url_field.py
run "make check"                   make check
run "make test-db"                 make test-db
run "make integration"             make integration
run "daemon: runner + git + cli"   bash -c 'cd daemon && go test ./internal/runtime ./internal/gitfetch ./internal/connection ./internal/cli ./internal/protocol'
run "M-AR-2 (log rate)"            python3 scripts/ar/measure_log_rate.py --out artifacts/ar/local/m-ar-2.json
run "M11 (clone + worktree)"       python3 scripts/ar/measure_clone.py --out artifacts/ar/local/m11.json
run "M12 (run dir size)"           python3 scripts/ar/measure_run_dir.py --out artifacts/ar/local/m12.json
run "cond 24 (terminal latency)"   python3 scripts/ar/measure_terminal_latency.py --baseline artifacts/ar/local/baseline/terminal-latency.json
run "traceability"                 make traceability
```

**環境事實提醒**（`plan/17/09` §5，最容易漏的一件事）：
DB 測試要**兩個**環境變數（`CLIORA_TEST_DATABASE_URL` ＋ `CLIORA_DATABASE_URL`），
少了後者，authz 拒絕的稽核 middleware 會連到不存在的 `cliora` 資料庫，
症狀是三條 audit 測試無故失敗。

## 8. Release note 與文件

- `docs/release-note-agent-runner.md`：沿用既有 release note 的形狀。
  **要有一段「這一版不做什麼」**：不 push、不建分支、不開 PR、不碰機密、
  不做逐專案授權、不比對 labels。
  以及一段**已知取捨**（不是缺口——兩者的差別要在文案上看得出來）：
  ① 任何 runner 都能拉任何專案的程式碼，授權邊界是 enrollment（V2.3 收斂）；
  ② **Agent 在沙箱裡可以用機器的 git 憑證做任何事，包含 push——這是刻意給的**，
  平台提供的是可觀測性而不是阻止；
  ③ Central 崩潰會掉最後一段 log（**已裁決接受**，理由與不對稱寫進 ADR 0030 的
  Consequences：log 可重跑，而產物走 HTTP 逐件落地、訊息走 API 逐筆 commit）；
  ④ 產物配額先檢查後寫入（併發下不精確）；
  ⑤ 🆕 **無人值守的 token 花費沒有上限**（2026-08-11 裁決：本期只量不做，
  因為 `--max-budget-usd` 只有 claude 有，接一半比不接更危險）。
- 🆕 `docs/runbooks/` 要多一篇：**「一台 runner node 該怎麼準備」**
  ——`git` 要裝、`StateDirectory` 的磁碟要夠、**git 憑證建議唯讀或不設**。
  **第三條不再是「憑證要唯讀」**（第二次裁決撤回了那條建議），改成
  **「這台機器能碰到什麼，Agent 就能碰到什麼——所以 runner node 要專用」**
  （`04b-…md` §5.4）。
- `docs/runbooks/`：新增一篇「把一台 node 變成 Agent Runner」，
  一篇「一個 run 卡住了怎麼辦」（租約、cancel、blocked 的三種收斂路徑），
  以及一篇「run 目錄把磁碟吃滿了怎麼辦」（配額、保留期、mirror 的手動清理）。
- `docs/permission-matrix.md`、`docs/error-catalog.md`：重新產生。
- `docs/adr/0029-…md`、`0030-…md`、**`0031-…md`**：`AR-01`／`AR-02`／`AR-02b` 已完成，
  `AR-12` 只確認 Status 從 `Proposed` 翻 `Accepted`。
  **`0031` 的 Status 要寫明「本版只涵蓋取得半邊，V2.3 增補送回半邊」**
  ——一份會被 amend 的 ADR 要在第一版就說它會被 amend。
- `traceability/requirements.json`：八筆 FR-AGENT 從 `proposed` 翻 `active`。

## 9. 合併回 `dev`

**一律由人工確認。**（`research/02/10` §7）

出口條件全綠只是**取得提案資格**，不是核准。自動化（含 CI 與 agent）
不得發起或完成這個合併。`AR-12` 的最後一步是**寫出提案並停下來**：

```text
提案內容：
  - 24 條出口條件的狀態表（含證據位置）
  - 六個 gate ＋ 六條掃描式斷言的輸出
  - docs/security-review-v22.md **五節**的結論
  - 已知取捨清單：**任何 runner 能拉任何專案的程式碼**（授權邊界是 enrollment）、
    **Agent 在沙箱裡的 git 自由（含 push）是刻意給的，收斂點是可觀測性**、
    Central 崩潰會掉最後一段 log（**已裁決接受**）、產物配額先檢查後寫入、
    **token 花費無上限**（2026-08-11 裁決：只量不做）
  - **紅線 4 第 1、2 條的措辭修訂**（`04b-…md` §5.5）——這是本期唯一一處改紅線的地方
  - agentd 0.9.0 的發布時機（出口全綠不代表要推給所有 node；
    node_update 是既有的分批機制，本期不改也不自動觸發）
然後停下來。
```

`plan/16`／`plan/17` 的合併提案也仍待人工決定；本期**不改變那條規則**，
也不因為前一期尚未合併而繞過它。
