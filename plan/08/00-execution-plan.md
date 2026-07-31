# 00 — 執行總控（Workspace Tab 化與系統終端機）

## 1. 成功定義

本期要退休四個問題：

**(a) 中央區的空間分配是錯的。** 開啟檔案時 `SessionWorkspaceView.vue:206` 把中央區切成 `grid-template-rows: minmax(0,1fr) minmax(0,45%)`（`:343-345`），CLI 與預覽同時可見但兩者都不足以操作。要換成 tab：同一時間一個面板佔滿，切換成本一次點擊。

**(b) 左欄是一段永久佔位。** `SessionWorkspaceView.vue:201-204` 只有一個 `<h2>Sessions</h2>` 和一句「切換自 Sessions 清單。」，固定佔 200px（`:329`），窄視窗又整欄隱藏（`:390-398`）。切換 session 的實際入口是外層 `/sessions` 清單與 sidebar，左欄要移除，並且 PRD/tech/style/plan/report 五處規格要同步改掉，不能留下「規格說有、程式沒有」的漂移。

**(c) xterm 有一條掛不回來的路徑。** `useTerminalSession.ts:139-140` 的 `mount()` 對已存在的 terminal 直接 return，而唯一呼叫點是 `SessionWorkspaceView.vue:90-99` 的 `onMounted`。容器被卸掉再回來就沒人重掛，終端機寫進脫離 DOM 的節點。現在觸發條件是「初次載入失敗 → Retry 成功」；tab 化後若用 `v-if` 會變成每次切 tab 都觸發。

**(d) workspace 內沒有操作系統的地方。** 使用者要 `git status`、看 log、裝套件時必須離開瀏覽器。這是本期唯一的新功能，也是唯一的範圍變更。

成功的判準不是「畫面看起來對」，而是：切 tab 前後終端機是**同一條 socket**、PTY 尺寸不被隱藏容器污染、沒有任何路徑能讓 xterm 掛不回來；以及若 shell 交付，它是一個受既有 RBAC／audit／ticket 管線管的正規 session，而不是一條旁路。

## 2. 範圍

### 納入

- 中央區 tablist：`CLI`、最多一個 `[filename]` 預覽 tab（`WT-03`）。
- 左欄 Sessions 佔位移除，grid 改兩欄，相關規格文件同步（`WT-01`）。
- xterm 掛載生命週期修正、隱藏期間的 fit/resize 防護（`WT-02`）。
- 系統終端機：`shell` runtime、`terminal.shell` action、node 端停用開關、parent 綁定生命週期、TERMINAL tab（`WT-04`–`WT-08`）。
- traceability 註冊、安全審查、evidence 與 exit gate（`WT-09`–`WT-11`）。

### 不納入

- **面板拖曳調整與收合。** tech §16.1 與 `plan/03/05:33` 要求過，從未實作（grid 寬度是硬寫死的常數）。本期不補，改為在 `WT-01` 一併把規格改成「固定兩欄」——留著一條沒人實作的規格比沒有規格更糟。
- **多檔同開。** 永遠只有一個預覽 tab（決策 D2）。
- **workspace 內切換 session。** 左欄移除即代表放棄 `plan/03/05:35` 的「左欄 session 清單支援切換不同 session」，`watch(() => props.id)`（`SessionWorkspaceView.vue:103-111`）保留但不再是使用者動線（見 §6）。
- **shell 的指令記錄／replay／session 錄影。** 與 `TECH-SEC-08`／ADR 0004 直接衝突（決策 D9）。
- **從 Sessions 清單或 New Session dialog 建立 shell session。** 唯一入口是 TERMINAL tab（決策 D13）。
- **shell 的檔案上傳／下載、Central 端 SSH、多 node 廣播執行。** 永久非目標，不因為有了 shell 就順勢納入。

## 3. 固定基線決策

這些是本目錄後續所有 ticket 的前提。改動任一項要回來改這張表，不要在 ticket 內就地改主意。

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D1 | 中央區呈現方式 | 上方 `role="tablist"`，選中的 panel 佔滿整個中央區 | 45% 分割讓 CLI 與預覽同時不好用；tab 的代價是一次點擊，換來兩邊都完整 |
| D2 | 預覽 tab 數量 | 恆為 0 或 1 | 使用者明確決定不需要多檔。`previewPath` 維持單一 ref（`SessionWorkspaceView.vue:69`），不必處理 tab 溢出與 model 上限 |
| D3 | 左欄 Sessions | 移除，grid 改 `1fr 300px` | 外層清單 + sidebar 已是完整入口；200px 給 Terminal 更值得（style §12「Terminal 佔最大比例」） |
| D4 | 非作用中 tab 的處理 | **CSS 隱藏（`v-show`）保留 DOM**，不 `v-if` | xterm 一旦卸掉就掛不回來（§1c）；且 CLI 隱藏期間必須持續收流，否則切回來會出現本不該有的 gap |
| D5 | 系統終端機的實作路徑 | 新增 runtime id **`shell`**，走既有 session 管線 | ws-ticket、relay、single-writer、reconnect、snapshot、terminate、audit 全部沿用。`daemon/internal/session/manager.go:78` 的 `StartSession(id, runtimeID, workspace, binary, rows, columns)` 已經是 runtime-generic 的，另開一條平行通道等於把這些全部重寫一次。**而且前端仍然只送 runtime id，`SEC-002` 完整保住** |
| D6 | 誰決定一個 node 能不能開 shell | **node 端 `config.yaml` 的 `runtime.shell`，預設啟用（設定缺項即視為啟用），可明確 `enabled: false` 停用** | 沿用既有 per-runtime `{Enabled, Binary}` 形狀（`daemon/internal/config/config.go:102`、`install/plan.go:56-59`），不新增設定概念。**2026-07-31 決定改為預設啟用**：需求是「完整的 terminal 功能」，逐台改檔重啟的門檻與之不符。node 擁有者仍保有否決權（明確停用），Central 依然不能替 node 開啟。**代價：既有 node 升級 daemon 後會一併獲得此能力**，必須在 release note 與 runbook 明講（`03-…md` §1.2） |
| D7 | RBAC | 新增 action **`terminal.shell`**，授予 **Admin + Developer** | **2026-07-31 決定**。與 `terminal.operate`／`session.terminate` 的授予範圍一致；Developer 本來就能在自己的 session 操作 CLI。邊界改由 **ownership** 承擔：只能在自己擁有的 session 上開 shell，不能在他人的 session 開、不能 attach 他人的 shell。Viewer 一律無此 action。**這使「daemon 非 root 執行」成為載重條件而非最佳實踐**（`04-…md` WT-10 第 10 項） |
| D8 | shell session 建立時機 | 第一次點 TERMINAL tab 才建立；tab 關閉或離開 workspace 即 terminate | `sessions_per_node_max = 10`、`sessions_per_user_max = 20`（`backend/app/settings.py:73,79`）。每開一個 workspace 就多一個 session 會直接砍半可用容量 |
| D9 | 是否記錄 shell 指令 | **不記錄** | ADR 0004／`TECH-SEC-08`：terminal bytes 不得進 DB 或 log。改為記 session 級事件（create/attach/terminate）並在 metadata 標 `runtime: shell`，讓稽核看得到「誰在哪個 node 開過 shell」而不是他打了什麼 |
| D10 | 右側檔案樹綁定 | 永遠綁**頁面的 CLI session**，不隨 tab 切換 | 樹是 workspace 的視圖，不是某個 tab 的附屬品。`filesSessionId`（`SessionWorkspaceView.vue:47-49`）的守衛邏輯不變 |
| D11 | `SCOPE-011` 的處置 | **2026-07-31 決定：選項 A（收窄），以 PRD 修訂與 ADR 0021 落地** | 它的守門測試 `backend/tests/test_scope_guards.py::test_scope_011_the_front_end_cannot_name_a_command` 只斷言 session start 沒有 command/args/argv/shell/env/entrypoint 欄位——加 `shell` runtime **測試全綠**。這件事只有人能擋 |
| D12 | 契約版本 | **v1.5.0（compatible）** | `runtime` 是 wire 上的 enum（`contracts/v1/schemas/messages/session-start.schema.json`、`runtime-item.schema.json`），新增值是契約變更，不是內部實作 |
| D13 | shell session 的可見性 | Sessions 清單**過濾掉** `runtime=shell`；Node 詳情頁與 Dashboard 照實計入 | 它是某個 CLI session 的附屬視圖，不是獨立工作單位，混在清單裡點進去會得到一個沒有 CLI 的 workspace。但資源計數必須誠實，否則會出現「清單顯示 3 個、node 卻滿載」 |

## 4. 目標布局

```text
Session Header（名稱 / Runtime / Workspace / Session 狀態 / 連線狀態 / Writer|Viewer / 動作）
┌──────────────────────────────────────────────┬──────────────┐
│ ┌ CLI ┬ [app.py] ┬ TERMINAL ┐                │  Workspace   │
│ │                                          │ │  File Tree   │
│ │        選中的 panel 佔滿整個中央區        │ │              │
│ │                                          │ │              │
│ └──────────────────────────────────────────┘ │              │
└──────────────────────────────────────────────┴──────────────┘
```

- `CLI` 恆存在且為預設。
- `[filename]` 只在有開啟檔案時存在，顯示 basename，完整 rel_path 放 `title`（**不得出現 node 絕對路徑**，P3 規則，同 `workspaceLabel` 的處理方式 `SessionWorkspaceView.vue:53-57`）。
- `TERMINAL` 只在「使用者持有 `terminal.shell`」且「該 session 為自己擁有」且「該 node 未停用 shell」時存在（三者由 server 端 `can_open_shell` 合併計算）。
- grid 從 `200px 1fr 300px` 改為 `1fr 300px`；`@media (max-width: 1100px)` 內的 `.sessions-rail` 規則一併移除。

## 5. 執行波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（可立即開工）** | `WT-01` | 左欄 Sessions 退場與規格同步 | — |
| | `WT-02` | xterm 掛載生命週期修正（`WT-03` 的前置條件） | — |
| | `WT-03` | 中央區 Tab 化（`CLI` / `[filename]`） | WT-02 |
| **1（決策閘門）** | `WT-04` | ADR 0021、PRD 修訂與 `SCOPE-011` 處置 | WT-03 合併（避免版面與 shell 在同一份 diff） |
| | `WT-05` | 契約 v1.5.0、`terminal.shell` action、migration `0012`/`0013` | **WT-04 核准** |
| **2** | `WT-06` | Daemon `shell` runtime 與 node 端停用開關 | WT-05 |
| | `WT-07` | Central shell session（parent 綁定、authz 特例、audit、清單過濾） | WT-05 |
| | `WT-08` | 前端 TERMINAL tab | WT-06、WT-07 |
| **3** | `WT-09` | traceability 註冊與影響分析 | WT-03（A 部分）／WT-08（B 部分） |
| | `WT-10` | 安全審查 | WT-08 |
| | `WT-11` | 驗收、evidence 與 exit gate | 全部 |

## 6. 已知取捨：原地切換的三個缺陷降級為「不修」

左欄移除後 `watch(() => props.id)`（`SessionWorkspaceView.vue:103-111`）不再是使用者動線（只剩手動改 URL 會走到）。以下三項因此**明確決定不修**，並記錄於此以免將來被當成漏掉的 bug：

1. `connect()`（`useTerminalSession.ts:70-112`）沒有 `terminal.reset()`，原地換 session 會把前一個的 scrollback 留在畫面上。
2. `role`（`:29`）與 `exit`（`:27`）在 `connect()` 中未重設，header 會沿用舊 session 的 Writer/Viewer 標籤直到伺服器送來 `terminal.role`。
3. watch 無條件 `void terminal.connect(next)`，即使 `resource.run()` 回 forbidden 也會去換 ticket，被 403 後進退避重連迴圈。

**但 §1c 的 mount 缺陷不在此列**，它與切換無關且現在就會踩到，由 `WT-02` 修掉。

## 7. 每張 ticket 的完成格式

1. **產物清單**：新增/修改的檔案逐一列出，含理由。
2. **測試**：新增的自動測試與其斷言對象。「可手動展示」不能替代自動測試。
3. **規格同步**：本 ticket 動到的 PRD/tech/style/ADR/traceability 條目。
4. **證據**：可重跑的指令與其輸出位置。
5. **未關項**：本機關不掉的（例如 WebKit E2E）明確標為 CI-gated，不含糊帶過。

## 8. 阻擋規則

### PR 階段

- 波次 0 的任何 PR 出現 `shell`、`terminal.shell`、runtime enum 或 migration 變更 → 退回。
- `WT-03` 的 PR 若中央區使用 `v-if` 切換 CLI panel → 退回（違反 D4，且會重新引入 §1c）。
- 任何新增 action key 的 PR 未同步 `backend/app/services/rbac.py`、seed migration、`frontend/src/api/dto.ts` 三處 → `backend/tests/db/test_permission_matrix.py` 會擋下，不要用 skip 繞過。
- 修改契約的 PR 必須先於 consumer 合併，並同步 schema、`contracts/v1/fixtures/`、`contracts/v1/fixtures/manifest.json`、`contracts/CHANGELOG.md` 與 Python／Go／TypeScript 三個 consumer。
- 移除既有規格行為（左欄清單、上下分割、面板拖曳/收合）而未在 traceability 留下 `deprecated` + `supersedes` + rationale → `scripts/trace validate` 失敗。

### 上線階段

- `WT-04` 未核准 → 波次 2 以後的程式不得合併，即使已經寫好。（**已於 2026-07-31 核准，選項 A**）
- **`WT-10` 安全審查完成前不得部署到正式環境。** D6／D7 都採了較寬的預設，補償控制因此全部落在 ownership、audit 與「daemon 非 root」上——這三項未經對抗測試證明之前，寬預設不能上線。
- **部署前必須確認 daemon 的執行身分不是 root。** 這一項從「應該做」變成阻擋條件：shell 不提升任何權限，它把 daemon 既有的權限暴露成互動介面，所以 daemon 的執行身分就是這個功能的權限上界。
- **既有 node 升級前必須先發 release note。** 升級後 shell 即可用（D6），這是能力變更而非修補，不得靜默發布。

## 9. 完成定義

`make check` 與 `make traceability` 全綠；`scripts/trace coverage --scope all --strict` 退出 0（本期新增的 requirement 已備齊 planned_by／specified_by／implemented_by／verified_by 四類 primary link，缺任一項會因 criticality `must` 而阻擋 release）；版面部分在 1440×900 與 1100px 以下皆無水平溢位、tablist 可鍵盤操作且 WCAG AA；shell 部分（若交付）通過 `WT-10` 的七項對抗測試且無未處理 Critical/High finding。
