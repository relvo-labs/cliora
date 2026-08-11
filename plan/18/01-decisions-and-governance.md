# 01 — `AR-00`／`AR-01`／`AR-02`／`AR-02b`：基線、量測、需求變更與三份 ADR

> **2026-08-10 裁決加了第三份 ADR（0031，原屬 V2.3）、把 M11／M12 拉進本期的開工前量測，
> 並讓 M-AR-1 當天就量完了**（§2.1）。

## 1. `AR-00` — 基線擷取（閘門）

**動任何一行程式碼之前**，把「本期之前的樣子」存下來。改完就再也取不到，而本期有
**六份**這種東西——比 V2.1 多三份（前端路由表、終端延遲基線、`COMMIT`）。
前端路由表是因為判準 14 要斷言一個**否定命題**（「應用 origin 內沒有任何路徑會渲染產物」），
而否定命題只能對照清單來證；終端延遲基線見 §1 表格下方那段。

**基線點（2026-08-11 裁決）：`3c8760d`**
（`Merge pull request #24 from Lei-k/feat/v2-1-task-layer`，本期開工時的 `v2` HEAD）。

擷取時要把當下的 `git rev-parse HEAD` 一起寫進
`artifacts/ar/local/baseline/COMMIT`，**而且六份基線必須全部取自同一個 commit**
——取自三個不同狀態的基線，比沒有基線更糟：它會讓某一條 diff 斷言在半年後
變成一個沒有人知道該不該相信的紅燈。
若開工前 `v2` 又前進了，**以實際擷取當下的 HEAD 為準並更新這一行**，
不要沿用這個 hash。

輸出一律進 `artifacts/ar/local/baseline/`，沿用 `scripts/tk/capture-baseline.sh` 的形狀：

| 檔案 | 怎麼取 | 給誰用 |
|---|---|---|
| `openapi.json` | 兩個旗標都關閉時 dump 一次、都開啟時再 dump 一次（兩份） | 回歸判準的「旗標關閉逐位元組一致」；判準 14 的「沒有任何回應宣告 `text/html`」 |
| `schema.txt` | `pg_dump --schema-only` | `GATE-AR-SCHEMA-ADDITIVE`（沿用 `scripts/pj/gate-schema-additive.sh`） |
| `contract-fixtures.txt` | `scripts/tk/contract_snapshot.py` | `GATE-AR-CONTRACT-ADDITIVE`：**既有 fixture 逐檔未變**。開工當下 `contracts/v1/fixtures/` 是 46 valid ＋ 63 invalid ＝ **109 個檔**（`plan/17/09` §1 寫的 96+14=110 與實際清單差一個，**以 `AR-00` 擷取到的清單為準**，不要沿用那個數字） |
| `frontend-routes.txt` | 從 `frontend/src/router/index.ts` 抽出 `path`／`name`／`component` 三欄 | 判準 14 的第二個機器斷言 |
| `terminal-latency.json` | e2e stack 上量互動終端的 echo 延遲 p50／p95（50 samples） | `00-…md` §5 的「run log 不得讓終端變頓」那條，需要一個**基線值**才有意義 |
| `COMMIT` | `git rev-parse HEAD` | 讓上面五份的來源可驗證。**沒有它，「與升級前 diff」是一句沒有被錨定的話** |

**`terminal-latency.json` 是本期新加的一份**。V2.1 不需要它，因為 V2.1 在那條 socket 上
只多了一次投影往返；V2.2 會在同一條 socket 上持續送 log。沒有升級前的數字，
「終端有沒有變慢」就只能靠感覺。

## 2. `AR-00` — 五項開工前量測（M-AR-1 已完成）

### M-AR-1 — `claude` 與 `codex` 的非互動介面 ✅ **已於 2026-08-10 量完**

原本這是本期唯一一個「不量就不能開工」的量測，而且原本記成「這台機器上兩支 CLI 都沒裝」。
**那是錯的**：兩支都在 `~/.local/bin/`，`which` 之所以找不到，
是因為用了預設 PATH——而 `plan/17/09` §5 的第一列環境事實寫的正是這件事。

**答案與三個結論在 [`10-open-measurements.md`](./10-open-measurements.md) §1.1**，
摘要：`runArgs = {claude: ["-p","--output-format","stream-json"], codex: ["exec","--json"]}`。
**兩支都從 stdin 收 prompt，所以 D7 成立**，SEC-002 的 argv 條文逐字不變。

🆕 **2026-08-11 補量到最重要的一項：兩支都有為程式設計的事件流**
（`--output-format stream-json`／`--json`）。它讓存活判定不必靠牆鐘逾時，
也讓「用互動模式（PTY）取得即時狀態」這條路不必走（`00-…md` D21、`04-…md` §3.4）。

殘留兩項：`claude --permission-mode` 用哪個值，以及 `idle_timeout_seconds` 的值
（M-AR-9），兩者都要一次真的 run。

### M-AR-9 — 事件間隔的尾巴（校準 `idle_timeout_seconds`）🆕

2026-08-11 的存活判定改成事件流之後（`00-…md` D21），
`runner.idle_timeout_seconds = 300` 是唯一一個「不量就只能猜」的常數。
**要看的是 p99.9 的尾巴不是中位數**——誤殺發生在尾巴，而誤殺會重排，
所以誤殺一次通常是誤殺三次。詳見 `10-…md` §1.5。

### M11／M12 — clone 耗時與 run 目錄大小 🆕 **裁決把它們拉進本期**

原本是 V2.3 開工前（`research/02/10` §5）。裁決把 clone 提前，
所以它們現在擋 `AR-07b`：**沒有這兩個數字就設不出配額，而沒有配額的 run 目錄
會吃掉整台機器的磁碟。** 詳見 `10-…md` §1.2／§1.3。

M11 另有一個本計畫加的問題：**淺 clone 與 mirror 的比較**。
`research/02/01` D19 規則 4 直接寫了「用 mirror」，但那是一個**假設 repo 很大**的結論；
一個不需要的快取層是一個要清理、要處理鎖競爭、要處理損壞的東西。量完再決定。

### M-AR-2 — 一次典型 run 的 log 產生速率

決定 D3 的兩個常數（chunk 32 KiB、聚合窗 2 秒）是不是合理，也是
`CLIORA_RUN_LOG_MAX_BYTES` 預設 5 MB 的第一個檢驗。用 `daemon/cmd/fakecli` 改一個
只吐輸出的變體，量三檔速率（1 KB/s、100 KB/s、1 MB/s）下的：
每秒訊框數、Central 的 DB 寫入次數、**同一個 node 上互動終端的 echo 延遲**。

第三欄是重點——它是 `00-…md` §5 那條風險的直接證據，而且它要對照
`AR-00` 存下來的 `terminal-latency.json`。

## 3. `AR-01` — ADR 0029：Agent Runner 模型與 run 生命週期

沿用既有 ADR 格式：Status／Date／Amends／Related／Requirements／Contract／Ships in／Plan
＋ **Alternatives rejected 表**。涵蓋 D16／D17／D17b／D24／D26（**D18 移到 V2.3 的 ADR 0032**）。

### 要寫清楚的七件事

1. **Runner 是 `agentd` 的一個模式**（D16）。重用既有的 enrollment、Ed25519 憑證、
   outbound WSS、heartbeat、doctor、release／update。**不新增信任建立流程**——
   這是本 ADR 最重要的一句。推論：runner 的線上狀態**就是** node 的線上狀態，
   不另做一套 heartbeat；而**一個 node 一列 runner**（`00-…md` D9）正是這條推論的資料模型形式。

2. **拉取式認領**（D17）與其理由：平台不寫排程器，背壓天然。
   **指定 agent 是 poll 查詢的一個 `WHERE` 條件，不是推送**（D17b）——
   三個邊界逐條寫進 Decision，各配一條測試。

3. **認領發生在 poll 當下，不是在 offer 被接受時**（`00-…md` D1）。
   這是本 repo 特有的一條，理由是兩行程式碼（`registry.py:276`／`connection.go:494`），
   要連同**被否決的三方握手**一起寫進 Alternatives rejected——否則日後有人讀 `research/02/01`
   的訊息清單，會以為實作寫錯了。

4. **資格判定是四條件**（2026-08-10 裁決）：卡片在 `ready`、`dependsOn` 全滿足、
   runtime 相符、`assigned_runner_id` 為 null 或等於該 runner。
   **綁定與 labels 兩條不在本期**，而這件事要寫成一個**姿態宣告**而不是一句省略：

   > V2.2 的授權邊界是 **enrollment**。任何 enroll 過的 node 上的 runner
   > 都能領任何專案的卡片、拉任何專案的程式碼。逐專案的授權從 V2.3 起提供。

   同一句話要出現在 `rbac.py` 的註解與 Agents 頁的 UI 上（`02-…md` §6、`07-…md` §2.1）
   ——三個地方，因為它是那種「不寫下來就會被當成 bug 回報」的設計。

   **`authorize_workspace()` 不在這條路徑上**，而那是一個減法：run 不碰 workspace，
   所以那個函式仍然只有一個呼叫者群組，紅線 2 的適用範圍變乾淨而不是變複雜
   （`03-…md` §3.2）。

5. **租約語意**：續租週期 30 秒、逾時 180 秒、重排上限 3、用完進 `blocked`；
   **`waiting_for_input` 續租但不計執行逾時，也不佔 `max_concurrent`**
   （比規劃多的一條，理由是等回覆的 run 沒有在跑程序）。

6. **Agent Run 不是 Session，也不使用 workspace 綁定**：不進 `terminal_sessions`、
   不走 Terminal relay、不佔 writer 名額、沒有 tmux 持久化、**不在任何 allowed root 內**。
   **兩條路徑在程式碼上分開**，機器形式是
   `GATE-AR-TOUCH-LIST` ＋ 🆕 `GATE-AR-NO-WORKSPACE-IN-RUNS`（`08-…md` §3.1）。

7. **本期的已知缺口換了一組**（裁決移除了原本那一個）：
   ① **任何 runner 都能拉任何專案的程式碼**（授權邊界是 enrollment）；
   ② **Agent 可以用 node 既有的 git 憑證做 git 能做的任何事，包含 push——這是刻意給的**
   （2026-08-10 第二次裁決，`04b-…md` §5.4，詳細落地在 ADR 0031 而不是這裡）。

   第①條寫進 Consequences（沿用 ADR 0027 記錄既有揭露的同一種做法），
   **而且要先寫清楚什麼不是新的**：人本來就看得到所有專案
   （`api/http/projects.py:109` 的 docstring），真正變的是「程式碼落在哪台機器」。
   第②條寫進 Status，因為它是一個**選擇**而不是一個後果。

### Alternatives rejected

| 被否決的 | 為什麼 |
|---|---|
| 平台推送式派工 | 會長成排程引擎，且違反紅線 4 的「不自動指派」 |
| 把 run 建成一種 Session | 生命週期不同，會污染既有狀態機；而且直接違反出口條件 16 |
| 新做一支 runner binary | 重複整條信任鏈（`plan/02` 的 enrollment ＋ 憑證），那是目前系統裡最不該重做的東西 |
| `offer → accept → claimed{granted}` 三方握手 | 多一個訊息型別，而且認領窗口只是往後挪，沒有消失（`00-…md` D1） |
| 一個 node 多列 runner | 共用一條 WSS 之後「哪一列在線」永遠等於 node 的狀態，那個欄位會變成假指示燈（`00-…md` D9） |
| **在使用者綁定的 workspace 上執行** | 2026-08-10 裁決否決的那一個：無人值守 ＋ 使用者的未提交工作 ＝ 一個不該存在一個階段的缺口。Agent 自己 clone 到隔離目錄 |
| **本期預先建 `project_agents` 表** | 一個不授權任何東西的授權表，會讓 V2.3 的安全審查失去一個真正的檢查點（`02-…md` §2.2） |
| 指定逾時自動退回任一 agent | D17b §3：會指定的理由通常正是「只有那台機器有需要的東西」，在錯的機器上執行比多等更糟。真的需要時做成卡片上的 opt-in 欄位 |
| 把 run 升級成互動 Session 接管 | D26：run 的工作目錄會被清掉，變成持久 tmux 要重新設計生命週期 |

## 4. `AR-02` — ADR 0030：run 的兩種輸出

一份 ADR 涵蓋 log 與產物，因為它們是同一個問題的兩半：
**run 產生的東西怎麼離開 node、存多久、誰清。**

### Part A — run log（D27）

核心是那張「互動式 Session vs Agent Run」對照表，以及一句話：

> **這不構成「平台現在會存終端內容」的先例。** 互動式 Session 的承諾未變。

四條約束逐條寫進 Decision，各配一條測試：

| 約束 | 落地 | 測試 |
|---|---|---|
| 有界 | `CLIORA_RUN_LOG_MAX_BYTES` 預設 5 MB，超過從中間截斷 | 出口條件 14 |
| runner 端去識別 | **本期沒有機密可去識別，但掛勾點要在**：`redactor` 介面 ＋ 一個 no-op 實作 ＋ 一條「所有 log 都經過 redactor」的測試 | `04-…md` §5 |
| 保留期 | 成功 3 天、失敗 14 天，Central 側清理 | `02-…md` §2.4 |
| 不是 Terminal relay | 單向、批次、可丟棄；不走 `terminal.*` 任何一條路徑，沒有 writer／viewer 語意 | `GATE-AR-TOUCH-LIST` |

**本期新增的第五條約束**（本計畫比規劃多的）：
**Central 的記憶體聚合窗（≤64 KiB／≤2 秒）意味著 Central 崩潰會掉最後一段 log。**

**2026-08-11 裁決：接受這個代價。** 但它**必須寫進 ADR 的 Consequences 而不是留在
程式碼註解裡**——一個「資料會掉」的設計如果只寫在實作旁邊，
下一個人讀到 `run_logs` 會以為它是完整的。要寫的三句：

1. **掉的是什麼**：Central 行程崩潰時，每個進行中的 run 最後未 flush 的 ≤64 KiB。
2. **為什麼可接受**：log 是**診斷**——重跑一次就有了。而這條路徑上的替代方案
   （每個 chunk 一次 DB 往返）會在 `node_gateway` 的單一迴圈裡阻塞**互動式終端的輸出**，
   那是拿 V1 的體感去換 Agent 的除錯輸出。
3. **什麼不受影響，以及為什麼那是刻意的**：**卡片產物走 HTTP 端點並逐件落地**（D4）、
   **卡片訊息走 API 並逐筆 commit**。兩者都是交付物，而它們**刻意不走聚合這條路**
   ——這個不對稱是設計，不是遺漏。

### Part B — 卡片產物（D29）

- **能力與宣告分開**：任何 run 隨時都能附加產物；`delivery: artifact` 的宣告與 Done Gate 留到 V2.4。
- **存平台不存 node**（D29 §3）：run 目錄有保留期，卡片是永久的。
- **三層配額**：單件 10 MB、單 run 件數上限（預設 20）、專案總配額（預設 1 GB）。
- **提供時預設下載不渲染**（D29 §4，`00-…md` D14 是它在本 repo 的落地形式）。
- **不可變**：沒有 update 端點。刪除只有 `project.manage`，需理由 ＋ audit。
- **不保證不含機密**：runner 端去識別只對 log 的文字串流有效。
  誠實寫進 ADR 與 UI 文案，**不要暗示產物是安全的**。

### 兩者的保留期不同，這是本 ADR 最重要的一句

| | `run_logs` | `task_artifacts` |
|---|---|---|
| 是什麼 | **診斷**紀錄 | **交付物** |
| 誰清、何時 | 保留期到期自動刪（成功 3 天／失敗 14 天） | **跟著卡片走**；卡片在就在 |
| 上限 | 單 run 5 MB，超過截斷 | 單件 10 MB、單 run 20 件、專案 1 GB |
| schema 上的差別 | 有 `expires_at`，有清理迴圈 | **沒有 `expires_at`**，沒有清理迴圈 |
| 掉了會怎樣 | 重跑一次就有了 | 那份工作消失了 |

混為一談會讓卡片上出現死連結。**閘門三**（`00-…md` §4）就是為這一條設的：
ADR 要在建表之前接受。

這是 ADR 0024 W2「誰清這個、什麼時候清」在本期的答案，而本期有**三個不同的答案**
（`run_logs` 有保留期、`task_artifacts` 沒有、`run_tokens` 隨 run 結束失效但列保留 90 天供稽核）
——與 V2.1 一樣，寫在同一張表裡，讓下一個階段不必重新推導。

## 4b. `AR-02b` — ADR 0031：隔離工作目錄與 git 取得（🆕 原屬 V2.3）

**只寫取得半邊。** push、`cliora/` 分支命名空間、五條 git 硬約束、bot identity
留給 V2.3 增補**同一份** ADR。

三段內容，設計細節在 [`04b-run-directory-and-git.md`](./04b-run-directory-and-git.md)：

1. **目錄六條規則**（D19）：不在 allowed root 內（**雙向**）、每次新建、兩層配額、
   repo 快取、誰清理、`artifacts/` 是列舉不是瀏覽器。
2. **git 取得的約束**：只做 `clone`／`fetch`／`checkout`／`worktree add`、host allowlist、
   known_hosts pinning、**clone 後移除 `origin`**。
3. **既有 git 憑證與 Agent 的 git 自由，五條後果**（`04b-…md` §5.4）。
   第三條是一個**刻意給的自由**（第二次裁決），所以**不得寫成「我們擋不住，抱歉」**
   ——那個框架已經被撤回。要寫的是收斂點（紅線 5 的原則、部署姿態、可觀測性）。
4. 🆕 **紅線 4 第 1、2 條的措辭修訂**（`04b-…md` §5.5）：主詞從「Agent」改為
   「平台的 push 路徑」。`research/02/00` §7 已於同日改好，ADR 0031 要引用它。

### 這份 ADR 的 Status 段要寫明它會被 amend

> 本版只涵蓋 git 的**取得**半邊。送回半邊（push、分支命名空間、五條硬約束）
> 與平台管理的憑證由 V2.3 增補本文件。

一份會被 amend 的 ADR 要在第一版就說它會被 amend——否則 V2.3 的人會不確定
自己該改這一份還是開一份新的，而兩個答案都會產生一份說謊的文件。

### Alternatives rejected

| 被否決的 | 為什麼 |
|---|---|
| run 目錄落在 allowed root 內 | 兩套授權模型互通：Agent 的中間產物出現在使用者的檔案瀏覽器裡，使用者的 `filesystem.store` 能寫進 run 目錄 |
| 用 `RuntimeDirectory`（`/run/agentd`） | tmpfs，重啟就消失，而失敗的 run 目錄要留 14 天（`00-…md` D17） |
| 引入 Go 的 git library | mirror／worktree 是它最弱的部分；而且 Agent 在沙箱裡用的是真的 `git`，兩套實作會看到不同狀態（`00-…md` D18） |
| 每次完整 clone（不做 mirror） | **不是否決，是待量測**：M11 若顯示 Traqora 這種規模的 repo 淺 clone 就夠快，mirror 是一個不需要的快取層。**量完再決定，而這句話要寫進 ADR** |
| 把 token 塞進 remote URL | 它會出現在 `git remote -v`、reflog 與錯誤訊息裡（D20）。本期連 URL 都拆成三欄存，讓 userinfo 不可表示 |
| **clone 之後移除 `origin`** | 2026-08-10 第二次裁決撤回：它會連帶弄壞 fetch／pull 與那個被允許的 push。**換上的是可觀測性而不是阻止** |
| **建議 runner node 只帶唯讀 git 憑證** | 同一次裁決撤回。runbook 改成「這台機器能碰到什麼，Agent 就能碰到什麼——所以 runner node 要專用」 |
| 為了阻止 Agent push 而移除它的 shell 能力 | 那會讓自主執行退化成互動式 Session（D25）。本期的處置是限制**產出怎麼離開**，而不是限制沙箱內能做什麼 |

## 5. `AR-01` — 需求變更與 traceability

### 5.1 PRD §8.13

新增 FR-AGENT-001、003–013（`research/02/11` §2，已於 2026-08-10 更新），每條配 AC。
**FR-AGENT-002（Project × Agent 多對多）移到 V2.3 成為 FR-RUNENV-006**；
新增三條 🆕 FR-AGENT-011（隔離工作目錄）／012（自行取得程式碼）／013（變更不得靜默丟棄）。

要注意的四件事：

- **FR-AGENT-003 的 AC 要寫「四條件」**，並把「授權邊界是 enrollment」寫成一條 AC
  而不是一句備註——它是本期唯一一個要人接受的**姿態**，而姿態要可追蹤。
- 🆕 **FR-AGENT-011 的 AC 要小心不要寫成一句做不到的保證。** 三條 `automated` AC：
  ① 既有檔案 API 讀不到 run 目錄；② run root 落在 allowed root 內時 daemon 拒絕啟動；
  ③ `dedicated` 由 daemon 回報並在 console 顯示。
  **不要寫「run 程序讀不到 allowed root」**——那件事平台沒有實作
  （`04b-…md` §3.4）。AC 是需求的可驗證形式，寫一條驗不了的 AC
  等於在 traceability 裡放一個永遠 `pending` 的格子。
- 🆕 **FR-AGENT-012 的 AC 要包含「缺憑證秒級失敗」與「run 摘要記錄得出有沒有動到遠端」**。
  前者的 `verification` 是 `measurement`（< 30 秒），不是 `automated` 的布林。
  **不要寫「clone 後 `git remote -v` 為空」**——第二次裁決撤回了那個作法。
- **FR-AGENT-009／010（產物）的 AC 要包含否定命題**：
  「應用 origin 內沒有任何路徑會渲染產物」——AC 的 `verification` 標為 `automated`
  並指向 OpenAPI 掃描與前端路由表 diff 這兩個機器斷言，不是 `manual`。
  （V2.1 的 `plan/17/09` §3 第 8 條已經踩過一次：schema 的 enum 根本沒有 `manual`。）
- **FR-AGENT-005 的 AC 要包含「`terminal_sessions` 的列數不變」**，
  那是出口條件 12 唯一可機器判定的形式。

### 5.2 skill 範圍句的補述

`.agent/skills/cliora-project-context/SKILL.md` 目前禁止在沒有需求變更的情況下引入
「Git automation, task routing, or multi-agent orchestration」。V2.0 已經改過那一句。
本期要補的是**兩個 V2.0／V2.1 都沒有的面**：

1. **無人值守執行**：平台現在會讓一個程序在 node 上跑，而且沒有人在終端前面。
   範圍句要寫清楚：**單一 Agent 走完一張卡仍然不是多 Agent 編排**；
   跨 Agent 協作、Agent 互相派工仍然不做。
2. **平台儲存 Agent 產生的檔案**：這是 V1「平台不儲存終端位元組」承諾旁邊的新東西，
   範圍句要指向 ADR 0030 的區分，而不是含糊地說「平台現在會存東西」。
3. 🆕 **平台觸發 git 操作**：V2.0 改過的那一句把「Git automation」放進範圍，
   但當時的範圍是「V2.3 起」。裁決把取得半邊提前，所以範圍句要改成
   **「唯讀的 git 取得從 V2.2 起在範圍內；任何遠端寫入仍在範圍外，直到 V2.3」**
   ——一個階段一個句子，否則下一次有人讀它會以為 push 也已經開放了。

### 5.3 traceability 註冊

八筆需求先進 `traceability/requirements.json` 標 `proposed`，`AR-12` 翻 `active`
（沿用 `TK-01` → `TK-11` 的節奏）。`make traceability` 要綠。

### 5.4 上游的回寫 ✅ **已於 2026-08-10 完成**

裁決當天已改的九份文件，列在這裡是為了讓 `AR-01` 不必重做一次：

| 檔案 | 改了什麼 |
|---|---|
| `research/02/04-phase-v22-agent-runner.md` | **整份改寫**：§0 搬動表、四條件、AR-02b、AR-04b（ambient 憑證）、23 條出口條件、風險表 |
| `research/02/05-phase-v23-secrets-and-isolation.md` | 範圍改寫：隔離與 clone 移出，`project_agents` 移入，SC-02／SC-05 重寫 |
| `research/02/01-architecture-decisions.md` | D17 資格判定、D17b 邊界 1、D18（延後）、D19（提前）、D20（拆兩半）、D30（V2.2 那一列） |
| `research/02/00-upgrade-roadmap.md` | §2 工作目錄那一列、§6 階段表與裁決註記 |
| `research/02/08-data-model-and-contract.md` | §2 表格階段與 migration 編號、§4 protocol（`source` 提前、`run.artifact` 不做）、§7 資源授權、§8 環境變數與 daemon config |
| `research/02/10-verification-and-exit.md` | **§2.3 標題更正（原誤寫為「V2.2」，實為 V2.4）**、§2.4 改寫、§2.5 改寫、§4 測試矩陣、§5 M11／M12 時機、§6 安全審查觸發 |
| `research/02/11-requirement-traceability.md` | FR-AGENT 清單（002 移出、011–013 新增）、FR-RUNENV 標題、ADR 0031 的階段 |
| `research/02/09-frontend-information-architecture.md` | §4.3b Agents 頁（無綁定欄 ＋ 姿態宣告 ＋ Repository 區）、§4.7 Run 詳情 |
| `research/02/CHECKLIST.md` | §4 的 AR 列、D30 那一列、SC 前置條件、ADR 0031 |

**`research/02/10` §2.3 那一處是獨立於裁決的一個更正**：
它的標題寫「V2.2」但內容（`plan snapshot`、驗證報告、Done Gate、Admin `--force`）
對應的是 FR-PLAN／FR-VERIFY，那是 **V2.4** 的工作包。
不更正的話，`AR-12` 會對著一份不屬於本期的出口條件清單交差。
