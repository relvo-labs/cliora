# 03 — Sidebar 寬度與版面密度（LY-05）

## LY-05 — sidebar 280 → 208px、fill 內距、style.md 數字同步

### 現況與問題

`tokens.css:31` 的 `--layout-sidebar: 280px` 用來放五個導覽項（`AppLayout.vue:46-60`）：

| 導覽項 | 內容寬（推算：13px 字 + 圖示 11px gap + `padding: 11px`，`AppLayout.vue:138-146`） |
|---|---|
| Dashboard | ≈ 105px |
| Nodes | ≈ 85px |
| Sessions | ≈ 100px |
| Enrollment | ≈ 120px |
| Audit | ≈ 85px |

加上 aside 自己的 `padding: 0 12px`（`:130`），最長項需要約 **144px**。280px 有將近一半是空白，而同一個畫面上的中央工作區只有約 792px（`00-…md` §4）。

`research/style.md:585-611`（§12）明寫 Terminal 佔最大比例，`:734-747`（§18）寫「Terminal 就是工作區，不要包一層 Card」。280px 的導覽欄與這兩條方向相反。

### 決定的數字

| 項目 | 現況 | 目標 | 說明 |
|---|---|---|---|
| `--layout-sidebar` | 280px | **208px** | 最長項需 ≈144px，208px 留 64px 餘裕：中文化標籤或多一個項目都不會擠。再窄（例如 176px）收益只剩 32px，但 `Enrollment` 這類字就開始貼邊 |
| 收合斷點 | `@media (max-width: 900px)` → 64px 圖示欄 | **不變** | 提前到 1280px 會讓 1280 筆電失去文字標籤，那是另一個取捨（決策 D5）。本期只調常態寬度 |
| fill 模式內距 | main `24px 28px 40px` | **`12px 16px`**（僅 fill 頁面） | 由 `LY-02` 實作，數字在此定案：上下共省 40px、左右共省 24px，全部進入終端機 |
| 非 fill 頁面內距 | `24px 28px 40px` | **不變** | 表格頁需要留白，且沒有人抱怨它們 |
| 右側檔案樹 | 程式 300px、style.md 寫 360px | **程式 300px 不變，文件校正為 300px** | 決策 D6。這是 plan/08 留下的既有漂移，方向對中央區有利，所以校正文件而不是改程式 |

### 產物清單

| 檔案 | 動作 | 理由 |
|---|---|---|
| `frontend/src/theme/tokens.css:31` | `--layout-sidebar: 280px` → `208px` | 主變更。**唯一的寬度來源**：`AppLayout.vue:129`（`LY-01` 後改為 grid 欄）與 `:154` 都讀這個 token，`grep -rn "layout-sidebar" frontend/src` 確認沒有第三處 |
| `frontend/src/theme/tokens.css:32` | `--layout-status: 28px` 上方加註解 | 決策 D7：目前沒有任何使用者，留著沒註解會讓人以為 Status Bar 已實作。註解要寫明「保留給 style.md §9／§12 的 Status Bar，尚未實作」 |
| `research/style.md:495-497` | Sidebar `280px` → `208px` | 規格與程式必須同一個數字（`README.md` 使用規則 6） |
| `research/style.md:499-501` | Inspector `360px` → `300px` | 校正既有漂移（D6） |
| `research/style.md:828-832` | token 區塊 `sidebar: 280` → `208`、`inspector: 360` → `300` | §9 與 §22 是同一組數字的兩個列表，只改一處會製造新漂移 |
| `research/style.md:477-491`（§9 版面圖） | 圖中若標了寬度則同步；並補一行說明 fill 模式 | 見下 |

§9 要補的一行（因為這是新增的版面概念，不只是數字變更）：

> Session Workspace 這類「頁面本身就是固定版面」的畫面，Main Workspace 不使用一般頁面的內距，改為 `12px 16px`，並且不整頁滾動——滾動發生在面板內部（Terminal viewport、Monaco、File Tree）。

### 測試

| 層 | 測試 | 斷言 |
|---|---|---|
| 幾何（`LY-06`） | Playwright `layout: the centre pane gets the space` | 1440 寬下 `aside` 的 `clientWidth` ≤ 220；中央面板 `clientWidth` ≥ 860 |
| 一致性（`LY-06`） | CI grep gate | `research/style.md` 的 `sidebar:` 數字與 `tokens.css` 的 `--layout-sidebar` 一致（見 `04-…md` 的 gate 3） |
| 既有回歸 | plan/08 的 `layout: no horizontal overflow…`（`session.spec.ts:253-334`） | 1440×900 與 1000×800 皆無水平溢位。**sidebar 變窄讓 main 變寬，理論上只會讓溢位更不可能**，但 64px 圖示欄那條路徑要重跑確認 |

### 一併確認、但不在本期修的既有漂移

誠實記錄，以免下一個人以為是本期造成的：

1. **`research/style.md:824-826` 的 `font: body: Inter / mono: JetBrains Mono`** 與實作不符：`theme/base.css` 的註解已說明 MVP 不打包任何字型檔（ADR 0016），實際是 system stack；`useTerminalSession.ts:192` 的 `"JetBrains Mono, ui-monospace, monospace"` 只是「有裝就用」。這是字型議題，與版面無關，本期不動。
2. **Status Bar（`research/style.md:477-509`、§12 的版面圖）從未實作。** 決策 D7 維持不實作，只補 token 註解。
3. **`research/style.md:923-941` 說「平板僅提供唯讀模式」**，但目前沒有任何唯讀模式的實作。與本期無關，不動。

### 證據

- `cd frontend && npm run build`
- `grep -rn "layout-sidebar" frontend/src` → 僅 `tokens.css` 宣告與 `AppLayout.vue` 使用
- `grep -n "sidebar" research/style.md` → §9 與 §22 皆為 208
- `LY-06` 量測輸出：aside 寬度與中央面板寬度的實際值記進 `05-implementation-status.md`

### 未關項

無。
