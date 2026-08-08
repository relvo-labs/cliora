# 07 — 前端資訊架構

延續 `research/style.md` 的 Quiet Intelligence ＋ Developer Workbench ＋ Modern Industrial 方向。本階段沒有新的視覺語言，只有新的資訊層級。

## 1. 一條貫穿全篇的原則

> **Terminal 仍然是主要工作區。** V2 加的所有東西都不得讓它變窄。

`research/style.md` §12／§18、`plan/08`（三欄改兩欄 ＋ 中央區 tab、放棄面板拖曳與收合）、`plan/09`（sidebar 280→208px，空間讓給中央區）三份決定都指向這一句。`version2.md` §9 畫的四欄版面會一次推翻它們，所以**不採用**（見 §5）。

## 2. 導覽重整

現況五個平項（`frontend/src/components/layout/AppLayout.vue`）：`Dashboard`、`Nodes`、`Sessions`、`Enrollment`、`Audit`（另有 `/settings/integrations`、`/nodes/:id/tunnels` 由頁內入口進入）。

V2 改為三組：

```text
Projects                    ← 新，V2.0
  （CLIORA_PROJECTS_ENABLED 關閉時整組不出現）

Sessions                    ← 既有 /sessions（使用者直接操作的路徑，不變）

Infrastructure
  Dashboard                 ← 既有 /dashboard
  Nodes                     ← 既有 /nodes
  Agents                    ← 新，V2.2（CLIORA_AGENT_RUNS_ENABLED 關閉時不出現）
  Enrollment                ← 既有 /enrollment
  Audit                     ← 既有 /audit
  Integrations              ← 既有 /settings/integrations
```

**`Sessions` 與 `Agents` 是兩條執行路徑的入口，刻意分開**：Sessions 是「我自己來」，Agents 是「派給它做」。把 run 混進 Sessions 清單會讓兩種生命週期看起來像同一種東西（`00` §2）。

三條硬規則：

1. **既有路由路徑一律不變。** 這是重新分組，不是搬家。任何人存的書籤都還能用。
2. `Integrations` 從「只能從頁內進入」升格為導覽項——它本來就是一個獨立設定頁，順手補上。
3. 旗標關閉時退回五個平項的原樣（含順序），`/projects*` 回 404 而不是空頁。

## 3. Sidebar 寬度必須重新驗算

`plan/09` 把 `--layout-sidebar` 從 280px 改成 208px，理由是「最長項需 ≈144px，208px 留 64px 餘裕：中文化標籤或多一個項目都不會擠」。

V2 要加的是**一個導覽項 ＋ 兩層階層**，所以那 64px 餘裕的用途已經被指定過一次，不能再假設它還在。PJ-06 必須先量再改：

| 檢查 | 方法 |
|---|---|
| 最長項是否仍 ≤144px | 量 `Infrastructure` 群組標題與其縮排後最長子項（`Integrations` 縮排 12px 後約 155px） |
| 208px 是否仍夠 | 若不夠，優先**縮小縮排**（8px）或把群組標題做成無縮排的分隔線樣式，而不是把 sidebar 加寬 |
| 高度 | 現在是 5 列，之後是 3 組共 8 列 ＋ 2 個標題。1080p 沒問題，但 `plan/09` 的 app-shell 高度規則要複驗一次 |

**不得**為了容納群組而把 sidebar 加回 280px——那會直接推翻 `plan/09` 的整個理由。

## 4. 新畫面

### 4.1 `/projects` — 專案列表（V2.0）

卡片或表格列，每列：名稱、狀態徽章、綁定的 workspace 數（含所在 node 數）、進行中的 Session 數、最後活動時間。篩選：狀態、我擁有的。

空狀態要有意義：「還沒有專案。你仍然可以直接從 Sessions 建立 Ad-hoc Session。」——這句話同時教了兩件事。

### 4.2 `/projects/:id` — 專案總覽（V2.0，V2.1／V2.3 逐步充實）

分頁：`Overview` / **`Requirements`（V2.1 人工／V2.5 Agent 驅動）** / `Board`（V2.1）/ `Roadmap`（V2.1）/ `Activity` / `Settings`。

Overview 內容：描述、綁定的 workspace 清單（node 名稱 ＋ 線上狀態 ＋ 路徑 ＋ 「開 Session」按鈕）、進行中的 Session、近期活動、進度與風險摘要（V2.3）。

**綁定清單的狀態表達很重要**：node 離線、root 被停用、路徑已不存在，三種情況要分得出來，且都不是錯誤頁——是這一列上的一個狀態。

### 4.3 `Board` — 看板（V2.1）

- 六車道，沿用 Monstrare 的 `stage` 值，顯示中文標籤（`01` D3）。
- **卡片可拖曳**（V2.1 起）。互動契約：樂觀更新 → `PATCH`（帶 `version`）→ 失敗一律**彈回原位並重新載入該卡**，訊息要具體（`409` 是「這張卡剛被別人改過」、被 `dependsOn` 擋是「TASK-101 尚未完成」、被 Done Gate 擋是「缺驗證報告」）。
- 卡片顯示：`card_ref`、標題、risk 徽章、owner／assignee、阻塞徽章（`dependsOn` 未滿足）、**run 狀態徽章**（排隊中／執行中＋agent 名稱／等待你的回覆／失敗）、**交付徽章**（`delivery` 四值，`none` 用低調樣式）、驗證狀態（V2.4）。
- **「等待你的回覆」必須是整個看板上最醒目的狀態**——它是唯一一個「系統在等人」的狀態，其他都是「人在等系統」。
- **指定了 agent 的卡片顯示 agent 名稱**；未指定的顯示「任一 Agent」。等待中的兩種原因要分開寫：「等待可用的 Agent」與「等待指定的 Agent：dev-vm-01（離線）」。
- 車道標頭計數；超過 WIP 建議值變色但不阻擋（Monstrare 的既有語意）。
- 卡片上的 `agent` 欄位有值時顯示 agent 名稱，空值代表純人工——這個區分來自 Monstrare 的卡片 schema，在一個 Agent 與人共用的看板上是必要的。

### 4.3b `Agents` — Runner 管理（V2.2，Infrastructure 群組）

清單：runner 名稱、所在 node（連結到既有 node 詳情）、runtime、labels、`max_concurrent` 與目前負載、**綁定的 Project 清單**、線上狀態、啟用開關。

- 線上狀態就是 node 的線上狀態（D16），不另做一套指示燈。
- 綁定 Project 的 UI 要說清楚它的意義：**綁定＝授權該 runner 取用該專案的機密**。這不是一個隨手勾的核取方塊。
- 容量用盡（run 目錄配額）時顯示原因，不是顯示成離線。
- 每個 runner 顯示「目前被指定的卡片數」，讓人看得出某台機器是不是被綁死了。

### 4.4 `Roadmap` — 藍圖（V2.1）

Epic → User Story → Task 三層摺疊，每層顯示完成度（`stage === 'done'` 卡數／總卡數）。指定 Epic 但未指定 User Story 的卡落在「（未分類任務）」桶。這是直接對應 `../Monstrare/tools/kanban/` 的藍圖分頁語意。

### 4.5 `/projects/:id/tasks/:cardId` — 任務詳情（V2.1 起）

兩欄：

```text
+-------------------------------------------------------------+
| TASK-123  Workspace File Tree API              進行中        |
+----------------------------+--------------------------------+
| 任務定義                    | Agent 執行                     |
| ・目標／範圍／非目標        | Runtime: codex                 |
| ・驗收標準（勾選狀態）      | Node: dev-vm-01                |
| ・Readiness 7 項            | Workspace: backend             |
| ・Review Gates 6 項         | Session: 進行中                |
| ・相依與阻塞原因            | [開啟 Terminal] [恢復 Session] |
| ・關聯文件（六個 links）    |                                |
+----------------------------+--------------------------------+
| 執行計畫（最新快照 ＋ 歷史）            V2.2                 |
+-------------------------------------------------------------+
| 驗證報告（checks／AC／殘留風險）        V2.2                 |
+-------------------------------------------------------------+
| 證據（三種 source 分別標示）            V2.3                 |
+-------------------------------------------------------------+
```

**證據的來源標示是設計的一部分，不是附註**：`machine_verified` 用實心徽章、`platform_observed` 用線框徽章、`agent_reported` 用灰字 ＋「Agent 自述」字樣。失敗的 check 與 AC 預設展開且不可摺疊隱藏（`version2.md` §14.3）。

### 4.5b `Requirements` — 需求釐清與拆解（V2.1 人工／V2.5 Agent）

四個畫面，一條線走下來：

1. **Intake**：一個刻意簡單的輸入框——**它接受的就是一句模糊的話**，那是整條流程的前提。不要一開始就逼人填十個欄位。
2. **釐清中**：**重用 §4.6 的卡片訊息串元件，不新做**（D28：兩套訊息管道會立刻分裂）。差別只在頁面位置。顯示「Agent 上次拉取訊息：<時間>」。
3. **規格審閱**：objective／scope／non-goals／AC 逐項；**`open_questions` 置頂，未解決時核准按鈕停用**並說明是哪幾個；版本比較（第 N 版 vs 第 N-1 版）。
4. **提案接受**：Epic／User Story／Task 三層樹狀勾選（各層可獨立勾）、可就地編輯、**顯示每張卡的 DoR 缺項**、底部顯示「將建立 N 張卡片」。

**來源可追溯**：每張卡的詳情頁顯示「來自需求 #12 的提案 #3」。

### 4.6 卡片訊息串（V2.2）— 「平台作為橋樑」的具體形式

這是裁決裡「使用者透過任務看板跟 agent 溝通」的落點，值得做好而不是做成一個註解欄位：

- 使用者留言、Agent 回覆、系統事件（領取／開始／完成／失敗／交付）三種混排，來源可辨識：使用者用一般樣式、Agent 用帶 runtime 圖示的樣式、系統事件用低調的單行樣式。
- **Agent 的提問要醒目**，並在卡片頂部與看板上同步顯示「等待你的回覆」。
- 輸入框固定在下方，送出後即時出現（Agent 會在下次拉取時看到，UI 要說明這一點——不要讓人以為 Agent 沒回應）。
- 顯示「Agent 上次拉取訊息：<時間>」，這一行讓等待變得可理解。

### 4.6b 卡片產物區（V2.2，D29）

卡片上獨立一區，與訊息串並列：

- 列出所有產物：檔名、大小、來自哪次 run、時間、上傳者（人或 agent 要分得出來）。
- 訊息裡的附件**同時**出現在訊息與產物區——同一件東西兩個入口，不是兩份資料。
- 圖片顯示縮圖；其餘一律**下載按鈕**。
- **不做「在新分頁開啟」**——那等同內嵌渲染，而 Cliora 是單一 origin 部署（D29 §4）。HTML 產物只能下載，或（若日後決定做）放進 `sandbox` iframe。
- 專案配額用量顯示在 Project Settings，接近上限時在卡片上提示。
- **不要在 UI 上暗示產物是安全的**：它是 Agent 產生的檔案，平台不保證它不含機密（D29 §5）。

### 4.7 Run 詳情頁（V2.2 起）

- 狀態、所屬 Task 與 Project、執行的 runner、attempt 次數。
- 時間軸：queued → claimed → running → …，每一段的耗時。
- **Log 串流**：可跟隨、可搜尋、**明示截斷位元組數**、明示保留期到期時間。
- V2.3 起：checkout 的 commit、用了哪幾個機密的**名稱**、工作目錄大小。
- V2.4 起：交付結果（**卡片產物**／PR／分支連結、`diff --stat`、或「無變更」、或「宣告不交付但偵測到變更，diff 已附為產物」）。
- 取消按鈕（`run.cancel`）。

## 5. Session Workspace 的擴充（V2.1／V2.4）

**不做 `version2.md` §9 的四欄。** 改為右欄 tab 化：

```text
+------------------------------------------------------------------+
| ← Back | Project · TASK-123 · codex · dev-vm-01      （header）  |
+--------------------------------+---------------------------------+
|                                | [Task] [Plan] [Files]           |
|  中央區（既有 tab）             |                                 |
|  Terminal / Files / Preview     |  Task: 目標、AC、阻塞           |
|                                 |  Plan: 步驟與狀態（唯讀）       |
|                                 |  Files: 既有 FileTree          |
+--------------------------------+---------------------------------+
| Task 狀態 | 驗證 | Session 狀態        （既有 status bar 擴充）  |
+------------------------------------------------------------------+
```

理由與代價：

- 沿用既有的兩欄 grid（`grid-template-columns: 1fr 300px`），Terminal 寬度**完全不變**。
- 右欄本來就只有 FileTree，tab 化是既有中央區做法的延伸，不是新機制。
- Ad-hoc Session（無 Task）右欄只有 Files，與今天逐像素相同——這是 V2.2 的出口條件之一。
- 若日後真的要四欄，必須先回頭修訂 `research/style.md` §12、`research/tech.md` §16.1、`plan/08`，並寫出「為什麼翻案」。沿用 `plan/08/01` §1.2 的規格同步做法：**不刪除原文，加註記**。

## 6. 狀態與可用性（每個新畫面都要交付）

沿用既有紀律，逐項列出而不是「照 design system 做」：

| 狀態 | 要求 |
|---|---|
| 載入中 | 骨架，不是 spinner 蓋全頁 |
| 空 | 有下一步動作的文案（見 §4.1 的例子） |
| 錯誤 | 安全訊息 ＋ `request_id` ＋ 重試 |
| 權限不足 | 由伺服器 403 驅動的畫面，**不做前端路由守衛**（沿用 `/audit` 與 `/settings/integrations` 的既有決定與註解） |
| Node 離線 | 綁定列上的一個狀態，不是錯誤頁；看板照常（任務資料在平台，不在 node） |
| 沒有可用的 Agent | 卡片可掛佇列，狀態顯示「等待可用的 Agent」並說明缺什麼（沒綁 runner／labels 不符／全部忙碌） |
| 指定的 Agent 不可用 | 「等待指定的 Agent：<名稱>（離線／忙碌）」＋ 改為不指定的按鈕。**與上一列的文案必須不同** |
| 指定的 Agent 不符資格 | dispatch 當下就擋，對話框內指名是哪一個條件（沒綁／runtime／labels／已停用），**不讓它進佇列** |
| Run 失敗 | 失敗原因 ＋ log 連結 ＋ 重試按鈕；attempt 用完時說明為什麼不再自動重試 |
| 機密欄位 | **永遠沒有「顯示值」按鈕**；只顯示名稱、建立者、最後使用時間 |
| 規格有未解決問題 | 核准按鈕停用 ＋ 指名是哪幾個問題，**不是靜默禁用** |
| 提案卡缺 DoR | 接受介面上逐項標示；接受後落 `backlog` 而非 `ready`，並說明原因 |
| 產物配額將滿 | Project Settings 顯示用量；接近上限時卡片提示；用盡時 run 明確報錯而非靜默失敗 |

## 7. Design token 與元件

- 不新增一次性色彩、間距、字級。新的狀態徽章（risk、stage、source）用既有 token 組合；缺的元件照既有風格補做並登記回 `frontend/src/theme/`。
- 六個 stage 的顏色要與既有 Session 狀態色**明顯區分**——同一個畫面上會同時出現「Session 進行中」「任務進行中」「Run 執行中」三種「進行中」，全用同一個綠色會讓人完全看不出差別。建議：Session 沿用既有色、Task stage 用另一組、Run 狀態用第三組並帶動態指示。
- 三種 `source` 徽章（實心／線框／灰字）在 Evidence、驗證報告、Run 詳情三個地方要**完全一致**——它是可信度語言，不是裝飾。
- 時間一律 RFC 3339 UTC 傳輸、畫面轉本地並顯示時區。
