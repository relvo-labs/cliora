# V2 執行清單

12 份規劃文件裡有 47 張 ticket、7 份 ADR、16 個量測項散在各處。這一份把它們攤平成可以逐條打勾的清單。

**閱讀順序**：§0 是現在就能做的 → §1 是擋著開工的 → §2 起是各階段。

---

## §0 現在就能做（不依賴任何裁決）

| ☐ | 事項 | 為什麼急 |
|---|---|---|
| ☐ | 把 `1b3054e`（`.env` gitignore）cherry-pick 到 `dev` | **已核對（2026-08-08）：`.env` 在 `dev`／`master`／`v2` 都沒有被追蹤，所以今天沒有洩漏。** 這是預防不是補救——那條 gitignore 規則目前只存在於 `v2`。低成本、不擋任何事，`master` 會從 `dev` 流過去 |
| ☐ | 對 `dev` 設 GitHub branch protection | 讓「合併需人工確認」（`10` §7）由平台強制，不只靠紀律。**設定：required PR review ×1 ＋ 禁止 force push，但刻意不加 required status checks**——加了會讓「CI 綠了」在 GitHub UI 上長得像「可以合併了」，而 `10` §7 的整個意思是那兩件事不同 |
| ☑ | ~~處理根目錄的 `package-lock.json`~~ | **已核對（2026-08-08）：檔案已不存在，`git ls-files` 也查無此檔。無需動作** |
| ☑ | 審過前端 prototype（`research/prototype-v2/`）並回饋 | 第 1 項（導覽 208px）**已定案**：採 prototype 的無縮排分隔線做法，實測最寬 147px、餘裕 61px（`plan/16/08` §1）。其餘六項仍待回饋，但都不擋 V2.0 |
| ☐ | 決定 Design token 候選要不要進 `frontend/src/theme/tokens.css` | prototype 的「Design token 候選」畫面有色票與 hex。**不擋 V2.0**：本期只用既有 token 組合，三個 Project status 徽章刻意不用綠（把綠留給 V2.1 的 stage 與 V2.2 的 run） |

---

## §1 開工前必須有答案

### 1.1 待裁決的決策（`01` 最後一張表）

| ☐ | 編號 | 問題 | 擋住什麼 |
|---|---|---|---|
| ☑ | — | ~~機密加密主金鑰放哪~~ → **已裁決：環境變數 `CLIORA_SECRET_MASTER_KEY`**（2026-08-08） | ~~V2.3~~ |
| ☑ | — | ~~git 認證用哪一種~~ → **已裁決：fine-grained PAT ＋ SSH key 兩者都支援**（2026-08-08） | ~~V2.3~~ |
| ☑ | D14 | ~~平台不可用時的行為~~ → **已裁決：直接失敗，不做離線佇列**（2026-08-08） | ~~V2.1~~ |
| ☑ | D30 | ~~驗收素材用哪個專案~~ → **已裁決：`Lei-k/Traqora`**，不用 Cliora 自己。**V2.2 期間限用 scratch clone**（2026-08-08） | ~~V2.0~~ |
| ☑ | D31 | ~~RQ-07 的 mockup 預覽~~ → **已裁決：走既有 tunnel 整合**（目前只有 Pinggy）。**未啟用整合則系統不做 mockup**：`ui` gate 自動停用（2026-08-08） | ~~V2.5~~ |
| ◐ | — | MCP：**transport 已裁決為 stdio**（2026-08-08）；**做不做**仍看 M2／M5／M17（`01` D11 的規則） | V2.4 的條件性工作包，**V2.1 上線後就要看數據** |

### 1.2 建議採納但需點頭的決策

D3 看板詞彙 · D4 Epic/US 升為實體 · D7 情境交付 · D8 情境預算 · D9 計畫形狀 · D10 證據分級 · D11 工具介面 · D12 相容機制 · D13 RBAC · D15 流程可設定性 · D16 Agent 實體 · D17 認領模型 · D18 三層綁定 · D19 隔離目錄 · D23 SEC-002 修訂 · D24 看板溝通 · D25 自主執行收斂 · D26 Session 與 Run 關係 · D27 Run log 界線

（D20 Git 存取、D22 機密管理、D14 離線行為已於 2026-08-08 裁決，不在此列。）

☑ **2026-08-08 裁決：一次全數採納，三條例外。**（完整說明在 `01` §決策裁決表的註記）

| 例外 | 決策 | 裁決 |
|---|---|---|
| 1 | **D7** | 採納，但**「代打第一行指令」整條刪除**，不留成 opt-in。它要付新的稽核語意、確認 UI、橫幅與一組時序條件，買到的是使用者少按一次 Enter；而 D7 自己已寫「Agent Run 路徑不需要它」 |
| 2 | **D10** | 採納。內文的「平台代跑驗證命令否決」與裁決表的「改為允許」原本互相矛盾。**定案**：否決的是「讓呼叫端指名命令的 API」，允許的是「daemon 在 run 目錄內執行卡片宣告的驗證命令」。進 ADR 0032 |
| 3 | **D13** | 採納，歸屬不變。但要寫明 `task.approve` 與 `task.update` 的**持有者集合刻意相同**——拆開是為了 token scope 而非角色分離。不寫這句，日後的「反正持有者一樣，合併吧」會靜默打開 Agent 自我核准的路 |

另有一項對 **D30** 的階段修訂：**V2.0 不使用 Traqora**，用 `run-stack.sh` 既有的合成 workspace
（V2.0 一行程式碼都不讀，Traqora 的價值從 V2.1 才開始兌現）。

### 1.3 開工前要有的量測（`10` §5）

| ☐ | 編號 | 量什麼 | 卡住 |
|---|---|---|---|
| ☑ | M8 | ~~sidebar 208px 在八列兩層下夠不夠~~ → **已量（2026-08-08）：最寬 `Integrations` 147px（無縮排分隔線版），208px 餘裕 61px，不用改。** `scripts/pj/measure-sidebar.mjs`，詳見 `plan/16/08` §1 | ~~V2.0 開工~~ |
| ☐ | M1 | 200 張卡的看板 API 回應大小與耗時 | V2.1 開工 |
| ☐ | M11 | 真實 repo 首次 clone vs worktree 耗時 | V2.3 開工 |
| ☐ | M12 | run 目錄典型大小、3 個並行需要多少磁碟 | V2.3 開工 |
| ☐ | M6 | `git status --porcelain` 在最大 repo 的耗時 | V2.4 開工 |

上線後觀察：M2（**Agent 實際使用 CLI 的比例——內化路線的核心假設，同時決定 MCP 做不做**）、M5 與 M17（**與 M2 合看決定 MCP**）、M3、M4、M7、M9、M10、M13、M14、M15、M16。

---

## §2 V2.0 專案基座（`PJ-`）

前置：§1.1 的 D12／D13、ADR 0027。

| ☐ | Ticket | 內容 |
|---|---|---|
| ☐ | **PJ-01** | **需求變更與範圍宣告（第一張，不可跳過）**：PRD 增訂、ADR 0027、skill 範圍句修訂、traceability 註冊 |
| ☐ | PJ-02 | 資料層 `0021`：`projects`／`project_workspaces`／`activity_events` ＋ `terminal_sessions.project_id` |
| ☐ | PJ-03 | RBAC `project.view`／`project.manage` ＋ seed `0022` |
| ☐ | PJ-04 | Project API（綁定驗證重用 `authorize_workspace()`） |
| ☐ | PJ-05 | Session 關聯（optional `project_id`） |
| ☐ | PJ-06 | 前端：導覽重整三組 ＋ Project 列表／總覽 |
| ☐ | PJ-07 | 驗證與出口（`10` §2.1 的 7 條） |

**出口**：9 條（`plan/16/06` §5——`10` §2.1 的 7 條，其中第 1、4 條依程式碼事實改寫，另加 2 條）。
**不動 daemon、不動 contract。**

> **執行計畫已寫在 [`plan/16/`](../../plan/16/README.md)**，含一張規劃裡沒有的閘門票 `PJ-00`
> （基線擷取：OpenAPI、`pg_dump`、導覽截圖——那三份快照改完就再也取不到）。
> `PJ-03` 與 `PJ-04` 在該計畫裡是**同一個 PR**（`test_every_action_is_enforced_somewhere`
> 是文字掃描，而 D13 禁止用 `UNENFORCED_ACTIONS` 迴避）。

---

## §3 V2.1 任務看板（`TK-`）

前置：V2.0 出口通過、D3／D4／D7／D8／D11／D13／D14／D15／D28。

| ☐ | Ticket | 內容 |
|---|---|---|
| ☐ | TK-01 | 內化流程定義（六車道、DoR 七項、Gates 六項、模板）＋ 標註 Monstrare 出處 |
| ☐ | TK-01b | 需求與規格資料模型 ＋ **人工表單**（`version2.md` §17：先人工再 Agent） |
| ☐ | TK-02 | 資料層 `0023`／`0024` |
| ☐ | TK-03 | RBAC `task.create`／`task.update`／`task.approve` |
| ☐ | TK-04 | Task API ＋ 進站／Done Gate（V2.1 只強制 `dependsOn`） |
| ☐ | TK-05 | `.cliora/` 投影與情境包（≤4 KB） |
| ☐ | **TK-06** | **`cliora` CLI 首發（本階段關鍵路徑）**——沒有它 Agent 無法記錄任何工作 |
| ☐ | TK-07 | 前端：看板（可拖曳）、藍圖、任務詳情 |
| ☐ | TK-08 | Task ↔ Session |

**出口**：11 條（`10` §2.2）。**不動 daemon、不動 contract。**

---

## §4 V2.2 Agent Runner（`AR-`）

前置：V2.1 出口通過、D16／D17／D17b／D18／D24／D26／D27／D29。

| ☐ | Ticket | 內容 |
|---|---|---|
| ☐ | AR-01 | **ADR 0028**：Runner 模型與 run 生命週期 |
| ☐ | AR-02 | **ADR 0029**：run 的兩種輸出（log 與產物），兩者保留期不同 |
| ☐ | AR-03 | Contract v1.10.0：runner／run 訊息 ＋ fixtures |
| ☐ | AR-04 | Daemon runner 模式（`agentd` 0.8.0） |
| ☐ | AR-05 | Central：run 生命週期、佇列、**原子認領**、租約 |
| ☐ | AR-06 | 看板作為溝通管道（`task ask`／`say`／`messages`） |
| ☐ | AR-06b | **任務卡產物**（存平台不存 node、三層配額、**預設下載不渲染**） |
| ☐ | AR-07 | RBAC `agent.*`／`run.*` ＋ API |
| ☐ | AR-08 | 前端：Agents 頁、派工對話框、Run 詳情、訊息串、產物區 |

**出口**：13 條（`10` §2.4）。**安全審查必然觸發**（無人值守執行 ＋ run log ＋ 產物的 stored XSS）。
⚠️ 已知缺口：本階段 run 仍在使用者 workspace 執行，建議只在測試專案啟用。

---

## §5 V2.3 機密與隔離（`SC-`）

前置：V2.2 出口通過、M11／M12 已量。（金鑰與 git 認證已於 2026-08-08 裁決。）

| ☐ | Ticket | 內容 |
|---|---|---|
| ☐ | **SC-01** | **ADR 0031：機密管理與 SEC-002 修訂（先寫這一份，它決定其餘能否開工）** |
| ☐ | SC-02 | ADR 0030：隔離工作目錄與 git 存取（六條目錄規則 ＋ 五條 git 約束） |
| ☐ | SC-03 | Secret store `0027`（**寫入後永不可讀回**） |
| ☐ | SC-04 | 下放與 **runner 端去識別** |
| ☐ | SC-05 | Daemon：隔離目錄、配額、repo mirror、git（`agentd` 0.9.0） |
| ☐ | SC-06 | 前端：Secrets、Repositories、卡片執行設定、Run 環境 |

**出口**：11 條（`10` §2.5）。**V2 風險最高的一階段**——同時觸發機密流、新儲存面、git 寫入三條，安全審查要分三節寫。

---

## §6 V2.4 交付與驗證（`DV-`）

前置：V2.3 出口通過、PR／MR 供應商已選、M6 已量。

| ☐ | Ticket | 內容 |
|---|---|---|
| ☐ | DV-01 | ADR 0032：**五種** delivery 模式 ＋ 三個誠實性規則 |
| ☐ | DV-02 | PR／MR 建立（**永不自動合併**） |
| ☐ | DV-03 | 執行計畫（append-only 版本列） |
| ☐ | DV-04 | 驗證報告與 `source` 三級（**伺服器端判定**） |
| ☐ | DV-05 | Done Gate（強制，依 delivery 分歧；Admin `--force` 需理由） |
| ☐ | DV-06 | Evidence（矛盾不仲裁） |
| ☐ | DV-07 | 專案智能與跨專案指標 |
| ☐ | DV-08 | 流程可設定性（只允許啟用／停用） |

**出口**：10 條（`10` §2.6）。**安全審查觸發**（對外副作用）。

---

## §7 V2.5 需求釐清與拆解（`RQ-`）

前置：V2.3 出口通過（**不依賴 V2.4，可並行**）、D28、TK-01b 的人工表單已上線。

| ☐ | Ticket | 內容 |
|---|---|---|
| ☐ | RQ-01 | ADR 0033：釐清用既有管道、產出是提案、三個人工關卡、停止條件 |
| ☐ | RQ-02 | 資料模型 `0030` |
| ☐ | RQ-03 | 釐清 run（**一次一個問題**） |
| ☐ | RQ-04 | 拆解 run（每張提案自帶 DoR 七項 ＋ `source`／`delivery`） |
| ☐ | RQ-05 | 人工關卡（規格核准、提案接受、UI 變體選定） |
| ☐ | RQ-06 | PRD Patch 提案（**平台不套用**） |
| ☐ | RQ-07 | UI Mockup 關卡（**可延後**；**依賴 tunnel 整合已啟用**，未啟用則整包不存在） |
| ☐ | RQ-08 | 前端：Intake、釐清對話、規格審閱、提案樹 |

**出口**：11 條（`10` §2.7）。**安全審查不必然觸發。**

---

## §8 ADR 清單

| ☐ | ADR | 主題 | 階段 |
|---|---|---|---|
| ☐ | 0027 | V2 範圍、Monstrare 功能內化與真實來源；紅線 4 的撤銷與換上的四條約束 | V2.0 |
| ☐ | 0028 | Agent Runner 模型與 run 生命週期 | V2.2 |
| ☐ | 0029 | run 的兩種輸出：log 與卡片產物（保留期不同） | V2.2 |
| ☐ | 0030 | 隔離工作目錄與 git 存取 | V2.3 |
| ☐ | 0031 | 機密管理與 SEC-002 修訂 | V2.3 |
| ☐ | 0032 | 交付模式與 PR 建立（紅線 5） | V2.4 |
| ☐ | 0033 | 需求釐清與拆解的形狀 | V2.5 |

每份都要有 **Alternatives rejected 表**——這個 repo 的 ADR 之所以有用，多半是因為那張表把「以後有人會再提一次的東西」先寫掉了。

---

## §9 必須同步修訂的既有文件（`11` §3）

| ☐ | 檔案 | 階段 |
|---|---|---|
| ☐ | `research/prd.md` — Project／Task／Verification 章節 | V2.0 |
| ☐ | `.agent/skills/cliora-project-context/SKILL.md` — 範圍句精確化 | V2.0／V2.4 |
| ☐ | `traceability/requirements.json` — 新需求註冊 | 各階段 |
| ☐ | `docs/permission-matrix.md` — 11 個新動作 | 各階段 |
| ☐ | `docs/error-catalog.md` — 新錯誤碼 | 各階段 |
| ☐ | `research/tech.md` §16.1、`research/style.md` §12 — 右欄 tab（**不刪原文，加註記**） | V2.4 |
| ☐ | `contracts/CHANGELOG.md` — v1.10.0／v1.11.0／v1.12.0 | V2.2–V2.4 |
| ☐ | `README.md`／`deploy/README.md` — 新環境變數、`agentd` 版本 | V2.2 起 |
| ☐ | `docs/runbooks/` — `session-context.md`、run 與機密的處置 | V2.1／V2.3 |
| ☐ | `.gitignore` 建議說明 — 使用者可把 `.cliora/` 加入 | V2.1 |

---

## §10 每階段都要跑的（不可略過）

| ☐ | 事項 |
|---|---|
| ☐ | **旗標關閉回歸套組**（`10` §3）：API 表面、protocol、五個既有路由、Session 全生命週期、檔案面、system terminal、tunnel、RBAC 矩陣、DB schema |
| ☐ | 兩個旗標各自獨立驗證（`PROJECTS_ENABLED=true` ＋ `AGENT_RUNS_ENABLED=false` 時看板可用、Agents 頁不出現） |
| ☐ | `make check` ＋（涉及者）`make integration`／`make e2e`／`make test-db` |
| ☐ | `test_every_action_is_enforced_somewhere` 雙向通過 |
| ☐ | 更新 `plan/NN/0X-implementation-status.md` |
| ☐ | **提出合併請求並停下來等人決定**（`10` §7）——條件全綠只是提案資格，不是核准 |
