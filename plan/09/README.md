# Cliora 版面高度與中央工作區優先 可實作規劃

本目錄把「CLI 終端機只有一半高度、左側 sidebar 太寬、中央工作區沒有拿到它該有的空間」轉成可建立 ticket、撰寫程式與驗收的執行規格。ticket 統一使用 `LY-` 前綴。

這一期**沒有新功能**：不動 protocol、不動 RBAC、不動 daemon、不動任何資料面能力。全部變更都在 `frontend/src` 的四個檔案與兩份規格文件內。

## 為何需要這一期

### 1. CLI 面板的高度被鎖在 24 列，而且鎖得非常穩定

`SessionWorkspaceView.vue:598-604` 的 `.terminal-pane` 用

```css
grid-template-rows: auto minmax(0, 1fr) auto;
```

分配三列給「提示列 / 終端機 / 狀態列」。TERMINAL 面板剛好有三個子元素（`:403-429`），所以 xterm 落在 `1fr` 那一列、填滿高度；**但 CLI 面板只有一個子元素**（`:386-390` 的 `.terminal-host`），auto-placement 把它放進第 1 列，也就是 `auto`——高度由內容決定，而不是由容器決定。

接下來是一個會自我維持的迴圈：

1. `new Terminal({...})`（`useTerminalSession.ts:188-200`）沒有指定 `rows`，xterm 取預設 **24 列**。
2. 掛載時 host 還是空的，`clientHeight === 0`，`fitSafely()`（`:67-74`）依設計拒絕量測，所以 24 列不變。
3. xterm 畫出 24 列，`auto` 列因此長到「24 列的高度」。
4. `ResizeObserver`（`:83-88`、`:219`）觸發 `applyFit()`，FitAddon 量到的 host 高度**正好等於 xterm 自己的高度**，於是算出 24 列。
5. 回到第 3 步。

結果：**不論視窗多高，CLI 永遠是 24 列**。而 `.terminal-pane` 的深色背景仍鋪滿整個面板（`:598-604`），所以畫面看起來是一整片終端機，但可用區只有上半部、prompt 停在中間、點下半部不會 focus。這正是「高度只有一半、難以閱讀與下指令」。

寬度沒有這個問題（`auto` 列的寬度仍是滿的），所以症狀是**只有高度縮水**——與回報一致。

`research/tech.md:1705-1717` 早就寫明「xterm.js / Monaco（擇一佔滿）」，因此這是**實作違反既有規格**，不是規格變更。

### 2. 同一個錯誤在另外兩個面板等著發生

用「列樣板 + auto-placement」決定面板高度的地方共三處，都是靠子元素數量剛好對上才成立：

| 檔案 | 樣板 | 子元素數 | 現況 |
|---|---|---|---|
| `SessionWorkspaceView.vue:598-604` | `auto minmax(0,1fr) auto` | CLI 面板 1 個 | **已壞**（本期主症狀） |
| `PreviewPane.vue:154-161` | `auto auto 1fr` | `.meta` 是 `v-if`（`:110-113`） | **條件性壞掉**：`meta` 不存在時 `.body` 落到第 2 列 `auto`，Monaco 高度塌陷 |
| `FileTree.vue:163-169` | `auto auto auto 1fr` | 正常狀態剛好 4 個 | 目前正確，但任何人多加一列說明文字就會壞 |

只修 CLI 面板等於留著兩顆同型號的地雷。

### 3. 中央工作區被兩層 padding 與一個過寬的 sidebar 夾住

- `tokens.css:31` 的 `--layout-sidebar: 280px`。實際只放五個 13px 的導覽項（`AppLayout.vue:46-60`），最長的 `Enrollment` 連圖示與內距約 120px——**280px 有一半以上是空白**。
- `AppLayout.vue:155` 的 `padding: calc(var(--layout-header) + 24px) 28px 40px` 對表格頁合理，對「終端機就是工作區」（`research/style.md:734-747`）的頁面則是純損失：上下共吃掉 64px，左右各 28px。

`research/style.md:585-611`（§12）明寫 **Terminal 佔最大比例**。目前中央區在 1440 寬下只有約 792px（推算，見 `00-execution-plan.md` §4），而 sidebar 那 280px 幾乎沒有內容。

### 4. 頁面高度有兩套互相矛盾的公式，兩邊都不對

`AppLayout.vue:152-156` 的 main 是 `min-height: 100vh` **加上** 上下 padding（border-box），內容區實際高度是 `100vh - 56 - 24 - 40 = 100vh - 120`。
`SessionWorkspaceView.vue:490-495` 的 `.workspace` 自己算了另一條：`calc(100vh - var(--layout-header) - 48px) = 100vh - 104`。

兩者差 16px，所以 Session Workspace **一直有一條約 16px 的整頁垂直滾動**——一個「不該滾動的固定版面」在滾。根因不是算錯，而是 **main 的高度是隱含的，任何 view 想填滿它就只能自己重新推導一次**。這一期把 main 的高度變成確定值，讓第二套公式沒有存在的理由。

### 5. 現有的自動化擋不住這件事

`frontend/tests/e2e/session.spec.ts:253-334` 是 plan/08 補的版面守門測試，但它**只量水平方向**（`:309-321` 的 `scrollWidth <= clientWidth`）。垂直方向從來沒有人量過，jsdom 也沒有 layout，所以三個面板的高度塌陷可以一路綠燈通過 `make check`、330 個前端單元測試與整條 browser E2E。

**綠燈不等於版面正確**——這與 plan/08 學到的是同一課，只是換了一個軸。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 成功定義、範圍與非目標、11 項固定基線決策、目標幾何（含推算數字）、ticket 波次、共同 DoD、阻擋規則 |
| [01-app-shell-and-height.md](./01-app-shell-and-height.md) | LY-01（App shell 改視窗高度 grid、main 成為唯一滾動容器）、LY-02（Workspace 改 fill 模式，刪掉第二套高度公式） |
| [02-panel-fill.md](./02-panel-fill.md) | LY-03（四個面板一律 flex column 填滿）、LY-04（初次量測與尺寸同步：shell 不再以 24×80 開場） |
| [03-sidebar-and-density.md](./03-sidebar-and-density.md) | LY-05（sidebar 280→208px、fill 模式內距、style.md §9/§22 同步與既有漂移校正） |
| [04-verification-and-exit.md](./04-verification-and-exit.md) | LY-06（量測式 E2E 與 CI 回歸鎖）、LY-07（PRD 新增 AC 與 traceability 註冊）、LY-08（驗收、evidence、exit gate） |
| [05-implementation-status.md](./05-implementation-status.md) | 各 ticket 實作狀態與實際證據；初始均未開工 |

## 使用規則

1. **LY-01 → LY-02 → LY-03 是一條鏈，順序不能顛倒。** LY-03 讓面板去填滿容器；如果容器的高度本身還是錯的（LY-01/LY-02 之前），填滿只是填滿一個錯的框，量測出來的數字也無法解讀。
2. **不准用「調小字級換行數」解決。** xterm `fontSize: 13`（`useTerminalSession.ts:193`）不動。本期的訴求是可讀性，用縮小字體換取行數是把問題換一個方向呈現（決策 D10）。
3. **不准用 `height: 100vh` 或 `calc(100vh - …)` 在任何 view 內重建高度公式。** 高度只有一個來源：app shell（決策 D1）。這一條由 CI grep gate 擋（LY-06）。
4. **面板高度不得依賴子元素的數量或順序。** 一律 flex column + 明確的 `flex: 1 1 auto; min-height: 0`（決策 D3）。這一條同樣由 grep gate 擋。
5. **jsdom 不能當版面證據。** 單元測試只能鎖結構與屬性；幾何一律由 Playwright 量測（決策 D8）。任何以「單元測試通過」宣稱版面正確的 PR 退回。
6. **規格變更先改 `research/style.md`／`research/prd.md`，再同步 `traceability/`。** sidebar 寬度是 style.md 的既有數字（`:497`、`:830`），改程式不改文件會製造新的漂移——這一期的成因之一就是舊漂移（決策 D5、D6）。

## 完成結果

本期通過時：在 1440×900 下進入 Session Workspace，CLI 終端機填滿整個中央面板（**量測值**：`.xterm-screen` 高度 ≥ 面板高度的 90%、列數 ≥ 30），切到預覽再切回來列數不變；整頁沒有垂直滾動條；左側 sidebar 為 208px，中央面板寬度比現況多出約 96px（推算 792 → 888px）；Monaco 預覽在沒有 meta 列時也填滿高度；`research/style.md` §9／§22 與程式的數字一致，`research/prd.md` 有一條可驗證的「Terminal 填滿可用高度」AC 並在 traceability 中備齊四類 primary link；`frontend/tests/e2e/session.spec.ts` 有一個會因為高度塌陷而變紅的量測測試，CI 有三條 grep gate 防止舊寫法回來。
