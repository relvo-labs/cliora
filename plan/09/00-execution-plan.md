# 00 — 執行總控（版面高度與中央工作區優先）

## 1. 成功定義

本期要退休四個問題：

**(a) CLI 面板的高度被鎖在 24 列。** `SessionWorkspaceView.vue:598-604` 的列樣板配三列，CLI 面板只有一個子元素（`:386-390`），auto-placement 把它放進 `auto` 列；xterm 預設 24 列 → `auto` 列長成 24 列高 → FitAddon 量到的正好是 xterm 自己的高度 → 永遠 24 列。詳細迴圈見 `README.md` §1。

**(b) 同型錯誤還有兩處。** `PreviewPane.vue:154-161`（`.meta` 是 `v-if`，不存在時 Monaco 塌陷）與 `FileTree.vue:163-169`（目前靠子元素剛好 4 個成立）。

**(c) 中央工作區拿到的空間太少。** `--layout-sidebar: 280px`（`tokens.css:31`）餵五個 13px 導覽項；`AppLayout.vue:155` 的上下 64px／左右 28px 內距對「終端機就是工作區」的頁面是純損失。`research/style.md:585-611` 要求 Terminal 佔最大比例。

**(d) 頁面高度有兩套公式。** `AppLayout.vue:152-156` 隱含 `100vh - 120`，`SessionWorkspaceView.vue:494` 明寫 `100vh - 104`，差 16px 造成整頁垂直滾動。根因是 main 的高度是隱含值，view 想填滿只能自己重新推導。

成功的判準不是「看起來變高了」，而是**量測值**：

1. `#panel-cli` 內 xterm 的畫面高度 ≥ 面板 clientHeight 的 90%，且 1440×900 下列數 ≥ 30。
2. 切到 `[filename]` 再切回 `CLI`，列數與 socket 都不變（不得因為重新 fit 而送出錯誤尺寸或觸發 gap）。
3. `document.documentElement.scrollHeight <= clientHeight`（整頁無垂直滾動），且維持 plan/08 已有的無水平溢位條件。
4. 1440 寬下 sidebar 寬度 ≤ 220px，中央面板寬度 ≥ 860px。

## 2. 範圍

### 納入

- App shell 改為視窗高度 grid，`main` 成為唯一滾動容器（`LY-01`）。
- `AppLayout` 新增 `fill` 模式；Session Workspace 改用它並刪除自有的 `calc(100vh …)`（`LY-02`）。
- CLI／TERMINAL／Preview／FileTree 四個面板改 flex column 填滿（`LY-03`）。
- 首次量測與尺寸同步：shell session 不再以硬寫的 24×80 開場（`LY-04`）。
- sidebar 280 → 208px、fill 模式內距、`research/style.md` §9／§22 數字同步與既有漂移校正（`LY-05`）。
- 量測式 E2E、CI 回歸鎖、PRD 新增 AC 與 traceability 註冊、evidence 與 exit gate（`LY-06`–`LY-08`）。

### 不納入

- **拖曳分隔線與面板收合。** plan/08 已把它從規格移除（`research/tech.md:1745-1748`），本期不復活。
- **sidebar 收合／展開開關。** 需求是「調窄」，一個固定的窄寬度就滿足；加一個可切換狀態要處理持久化、鍵盤操作與兩種寬度下的量測，成本與收益不成比例。若日後要做，前置條件是本期的 `fill` 模式與量測測試已在（決策 D9）。
- **Status Bar。** `research/style.md:477-505` 規劃了它、`tokens.css:32` 也留了 `--layout-status: 28px`，但從未實作。本期不實作，只在 token 旁註明現況（決策 D7）——刪掉 token 會讓 style.md 與 tokens 更難對照。
- **調整 xterm 字級或行高換取行數。** 決策 D10。
- **多檔預覽 tab、行動版版面、Dashboard／Nodes／Audit 的視覺改版。** 這些頁面只被動受益於 shell 幾何修正，不在本期主動改動它們的內部版面。

## 3. 固定基線決策

這些是本目錄後續所有 ticket 的前提。改動任一項要回來改這張表，不要在 ticket 內就地改主意。

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D1 | 高度的唯一來源 | `.shell` 自己是視窗高度的 grid：`grid-template-columns: var(--layout-sidebar) 1fr`、`grid-template-rows: var(--layout-header) minmax(0, 1fr)`、`height: 100vh; height: 100dvh;`。header／aside **不再 `position: fixed`** | 目前 header 與 aside 是 fixed，main 只能用 `min-height: 100vh` + padding 補位，於是 main 的高度是隱含的，任何想填滿它的 view 都得自己重算一次（§1d）。grid 讓 main 有**確定高度**，view 只需 `height: 100%`，第二套公式從此沒有存在理由 |
| D2 | 用 `dvh` 而非 `height: 100%` 鏈 | `height: 100vh` 後接 `height: 100dvh` | `index.html` 的 `html`／`body`／`#app` 都沒有高度規則（`frontend/index.html:11-12`、`theme/base.css` 無 `#app` 規則），走 `100%` 鏈要新增三層規則；viewport 單位一層解決。`dvh` 另外照顧 `research/style.md:923-941` 提到的平板唯讀情境，`100vh` 作為前置宣告是舊瀏覽器的 fallback |
| D3 | 面板填滿的寫法 | **flex column + `flex: 1 1 auto; min-height: 0`**，禁止用「auto/1fr 依子元素順序」的 grid 列樣板決定面板高度 | 列樣板要求「子元素數量與順序」永遠對上，而三個面板裡有兩個的子元素是 `v-if`（`SessionWorkspaceView.vue:413-429`、`PreviewPane.vue:110-113`）。這是本期主症狀的直接成因，修法必須讓它**不可能再依賴數量** |
| D4 | 面板疊放方式 | 不變：所有 panel 疊在 `.center` 的同一個 grid cell（`SessionWorkspaceView.vue:570-583`），非作用中的用 `v-show` 隱藏 | plan/08 D4 的正確性條件（隱藏≠卸載、隱藏中不得 fit）繼續成立。本期只改「面板內部」怎麼填滿，不改「面板之間」怎麼疊 |
| D5 | sidebar 寬度 | `--layout-sidebar: 280px` → **`208px`**；`@media (max-width: 900px)` 的 64px 圖示欄**不變** | 208px 對最長標籤 `Enrollment`（約 120px 含圖示與內距）仍有餘裕，且 1440 下把中央區從約 792px 推到約 888px（§4）。**斷點不動**：把收合點提前到 1280px 會讓 1280 筆電失去文字標籤，那是另一個決定，不該夾在這一期 |
| D6 | 右側檔案樹寬度 | 程式維持 `300px`（`SessionWorkspaceView.vue:563`）；把 `research/style.md:501` 的 Inspector `360px` **校正為 300px** | 這是 plan/08 留下的既有漂移（規格 360、實作 300）。本期既然要動 style.md 的版面數字，就一次對齊；**不改程式**，因為 300px 已是對中央區有利的方向 |
| D7 | Status Bar 與 `--layout-status` | 不實作；token 保留並在 `tokens.css` 註明「Status Bar 尚未實作，保留給 style.md §9／§12」 | 目前沒有任何使用者（`grep -rn "layout-status" frontend/src` 只有宣告本身）。刪掉會讓 style.md 的版面圖找不到對應 token，留著沒註解會讓下一個人以為它在生效 |
| D8 | 驗收方式 | 幾何一律以 Playwright **量測**；jsdom 單元測試只鎖結構與屬性；再加 CI grep gate 鎖「不得復活的寫法」 | jsdom 沒有 layout，所以三處面板塌陷可以在 330 個單元測試與整條 E2E 全綠下存活（`README.md` §5）。既有的 `session.spec.ts:253-334` 只量水平方向，本期補垂直方向 |
| D9 | 是否加 sidebar 收合開關 | **不加**（見 §2 不納入） | 需求是調窄；固定窄寬度即滿足，且沒有新狀態要持久化 |
| D10 | 是否用字級換行數 | **不改** `fontSize: 13`（`useTerminalSession.ts:193`） | 本期訴求是「難以閱讀」。用縮小字體換行數是把可讀性問題換個方向呈現，不是解決 |
| D11 | 是否順手改其他頁面版面 | 不改。Dashboard／Nodes／Audit／Enrollment 只因 shell 幾何改變而**被動**受影響，本期只驗證它們沒有回歸 | 這些頁面現在依賴整頁滾動；D1 之後滾動容器變成 `main`。這是必須驗證的行為變更（`LY-01` 測試項），但不是改版理由 |

## 4. 目標幾何（1440×900）

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Header  56px                                                           │
├──────────┬─────────────────────────────────────────────────────────────┤
│ Sidebar  │ main（唯一滾動容器；fill 模式時 overflow: hidden）           │
│  208px   │  ┌ Session Header ────────────────────────────────────────┐ │
│  (280)   │  │ ┌ CLI ┬ [app.py] ┬ TERMINAL ┐        │ Workspace       │ │
│          │  │ │                          │        │ File Tree       │ │
│          │  │ │  選中面板佔滿：約 888×736  │        │  300px          │ │
│          │  │ │  （現況 792×712，實際可用  │        │                 │ │
│          │  │ │    高度只有 ~408）        │        │                 │ │
│          │  │ └──────────────────────────┘        │                 │ │
└──────────┴─────────────────────────────────────────────────────────────┘
```

**數字全部是推算，不是量測值**，用途是決定方向與提供 `LY-06` 的斷言下界；實際值由 `LY-06` 量測後填進 `05-implementation-status.md`。

| 項目 | 現況（推算） | 目標（推算） | 差 |
|---|---|---|---|
| main 寬 | 1440 − 280 = 1160 | 1440 − 208 = 1232 | +72 |
| main 內容寬（左右內距） | 1160 − 28×2 = 1104 | 1232 − 16×2 = 1200 | +96 |
| 中央面板寬（`1fr 300px`、gap 12） | 1104 − 312 = **792** | 1200 − 312 = **888** | **+96（+12%）** |
| main 內容高（上下內距） | 900 − 56 − 24 − 40 = 780（而 `.workspace` 卻用 796 → 16px 整頁滾動） | 900 − 56 − 12×2 = **820** | +40 |
| 中央面板高（扣 Session Header ≈44、tab bar ≈32＋gap 8） | ≈ **712** | ≈ **736** | +24 |
| CLI 實際可用高度 | ≈ **408（24 列，約面板的 57%）** | ≈ **736（約 43 列）** | **+80%** |

最後一列才是這一期真正的收益：中央區變寬變高各約 3% 是次要的，**把 57% 的可用高度變回 100%** 是主要的。

## 5. 執行波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（幾何基礎，必須依序）** | `LY-01` | App shell 改視窗高度 grid，`main` 成為唯一滾動容器 | — |
| | `LY-02` | Session Workspace 改 `fill` 模式，刪除第二套高度公式 | LY-01 |
| | `LY-03` | 四個面板改 flex column 填滿（CLI／TERMINAL／Preview／FileTree） | LY-02 |
| **1（可與波次 0 並行審查，但後合併）** | `LY-04` | 首次量測與尺寸同步（shell 不再以 24×80 開場） | LY-03 |
| | `LY-05` | sidebar 調窄、fill 內距、style.md 數字同步 | LY-01 |
| **2（驗證與退出）** | `LY-06` | 量測式 E2E 與三條 CI 回歸鎖 | LY-03、LY-05 |
| | `LY-07` | PRD 新增 AC、traceability 註冊與影響分析 | LY-06（selector 必須與測試同一個 PR） |
| | `LY-08` | 驗收、evidence 與 exit gate | 全部 |

`LY-05` 只碰 token 與內距，技術上可先合併；但**它會改變 `LY-06` 要斷言的數字**，所以兩者必須在同一輪驗證內收斂。

## 6. 每張 ticket 的完成格式

1. **產物清單**：新增/修改的檔案逐一列出，含理由。
2. **測試**：新增的自動測試與其斷言對象。「可手動展示」不能替代自動測試；**「單元測試通過」不能替代幾何量測**（D8）。
3. **規格同步**：本 ticket 動到的 PRD/tech/style/traceability 條目。
4. **證據**：可重跑的指令與其輸出位置。
5. **未關項**：本機關不掉的（例如 WebKit E2E）明確標為 CI-gated，不含糊帶過。

## 7. 阻擋規則

### PR 階段

- 任何 view 或 component 內出現 `100vh`／`100dvh`／`calc(100vh - …)` 的高度宣告（`AppLayout.vue` 與 `LoginView.vue` 除外）→ 退回。高度只有一個來源（D1），這一條由 `LY-06` 的 grep gate 擋。
- 面板高度改回「以子元素順序對上 `auto`／`1fr` 列」的寫法 → 退回（D3）。同樣由 grep gate 擋。
- 把 CLI panel 從 `v-show` 改成 `v-if`、或對隱藏容器呼叫 `fit()`／送 `terminal.resize` → 退回。這是 plan/08 已經付過代價的正確性條件（`research/tech.md:1728-1740`），本期不得因為版面重構而動它。
- 以調整 `fontSize`／`lineHeight` 取得行數 → 退回（D10）。
- 改了 `--layout-sidebar` 或 `.rail` 寬度卻沒同步 `research/style.md` §9／§22 → 退回（D5、D6，且違反 `README.md` 使用規則 6）。
- 只有單元測試、沒有 Playwright 量測的版面 PR → 退回（D8）。

### 上線階段

- **`LY-06` 的量測測試必須在 chromium 與 firefox 本機實跑通過**，WebKit 可標為 CI-only（沿用 plan/08 的處理：WebKit 需 root 安裝系統函式庫）。
- **Dashboard／Nodes／Audit／Enrollment 四頁的滾動行為必須實測過**。D1 把滾動容器從 document 換成 `main`，這四頁的長表格是唯一會踩到的地方（`LY-01` 測試項）。

## 8. 完成定義

`make check` 與 `make traceability` 全綠；`scripts/trace coverage --scope all --strict` 退出 0（本期新增的 criterion 已備齊 planned_by／specified_by／implemented_by／verified_by 四類 primary link）；`LY-06` 的四項量測斷言（§1）在 1440×900 與 1000×800 兩個尺寸下皆通過；plan/08 既有的無水平溢位斷言仍然通過；`research/style.md` §9／§22 與 `tokens.css` 的數字一致，`05-implementation-status.md` 記錄的是**量測值**而非本文件的推算值。
